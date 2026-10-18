#!/usr/bin/env python3
"""
Per-port control for a plain powered USB hub, through the kernel.

Written for the Plugable 7-in-1 powered hub that replaces the Coolgear switch.
The difference that matters: the Coolgear has an FT232R control chip and an
ASCII serial protocol whose commands are a bitmask that turns exactly one port
on (see webserver/usbhub_ascii.py -- PORT_ON_CMDS "already ensures only one
port is on"). A plain hub has no control chip, so port control goes through the
kernel's own per-port power switching instead, and nothing enforces
exclusivity. Exclusivity becomes policy here rather than a property of the
wire protocol.

Two mechanisms, in preference order:

  1. "uhubctl", which issues the USB SET/CLEAR_FEATURE(PORT_POWER) requests
     directly. It also reports whether a hub claims per-port power switching,
     which is the only machine-readable answer to "does off mean unpowered?".
  2. sysfs: writing 1 to <hub>:1.0/<hub>-portN/disable. The kernel clears
     PORT_POWER as part of this where the hub supports it.

WHAT "OFF" ACTUALLY MEANS -- read this before trusting it for power saving.
A port reporting disabled guarantees the *device is gone from the bus*. It does
NOT by itself guarantee VBUS is removed: a hub that reports ganged power
switching (or lies about per-port switching, which cheap hubs do) will drop the
data link while still feeding 5 V. The USB spec's LPSM field distinguishes the
two, uhubctl reports it, and this module passes that through as
power_switching. The only proof for a given hub is a current measurement at the
port -- see probe_report() and the WARNING it prints.

Root is required to change anything. Reading state needs no privileges, which
is why the webserver container can render the page but cannot act on it: its
/sys/devices is mounted read-only, so the write path lives in the root helper
service that imports this module.
"""

import glob
import json
import os
import re
import subprocess

__all__ = [
    "HubPorts", "discover_hubs", "probe_report", "UHUBCTL", "HubError",
]

UHUBCTL = "/usr/sbin/uhubctl"

# A hub's ports appear under the hub's *interface* directory, not the hub
# device itself: /sys/bus/usb/devices/1-2:1.0/1-2-port3/. Interface 0 is where
# the kernel hangs the port children.
#
# Two naming shapes, and the difference is not cosmetic:
#   external hub  1-2:1.0/1-2-port3    -> attached device is 1-2.3
#   root hub      1-0:1.0/usb1-port1   -> attached device is 1-1
# So the port directory name cannot be turned into the device path by one rule.
# port_device_path() holds both.
_PORT_DIR_RE = re.compile(r"^(?P<hub>(?:usb)?[\d.-]+)-port(?P<port>\d+)$")


def port_device_path(port_prefix, port):
    """Where the device attached to this port appears in sysfs."""
    base = "/sys/bus/usb/devices"
    if port_prefix.startswith("usb"):
        # Root hub usbN: its children are N-<port>, not usbN.<port>.
        return f"{base}/{port_prefix[3:]}-{port}"
    return f"{base}/{port_prefix}.{port}"


class HubError(RuntimeError):
    """A hub operation failed in a way the caller should surface, not retry."""


def _read(path, default=""):
    """sysfs reads race with device teardown; a vanished attribute is not an
    error, it means the device left between listing and reading."""
    try:
        with open(path) as handle:
            return handle.read().strip()
    except (OSError, UnicodeDecodeError):
        return default


def _hub_interface_dirs():
    """Every USB interface directory that has port children, i.e. every hub."""
    found = {}
    for port_dir in glob.glob("/sys/bus/usb/devices/*/*-port*"):
        interface = os.path.dirname(port_dir)
        match = _PORT_DIR_RE.match(os.path.basename(port_dir))
        if match:
            ports, _ = found.setdefault(interface, ([], match.group("hub")))
            ports.append(int(match.group("port")))
    return {k: (sorted(v[0]), v[1]) for k, v in found.items()}


def discover_hubs():
    """
    Every hub the kernel knows, with its ports and what is attached.

    Returns a list of dicts, root hubs included -- the Pi's own controllers
    appear here too (usb1..usb4) and are deliberately not filtered out: the
    Alfa currently sits on a direct root port, so being able to see and name
    that is useful. Callers select by vid_pid or path.
    """
    hubs = []
    for interface, entry in sorted(_hub_interface_dirs().items()):
        ports, prefix = entry
        # The hub device is the interface minus its ":1.0", except for a root
        # hub, where the interface is "1-0:1.0" and the device is "usb1".
        hub_dev = (f"/sys/bus/usb/devices/{prefix}" if prefix.startswith("usb")
                   else interface.rsplit(":", 1)[0])
        hubs.append({
            "hub": prefix,
            "sysfs": hub_dev,
            "interface": interface,
            "vid_pid": f"{_read(hub_dev + '/idVendor')}:{_read(hub_dev + '/idProduct')}",
            "product": _read(hub_dev + "/product"),
            "manufacturer": _read(hub_dev + "/manufacturer"),
            "ports": ports,
            "is_root_hub": prefix.startswith("usb"),
        })
    return hubs


def _uhubctl_power_switching():
    """
    {"vid:pid loc": bool} for hubs uhubctl can see.

    uhubctl only lists hubs that support per-port power switching, so simply
    appearing in its output is the positive signal. It needs root for the
    control transfers; without it the tool prints a permission notice and
    reports nothing, which must not be read as "no hub supports it".
    """
    if not os.path.exists(UHUBCTL):
        return {}, "uhubctl is not installed"
    try:
        result = subprocess.run([UHUBCTL], capture_output=True, text=True,
                                timeout=15)
    except (OSError, subprocess.SubprocessError) as exc:
        return {}, f"uhubctl failed: {exc}"
    out = result.stdout + result.stderr
    if "permission problem" in out.lower():
        return {}, "uhubctl needs root; capability unknown"
    switching = {}
    for line in result.stdout.splitlines():
        match = re.match(r"Current status for hub (\S+)\s*\[([^\]]+)\]", line)
        if match:
            switching[match.group(1)] = True
    return switching, ""


class HubPorts:
    """
    One hub's ports.

    Construct with a sysfs hub name ("1-2") or let from_vid_pid() find it.
    Nothing is cached: port state changes underneath us when a device is
    plugged, and a stale "enabled" reading is exactly the kind of thing that
    made the old debug page report every port as off while one was powered.
    """

    def __init__(self, hub, port_names=None):
        self.hub = hub
        # "1-2" names its own interface; "usb1" does not -- look it up rather
        # than string-building, so both shapes work and a wrong name fails
        # loudly here instead of as a confusing missing-port error later.
        self.interface = ""
        for interface, (_, prefix) in _hub_interface_dirs().items():
            if prefix == hub:
                self.interface = interface
                break
        if not self.interface or not os.path.isdir(self.interface):
            raise HubError(f"no hub named {hub!r}; try the probe to list hubs")
        self.port_names = dict(port_names or {})
        self._switching = None

    @classmethod
    def from_vid_pid(cls, vid_pid, port_names=None):
        for hub in discover_hubs():
            if hub["vid_pid"].lower() == vid_pid.lower():
                return cls(hub["hub"], port_names)
        raise HubError(f"no hub with vid:pid {vid_pid}")

    # -- geometry ---------------------------------------------------------
    @property
    def ports(self):
        out = []
        for entry in os.listdir(self.interface):
            match = _PORT_DIR_RE.match(entry)
            if match and match.group("hub") == self.hub:
                out.append(int(match.group("port")))
        return sorted(out)

    def _port_dir(self, port):
        path = f"{self.interface}/{self.hub}-port{port}"
        if not os.path.isdir(path):
            raise HubError(f"hub {self.hub} has no port {port}")
        return path

    # -- capability -------------------------------------------------------
    def power_switching(self):
        """
        (supported, note). True means the hub *claims* per-port power
        switching, so disabling a port should remove VBUS. False with an empty
        note means uhubctl ran and did not list this hub -- ganged or absent
        switching. A non-empty note means the question could not be answered,
        which is NOT the same as no.
        """
        if self._switching is None:
            self._switching = _uhubctl_power_switching()
        switching, note = self._switching
        if note:
            return None, note
        return any(self.hub in key for key in switching), ""

    # -- state ------------------------------------------------------------
    def states(self):
        """Per-port state, newest reading each call. Needs no privileges."""
        out = {}
        for port in self.ports:
            port_dir = self._port_dir(port)
            device = port_device_path(self.hub, port)
            present = os.path.isdir(device)
            out[port] = {
                "port": port,
                "name": self.port_names.get(port, ""),
                # "disable" is the kernel's own view; 1 means we turned it off.
                "enabled": _read(f"{port_dir}/disable", "0") != "1",
                "device_present": present,
                "product": _read(f"{device}/product") if present else "",
                "vid_pid": (f"{_read(device + '/idVendor')}:"
                            f"{_read(device + '/idProduct')}") if present else "",
                "max_power": _read(f"{device}/bMaxPower") if present else "",
                "speed": _read(f"{device}/speed") if present else "",
            }
        return out

    def active_ports(self):
        """Ports currently enabled. The plural is the point: unlike the
        Coolgear, this hub can have several on at once."""
        return [p for p, s in self.states().items() if s["enabled"]]

    def get_current_active_port(self):
        """
        Compatibility shim for the Coolgear-shaped callers in server.py, which
        assume a single active port. Returns that port when exactly one is on,
        0 when none, and -1 when several -- which those callers read as
        "unknown" rather than silently picking one.
        """
        active = self.active_ports()
        if not active:
            return 0
        return active[0] if len(active) == 1 else -1

    # -- control (root) ---------------------------------------------------
    def set_port(self, port, on):
        """
        Enable or disable one port, leaving the others alone. This is what the
        debug page needs: independent per-port control, several on at once.
        """
        port_dir = self._port_dir(port)
        value = "0" if on else "1"
        try:
            with open(f"{port_dir}/disable", "w") as handle:
                handle.write(value)
        except PermissionError as exc:
            raise HubError(
                "writing port state needs root, and in a container also a "
                "writable /sys/devices (the webserver's is read-only)") from exc
        except OSError as exc:
            raise HubError(f"port {port}: {exc}") from exc
        return self.states()[port]

    def set_exclusive(self, port):
        """
        Power exactly one port: the policy the Internet page needs, and the
        one the RV wants by default -- several WAN sources may be *considered*,
        but only one should be drawing current.

        Others are switched off BEFORE the target goes on, so the hub is never
        briefly feeding two WAN devices at once. The Coolgear got this for free
        because its command was a bitmask; here it is explicit.
        """
        results = {}
        for other in self.ports:
            if other != port and self.states()[other]["enabled"]:
                results[other] = self.set_port(other, False)
        if port is not None:
            results[port] = self.set_port(port, True)
        return results

    def all_off(self):
        return {p: self.set_port(p, False) for p in self.ports}

    def all_on(self):
        """Every port on. Deliberately not used by the Internet page: it is a
        diagnostic, and on a WAN hub it means powering every uplink at once."""
        return {p: self.set_port(p, True) for p in self.ports}


def probe_report(as_json=False):
    """
    What is on this machine's USB tree and what can actually be controlled.

    Run this once the new hub is plugged in: it answers the questions that
    cannot be answered from the repo -- which hub is the Plugable, how many
    ports it exposes, what is on each, and whether it claims per-port power
    switching.
    """
    hubs = discover_hubs()
    switching, note = _uhubctl_power_switching()
    report = {"hubs": [], "uhubctl_note": note,
              "uhubctl_present": os.path.exists(UHUBCTL)}
    for hub in hubs:
        try:
            handle = HubPorts(hub["hub"])
            states = handle.states()
        except HubError as exc:
            states = {}
            hub["error"] = str(exc)
        hub["port_states"] = states
        hub["power_switching"] = (None if note
                                  else any(hub["hub"] in k for k in switching))
        report["hubs"].append(hub)
    if as_json:
        return json.dumps(report, indent=2)

    lines = []
    for hub in report["hubs"]:
        kind = "root hub" if hub["is_root_hub"] else "hub"
        switch = {True: "per-port power switching",
                  False: "NO per-port power switching (ganged or none)",
                  None: f"power switching unknown ({note})"}[hub["power_switching"]]
        lines.append(f"{hub['hub']:<8} {kind:<9} {hub['vid_pid']:<10} "
                     f"{hub['product'][:28]:<28} {switch}")
        for port, state in sorted(hub.get("port_states", {}).items()):
            mark = "on " if state["enabled"] else "OFF"
            dev = (f"{state['product'][:24]} [{state['vid_pid']}] "
                   f"{state['max_power']}" if state["device_present"]
                   else "(empty)")
            lines.append(f"    port {port}  {mark}  {dev}")
    lines.append("")
    lines.append("WARNING: 'OFF' guarantees the device is off the bus. It removes VBUS")
    lines.append("only if the hub really implements per-port power switching. Hubs do")
    lines.append("misreport this, so if the point is saving power, confirm with a")
    lines.append("current measurement at the port before trusting it.")
    return "\n".join(lines)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(
        description="Probe and control USB hub ports (changes need root).")
    parser.add_argument("--json", action="store_true", help="machine-readable probe")
    parser.add_argument("--hub", help="hub to act on, e.g. 1-2")
    parser.add_argument("--on", type=int, metavar="PORT", help="enable one port")
    parser.add_argument("--off", type=int, metavar="PORT", help="disable one port")
    parser.add_argument("--only", type=int, metavar="PORT",
                        help="enable this port and disable every other")
    parser.add_argument("--all-off", action="store_true")
    args = parser.parse_args()

    action = any([args.on, args.off, args.only, args.all_off])
    if not action:
        print(probe_report(as_json=args.json))
        raise SystemExit(0)
    if not args.hub:
        raise SystemExit("--hub is required to change a port")
    hub = HubPorts(args.hub)
    try:
        if args.all_off:
            hub.all_off()
        elif args.only is not None:
            hub.set_exclusive(args.only)
        elif args.on is not None:
            hub.set_port(args.on, True)
        elif args.off is not None:
            hub.set_port(args.off, False)
    except HubError as exc:
        raise SystemExit(f"error: {exc}")
    print(probe_report(as_json=args.json))
