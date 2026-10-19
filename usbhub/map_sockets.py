#!/usr/bin/env python3
"""
Build the physical-socket map for a USB hub by watching you plug a device in.

Why this exists: nothing in sysfs relates a socket on the hub's shell to a port
number, and on a USB 3 hub the relationship is not even one-to-one. Measured on
the Plugable 7-in-1, 2026-10-18:

    one upstream cable  ->  3-1 and 3-1.3   (USB 2 chips, bus 3)
                        ->  4-1 and 4-1.3   (USB 3 chips, bus 4)

A "7-in-1" is two 4-port chips in series on each speed, port 3 of the upstream
chip being the internal cascade, which is why 4 + 4 presents as 7. So a socket
has up to two sysfs identities -- one per speed -- and a plugged device appears
under exactly one of them, whichever matches its own speed. A USB 2 stick in
socket 3 is invisible on the USB 3 tree.

The only way to learn the mapping is to observe it. Run this once with a USB 3
device and once with a USB 2 device, giving each socket the same label both
times; the two passes merge into one map, so each socket ends up with both
identities and SocketMap can switch both.

    ./map_sockets.py                 # all hubs, write to the default map
    ./map_sockets.py --hubs 4-1,4-1.3
    ./map_sockets.py --out /tmp/sockets.json

Reading sysfs needs no privileges. Writing the default map under /etc does, so
either run it with sudo or use --out and install the file afterwards.
"""

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from usbhub_ports import (            # noqa: E402
    DEFAULT_SOCKET_MAP, HubError, HubPorts, discover_hubs, port_device_path,
)

POLL_SECONDS = 0.3
SETTLE_SECONDS = 0.9      # enumeration populates product/speed after the dir


def watched_ports(names):
    """
    (hub, port) pairs to watch, minus the ones that are not sockets.

    Ports carrying a hub are excluded: on the Plugable they are the internal
    cascade, and watching them would record the hub's own chips as sockets the
    first time anything downstream enumerated.
    """
    if names:
        hubs = [h for h in discover_hubs() if h["hub"] in names]
        missing = set(names) - {h["hub"] for h in hubs}
        if missing:
            raise HubError(f"no such hub(s): {', '.join(sorted(missing))}")
    else:
        hubs = discover_hubs()

    pairs = []
    for hub in hubs:
        try:
            handle = HubPorts(hub["hub"])
            cascades = set(handle.cascade_ports())
        except HubError:
            continue
        pairs += [(hub["hub"], p) for p in handle.ports if p not in cascades]
    return pairs


def occupied(pairs):
    return {pair for pair in pairs
            if os.path.isdir(port_device_path(pair[0], pair[1]))}


def describe(hub, port):
    path = port_device_path(hub, port)
    def read(attr):
        try:
            with open(f"{path}/{attr}") as handle:
                return handle.read().strip()
        except OSError:
            return "?"
    return (f"{read('product')} [{read('idVendor')}:{read('idProduct')}] "
            f"{read('bMaxPower')} {read('speed')}Mbps")


def wait_for_plug(pairs, baseline):
    """Block until a device appears on a watched port. Returns (hub, port)."""
    while True:
        now = occupied(pairs)
        new = now - baseline
        if new:
            time.sleep(SETTLE_SECONDS)
            return sorted(new)[0]
        baseline &= now          # track unplugs, so a move is seen as a plug
        time.sleep(POLL_SECONDS)


def tree_of(hub):
    """
    Which speed tree a hub name belongs to: "3-1.3" -> "3", "usb4" -> "4".

    The USB 2 and USB 3 halves of one socket are on different buses, so this is
    what tells a second pass apart from the first.
    """
    return hub.split("-")[0].replace("usb", "")


def sorted_labels(sockets):
    return sorted(sockets, key=lambda k: (not k.isdigit(), k.zfill(4)))


def next_label(sockets, hub):
    """
    The label to offer for a port not already in the map.

    On a second pass -- same sockets, a device of the other speed -- the right
    answer is the first socket with no identity on this tree yet, because the
    pass walks the same physical order. Without this the default would be a new
    number every time and every label would have to be typed by hand. Falls
    back to a new number when nothing is left to fill, i.e. the first pass.
    """
    tree = tree_of(hub)
    for label in sorted_labels(sockets):
        if not any(tree_of(h) == tree for h, _ in sockets[label]):
            return label
    return str(len(sockets) + 1)


def load_existing(path):
    try:
        with open(path) as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {}


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--hubs", help="comma-separated hubs to watch, "
                                       "e.g. 3-1,3-1.3,4-1,4-1.3")
    parser.add_argument("--out", default=DEFAULT_SOCKET_MAP,
                        help=f"where to write the map (default {DEFAULT_SOCKET_MAP})")
    parser.add_argument("--fresh", action="store_true",
                        help="start a new map instead of merging into --out")
    args = parser.parse_args()

    names = [n.strip() for n in args.hubs.split(",")] if args.hubs else []
    try:
        pairs = watched_ports(names)
    except HubError as exc:
        raise SystemExit(f"error: {exc}")
    if not pairs:
        raise SystemExit("no watchable ports found")

    existing = {} if args.fresh else load_existing(args.out)
    sockets = {k: [tuple(pair) for pair in v]
               for k, v in (existing.get("sockets") or {}).items()}
    wan = dict(existing.get("wan") or {})

    print(f"Watching {len(pairs)} ports: "
          f"{', '.join(f'{h}:{p}' for h, p in sorted(pairs))}")
    if sockets:
        print(f"Merging into {args.out} ({len(sockets)} socket(s) already mapped).")
    print("\nPlug one device into a socket, label it, then move it to the next.")
    print("Go in a consistent physical order -- left to right -- so a second")
    print("pass with a device of the other speed lines up with this one.")
    print("Ctrl-C when done.\n")

    baseline = occupied(pairs)
    try:
        while True:
            hub, port = wait_for_plug(pairs, set(baseline))
            baseline = occupied(pairs)

            known = [label for label, ids in sockets.items()
                     if (hub, port) in ids]
            tag = f"  (already socket {known[0]})" if known else ""
            print(f"detected  {hub}:{port}  {describe(hub, port)}{tag}")

            default = known[0] if known else next_label(sockets, hub)
            label = input(f"  socket label [{default}]: ").strip() or default
            ids = sockets.setdefault(label, [])
            if (hub, port) not in ids:
                ids.append((hub, port))

            if label not in wan:
                role = input("  WAN role (starlink/wired/cell/wifi, blank=none): ").strip()
                if role:
                    wan[label] = role
            print("  recorded. Move the device to the next socket.\n")
    except KeyboardInterrupt:
        print()

    if not sockets:
        raise SystemExit("nothing recorded; map not written")

    data = {
        "note": existing.get("note") or
                "Built by map_sockets.py. Each socket lists every (hub, port) "
                "identity it has -- USB 2 and USB 3 chips are separate hubs.",
        "sockets": {k: [list(pair) for pair in v] for k, v in sockets.items()},
        "wan": wan,
    }

    directory = os.path.dirname(os.path.abspath(args.out))
    try:
        os.makedirs(directory, exist_ok=True)
        with open(args.out, "w") as handle:
            json.dump(data, handle, indent=2)
            handle.write("\n")
    except OSError as exc:
        print(json.dumps(data, indent=2))
        raise SystemExit(f"\ncould not write {args.out}: {exc}\n"
                         "The map is printed above -- save it by hand, or "
                         "re-run with sudo or --out.")

    print(f"Wrote {args.out}:")
    for label in sorted_labels(sockets):
        ident = ", ".join(f"{h}:{p}" for h, p in sockets[label])
        role = f"  wan={wan[label]}" if label in wan else ""
        print(f"  socket {label:<4} {ident}{role}")
    halves = [l for l, v in sockets.items() if len(v) < 2]
    if halves:
        print(f"\nOnly one identity for socket(s) {', '.join(sorted(halves))}. "
              "Run a second\npass with a device of the other speed (USB 2 vs "
              "USB 3) to fill them in.")


if __name__ == "__main__":
    main()
