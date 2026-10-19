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
import time

__all__ = [
    "HubPorts", "SocketMap", "discover_hubs", "discover_cascade_ports",
    "probe_report", "socket_report", "UHUBCTL", "HubError",
    "DEFAULT_SOCKET_MAP",
]

UHUBCTL = "/usr/sbin/uhubctl"

# Which physical socket is which (hub, port) pair. Cannot be derived -- see
# SocketMap. map_sockets.py writes this file; a reference copy with the
# Plugable's geometry but no labels lives beside this script.
DEFAULT_SOCKET_MAP = "/etc/usbhub/sockets.json"

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


# Reading a port's "disable" attribute is a USB control transfer to the hub, and
# on a runtime-suspended hub it wakes it first: measured 75-220 ms per read on
# the Plugable's downstream USB 2 chip (3-1.3), against 2 ms on its USB 3
# counterpart. Fourteen identities then cost ~850 ms, which is too slow for a
# dashboard poll.
#
# But that read reports only *our own* switch state, and every write goes
# through set_port(), which invalidates the entry. So cache it, with a short TTL
# as the backstop for a change made behind our back -- uhubctl, or a hand-edited
# sysfs write. Device presence is NOT cached: those attributes are populated at
# enumeration and read in microseconds, and a stale "is something plugged in"
# is exactly the kind of lie that made the old debug page untrustworthy.
#
# Keeping the hub awake would also fix the latency, at the cost of standby
# current. On a battery that is the wrong trade.
_ENABLED_TTL = 5.0
_ENABLED_STALE_MAX = 300.0
_enabled_cache = {}


def _hub_suspended(hub):
    """
    Whether the hub is runtime-suspended. A plain attribute read, no control
    transfer, so this is cheap even when reading a port is not.
    """
    device = (f"/sys/bus/usb/devices/{hub}" if hub.startswith("usb")
              else f"/sys/bus/usb/devices/{hub}")
    return _read(f"{device}/power/runtime_status") == "suspended"


def _port_enabled(hub, port, port_dir):
    key = (hub, port)
    now = time.monotonic()
    cached = _enabled_cache.get(key)
    if cached is not None:
        age = now - cached[0]
        if age < _ENABLED_TTL:
            return cached[1]
        # A suspended hub cannot have changed its own port power: a plug into a
        # powered port resumes it (and device presence, which is read live,
        # changes with it), and a plug into an unpowered one is not detected at
        # all. So while it stays suspended the cached answer is still true, and
        # waking it to re-ask would cost 200 ms and the current to do it. The
        # long backstop covers the one case this misses -- a writer outside this
        # module, such as uhubctl by hand.
        if age < _ENABLED_STALE_MAX and _hub_suspended(hub):
            return cached[1]
    # "disable" is the kernel's own view; 1 means we turned it off.
    value = _read(f"{port_dir}/disable", "0") != "1"
    _enabled_cache[key] = (now, value)
    return value


def _forget_enabled(hub, port):
    _enabled_cache.pop((hub, port), None)


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
    def port_state(self, port):
        """
        One port's state, newest reading each call.

        Reading a port's "disable" attribute is a control transfer to the hub,
        and on a suspended hub it also wakes it: measured 75-220 ms per read on
        the Plugable's downstream USB 2 chip, against 2 ms on its USB 3 one. So
        reading a single port matters -- a caller that wants one socket must
        not pay for a whole hub, and nothing should read the same port twice in
        one request.
        """
        port_dir = self._port_dir(port)
        device = port_device_path(self.hub, port)
        present = os.path.isdir(device)
        return {
            "port": port,
            "name": self.port_names.get(port, ""),
            "enabled": _port_enabled(self.hub, port, port_dir),
            "device_present": present,
            "product": _read(f"{device}/product") if present else "",
            "vid_pid": (f"{_read(device + '/idVendor')}:"
                        f"{_read(device + '/idProduct')}") if present else "",
            "max_power": _read(f"{device}/bMaxPower") if present else "",
            "speed": _read(f"{device}/speed") if present else "",
            # Class 09 is a hub. A port with a hub on it may be an internal
            # cascade rather than a socket -- cutting it takes every port
            # behind it with it, so callers protect these.
            "is_hub": present and _read(f"{device}/bDeviceClass") == "09",
        }

    def states(self):
        """Every port's state. Needs no privileges."""
        return {port: self.port_state(port) for port in self.ports}

    def active_ports(self):
        """Ports currently enabled. The plural is the point: unlike the
        Coolgear, this hub can have several on at once."""
        return [p for p, s in self.states().items() if s["enabled"]]

    def cascade_ports(self):
        """
        Ports with another hub attached.

        On the Plugable these are not sockets at all: a "7-in-1" is two 4-port
        chips in series, so port 3 of the upstream chip is the link to the
        downstream one. Disabling it removes four sockets, and nothing in the
        port's own attributes says so. Returned so callers can refuse.
        """
        return [p for p, s in self.states().items() if s["is_hub"]]

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
        # Drop the cached reading rather than assuming the write took: the
        # returned state is then the kernel's answer, not ours.
        _forget_enabled(self.hub, port)
        return self.port_state(port)

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
        enabled = {p: s["enabled"] for p, s in self.states().items()}
        for other in self.ports:
            if other != port and enabled[other]:
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


def discover_cascade_ports():
    """
    Every (hub, port) that carries another hub, across the whole tree.

    These are the ports a caller must not cut blind. Two kinds show up here and
    both matter: a hub's internal cascade (the Plugable's port 3 on each chip,
    which fronts four sockets) and a hub plugged into a socket by hand. The
    distinction is invisible from sysfs, so both are simply reported.
    """
    found = []
    for hub in discover_hubs():
        try:
            found += [(hub["hub"], port) for port in HubPorts(hub["hub"]).cascade_ports()]
        except HubError:
            continue
    return found


class SocketMap:
    """
    Physical sockets, each of which is one or more (hub, port) pairs.

    A USB 3 hub is two hubs in one shell. The SuperSpeed lanes of a socket go
    to a USB 3 hub chip and that socket's D+/D- pair goes to a separate USB 2
    hub chip, on a different bus -- measured on the Plugable 2026-10-18, one
    upstream cable presenting as 3-1/3-1.3 (USB 2) and 4-1/4-1.3 (USB 3). So
    one socket has two sysfs identities and a plugged device appears under
    exactly one of them, chosen by its own speed. A USB 2 stick in socket 3 is
    invisible on the USB 3 tree, and vice versa.

    Two consequences:

      - A socket's state is the union of its identities: "occupied" if a device
        is on any of them.
      - Controlling a socket means acting on *every* identity it has. Which one
        actually gates VBUS is a board-layout question sysfs cannot answer, so
        setting both is the only way to be sure, and is harmless if one of them
        is not wired to the switch.

    The map itself cannot be derived -- nothing relates socket silkscreen to
    port number -- so it is discovered once with map_sockets.py and stored as
    JSON. An absent or empty map is a normal state, not an error: callers
    render "not configured" rather than guessing, because guessing here means
    cutting power to the wrong uplink.
    """

    def __init__(self, path=None, data=None):
        self.path = path or DEFAULT_SOCKET_MAP
        if data is None:
            data = self._load(self.path)
        self.sockets = {}
        for label, pairs in (data.get("sockets") or {}).items():
            self.sockets[str(label)] = [(str(h), int(n)) for h, n in pairs]
        self.wan = {str(k): str(v) for k, v in (data.get("wan") or {}).items()}
        # Roles whose socket is powered ONLY while it is the active uplink.
        # Everything else stays powered, which buys free detection: carrier or
        # association appears by itself and pi5connect promotes it with no
        # scan and no button. Measured 2026-10-19 with a USB meter: the Alfa
        # is 0.4 W (0.8 Ah/day at 12 V) while the cellular modem is ~1 W and
        # highly variable. Gating the 0.4 W parts saves less than the Pi's own
        # rails cost and throws away automatic promotion; gating the modem is
        # worth it and costs nothing, since nothing outranks it from below so
        # it never needs speculative testing.
        self.gated = {str(k) for k, v in (data.get("gated") or {}).items() if v}
        # Display label, deliberately NOT the same thing as a WAN role.
        # A socket can be named "Wifi" for the diagnostic page without
        # joining the exclusive group, which is what keeps selecting
        # another uplink from cutting power to the WiFi adapter.
        self.names = {str(k): str(v) for k, v in (data.get("names") or {}).items()}
        self.note = data.get("note", "")
        self._hubs = {}

    @staticmethod
    def _load(path):
        try:
            with open(path) as handle:
                return json.load(handle)
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as exc:
            raise HubError(f"socket map {path}: {exc}") from exc

    def __bool__(self):
        return bool(self.sockets)

    @property
    def labels(self):
        """Sorted numerically where the labels are numeric, else as text."""
        return sorted(self.sockets, key=lambda k: (not k.isdigit(), k.zfill(4)))

    @property
    def wan_labels(self):
        """
        Sockets that are WAN candidates, i.e. have a role in the map.

        This is what exclusivity applies to, and the distinction is not
        cosmetic: the hub also carries things that are not uplinks at all. With
        a Bluetooth adapter in socket 7, an exclusive switch over *every* socket
        would cut Bluetooth every time the WAN changed, taking the TPMS and
        battery monitors down with it.
        """
        return [label for label in self.labels if self.wan.get(label)]

    def _hub(self, name):
        if name not in self._hubs:
            self._hubs[name] = HubPorts(name)
        return self._hubs[name]

    def _identity(self, hub_name, port):
        try:
            return dict(self._hub(hub_name).port_state(port), hub=hub_name)
        except (HubError, KeyError) as exc:
            return {"hub": hub_name, "port": port, "error": str(exc),
                    "enabled": False, "device_present": False}

    @staticmethod
    def _merge(label, wan, name, gated, identities):
        """
        One socket's state from its identities.

        "enabled" is AND across them: a socket with either half disabled cannot
        carry a device of that speed, so reporting it as on would be a lie for
        half the devices that could go in it. The device fields come from
        whichever identity actually has something on it -- at most one can,
        since a device negotiates one speed.
        """
        present = [i for i in identities if i.get("device_present")]
        device = present[0] if present else {}
        return {
            "socket": label,
            "wan": wan,
            "name": name,
            "gated": gated,
            "enabled": all(i.get("enabled") for i in identities) if identities else False,
            "device_present": bool(present),
            "product": device.get("product", ""),
            "vid_pid": device.get("vid_pid", ""),
            "max_power": device.get("max_power", ""),
            "speed": device.get("speed", ""),
            "identities": identities,
        }

    def socket_state(self, label):
        """One socket, reading only its own identities."""
        identities = [self._identity(h, n) for h, n in self.sockets.get(label, [])]
        return self._merge(label, self.wan.get(label, ""),
                           self.names.get(label, ""),
                           label in self.gated, identities)

    def states(self):
        """
        Every socket's state, each identity read exactly once.

        Reading once per identity rather than once per hub per identity is the
        difference between a usable endpoint and a 2.3 s one: the Plugable's
        downstream USB 2 chip autosuspends, and every "disable" read wakes it
        for 75-220 ms. Keeping it awake would fix the latency and cost standby
        current, which is the wrong trade on a battery.
        """
        return {label: self.socket_state(label) for label in self.labels}

    # -- control (root) ---------------------------------------------------
    def set_socket(self, label, on):
        """Act on every identity of one socket. Partial failure is reported,
        not swallowed: half a socket switched is worth knowing about."""
        if label not in self.sockets:
            raise HubError(f"no socket {label!r} in {self.path}")
        errors = []
        for hub_name, port in self.sockets[label]:
            try:
                self._hub(hub_name).set_port(port, on)
            except HubError as exc:
                errors.append(f"{hub_name}:{port}: {exc}")
        if errors:
            raise HubError("; ".join(errors))
        return self.socket_state(label)

    def exclusive_group(self, label=None):
        """
        The sockets an exclusive switch is allowed to touch: the WAN candidates,
        plus the target itself even if it has no role yet.

        Anything without a role is left alone -- see wan_labels.
        """
        group = list(self.wan_labels)
        if label is not None and label not in group:
            group.append(label)
        return group

    def set_exclusive(self, label):
        """
        Power exactly one WAN socket, across both trees and both chips.

        Others go off BEFORE the target comes on, so the hub is never briefly
        feeding two uplinks -- the whole point of routing WAN selection through
        here rather than letting the UI toggle sockets one at a time. Pass None
        to leave every WAN socket off.

        Only WAN sockets are switched. A socket with no role is not an uplink
        and is not touched, so selecting a WAN source cannot cut the Bluetooth
        adapter sharing the hub.
        """
        if label is not None and label not in self.sockets:
            raise HubError(f"no socket {label!r} in {self.path}")
        group = self.exclusive_group(label)
        results = {}
        enabled = {l: s["enabled"] for l, s in self.states().items()}
        for other in group:
            if other != label and enabled.get(other):
                results[other] = self.set_socket(other, False)
        if label is not None:
            results[label] = self.set_socket(label, True)
        return results

    def all_off(self, wan_only=False):
        """
        Every socket off -- literally every one, unless wan_only.

        Unlike set_exclusive this does not respect the WAN group, because
        "all off" has to mean what it says. On a hub that also carries a
        Bluetooth adapter that is rarely what a caller wants, so the API
        defaults to wan_only and nothing in the UI calls the literal form.
        """
        targets = self.wan_labels if wan_only else self.labels
        return {label: self.set_socket(label, False) for label in targets}

    def all_on(self):
        return {label: self.set_socket(label, True) for label in self.labels}


def socket_report(path=None):
    """Human-readable socket view, or why there isn't one."""
    smap = SocketMap(path)
    if not smap:
        return (f"No socket map at {smap.path}.\n"
                "Run map_sockets.py to build one -- physical socket numbers\n"
                "cannot be derived from sysfs, they have to be observed.")
    lines = [f"socket map: {smap.path}"]
    if smap.note:
        lines.append(f"  note: {smap.note}")
    for label, state in smap.states().items():
        mark = "on " if state["enabled"] else "OFF"
        dev = (f"{state['product'][:24]} [{state['vid_pid']}] {state['max_power']}"
               if state["device_present"] else "(empty)")
        ident = ",".join(f"{i['hub']}:{i['port']}" for i in state["identities"])
        wan = f"  wan={state['wan']}" if state["wan"] else ""
        lines.append(f"  socket {label:<4} {mark}  {dev:<42} [{ident}]{wan}")
    return "\n".join(lines)


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
    parser.add_argument("--only", type=int, nargs="?", const=-1, metavar="PORT",
                        help="enable this port and disable every other; with "
                             "--socket takes no value")
    parser.add_argument("--all-off", action="store_true")
    parser.add_argument("--sockets", action="store_true",
                        help="show the physical socket map instead of raw ports")
    parser.add_argument("--socket", metavar="LABEL",
                        help="act on a physical socket (with --on/--off/--only)")
    parser.add_argument("--socket-map", metavar="PATH", default=None,
                        help=f"socket map file (default {DEFAULT_SOCKET_MAP})")
    args = parser.parse_args()

    if args.sockets and not args.socket:
        print(socket_report(args.socket_map))
        raise SystemExit(0)

    # Socket mode acts on every identity of the socket -- see SocketMap. The
    # flags are shared with port mode, so --only means "this one and no other"
    # in both, just over a different set.
    if args.socket:
        smap = SocketMap(args.socket_map)
        try:
            if args.all_off:
                smap.all_off()
            elif args.only is not None:
                smap.set_exclusive(args.socket)
            elif args.on is not None:
                smap.set_socket(args.socket, True)
            elif args.off is not None:
                smap.set_socket(args.socket, False)
            else:
                raise SystemExit("--socket needs one of --on/--off/--only/--all-off")
        except HubError as exc:
            raise SystemExit(f"error: {exc}")
        print(socket_report(args.socket_map))
        raise SystemExit(0)

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
