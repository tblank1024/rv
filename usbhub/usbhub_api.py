#!/usr/bin/env python3
"""
Root HTTP/JSON service for USB hub port power. Loopback only.

Why a service rather than doing this in the webserver container: the container
is privileged, but Docker mounts its /sys/devices read-only, so writing
<hub>:1.0/<hub>-portN/disable fails there with EACCES even as uid 0 (verified
2026-10-18). The Coolgear hub escaped this only because its control path is a
character device, /dev/coolgear-hub, which is bind-mounted from the host. A
plain powered hub like the Plugable has no control chip, so the kernel is the
only way in and that means host-side root.

Same shape as wifi-api-rp5.service deliberately: stdlib only, bound to
127.0.0.1, no authentication because the bind address is the access control.
Never bind 0.0.0.0 or br0 -- br0 carries RV guest devices, and this service can
power down the RV's internet.

API -- raw ports (one hub, sysfs port numbers)
    GET  /api/health                    version, uptime
    GET  /api/hubs                      every hub, its ports and what is on them
    GET  /api/hub/<hub>/ports           one hub's port states
    POST /api/hub/<hub>/port            {"port": N, "on": bool}  -- one port,
                                        others untouched; several may be on
    POST /api/hub/<hub>/exclusive       {"port": N}  -- power exactly this one
    POST /api/hub/<hub>/all-off         every port off

API -- physical sockets (what is printed on the hub's shell)
    GET  /api/sockets                   the socket map and each socket's state
    POST /api/socket                    {"socket": "3", "on": bool}
    POST /api/socket/exclusive          {"socket": "3"} or {"socket": null}
    POST /api/sockets/all-off           WAN sockets off; {"all":true} for every
                                        socket, Bluetooth adapter included

Prefer the socket endpoints. A USB 3 hub is two hubs in one shell, so one
physical socket has a USB 2 identity and a USB 3 identity on different buses
(the Plugable: 3-1/3-1.3 and 4-1/4-1.3), and a device shows up under only the
one matching its speed. The raw endpoints act on half a socket; the socket
endpoints act on all of its identities. See SocketMap in usbhub_ports.

The port/exclusive split is the point. /port and /socket are for the debug
page, which needs to power several at once to diagnose. /exclusive is for the
Internet page and is the RV's normal policy: WAN options may be *considered*,
but only one is left drawing current.

Protected ports: USBHUB_PROTECTED names them explicitly, and any port carrying
another hub is protected automatically -- a hub's upstream port, or the internal
cascade that fronts four of the Plugable's sockets. Cutting one of those takes
out everything behind it, including, on usb1:2, the live WAN.
"""

import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from ipaddress import ip_address, ip_network
from urllib.parse import urlparse

import usbhub_ports
from usbhub_ports import (
    DEFAULT_SOCKET_MAP, HubError, HubPorts, SocketMap, discover_cascade_ports,
    probe_report,
)

SCRIPT_VERSION = "0.3.0"

BIND = os.environ.get("USBHUB_API_BIND", "127.0.0.1")
PORT = int(os.environ.get("USBHUB_API_PORT", "12347"))
ALLOWED_NET = os.environ.get("USBHUB_API_ALLOWED_NET", "127.0.0.0/8")

# Ports that must never be switched off, as "hub:port", comma separated. Set
# this for anything whose loss would cost control rather than just internet --
# the FT232R that drives the Coolgear is the obvious candidate, since without
# it the old hub cannot be steered at all.
PROTECTED = {
    entry.strip() for entry in os.environ.get("USBHUB_PROTECTED", "").split(",")
    if entry.strip()
}

SOCKET_MAP = os.environ.get("USBHUB_SOCKET_MAP", DEFAULT_SOCKET_MAP)

START = time.monotonic()

# Walking the tree for cascades costs a few dozen sysfs reads, and protected()
# is called once per port inside loops. Cache it briefly -- long enough to make
# a request cheap, short enough that plugging a hub in is noticed.
_CASCADE_TTL = 5.0
_cascade = {"at": 0.0, "set": frozenset()}


def cascade_protected():
    """{"hub:port"} for every port carrying another hub."""
    now = time.monotonic()
    if now - _cascade["at"] > _CASCADE_TTL:
        try:
            found = frozenset(f"{h}:{p}" for h, p in discover_cascade_ports())
        except OSError:
            found = _cascade["set"]
        _cascade.update(at=now, set=found)
    return _cascade["set"]


def protected_set():
    return PROTECTED | cascade_protected()


def protected(hub, port):
    return f"{hub}:{port}" in protected_set()


class Handler(BaseHTTPRequestHandler):
    server_version = f"usbhub-api/{SCRIPT_VERSION}"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        print(f"{self.client_address[0]} {fmt % args}")

    def _send(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _allowed(self):
        try:
            return ip_address(self.client_address[0]) in ip_network(ALLOWED_NET)
        except ValueError:
            return False

    def _body(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError):
            return None

    def _hub(self, name):
        return HubPorts(name)

    def do_GET(self):
        if not self._allowed():
            return self._send(403, {"ok": False, "error": "forbidden"})
        path = urlparse(self.path).path.rstrip("/")
        try:
            if path == "/api/health":
                return self._send(200, {"ok": True, "version": SCRIPT_VERSION,
                                        "uptime": round(time.monotonic() - START, 1)})
            if path == "/api/hubs":
                return self._send(200, {"ok": True,
                                        **json.loads(probe_report(as_json=True))})
            if path == "/api/sockets":
                smap = SocketMap(SOCKET_MAP)
                return self._send(200, {
                    "ok": True, "map_path": smap.path, "note": smap.note,
                    "configured": bool(smap),
                    "sockets": smap.states() if smap else {},
                    "wan": smap.wan,
                    "protected": sorted(protected_set()),
                })
            parts = path.split("/")
            if len(parts) == 5 and parts[1:3] == ["api", "hub"] and parts[4] == "ports":
                hub = self._hub(parts[3])
                switching, note = hub.power_switching()
                return self._send(200, {
                    "ok": True, "hub": hub.hub, "ports": hub.states(),
                    "active_ports": hub.active_ports(),
                    "power_switching": switching, "power_switching_note": note,
                    "protected": sorted(protected_set()),
                })
        except HubError as exc:
            return self._send(404, {"ok": False, "error": "no_hub", "message": str(exc)})
        self._send(404, {"ok": False, "error": "not_found"})

    def _socket_blocked(self, smap, labels):
        """Protected (hub, port) identities among these sockets.

        A socket is refused if *any* of its identities is protected, since
        switching only the unprotected half would half-cut it and report
        success. Reported as "socket -> hub:port" so the message says which
        underlying port caused it.
        """
        blocked = []
        guard = protected_set()
        for label in labels:
            for hub_name, port in smap.sockets.get(label, []):
                if f"{hub_name}:{port}" in guard:
                    blocked.append(f"{label} -> {hub_name}:{port}")
        return blocked

    def _do_socket(self, path, body):
        """Physical-socket endpoints: act on every identity of a socket."""
        try:
            smap = SocketMap(SOCKET_MAP)
            if not smap:
                return self._send(409, {
                    "ok": False, "error": "no_socket_map",
                    "map_path": smap.path,
                    "message": ("no socket map; run map_sockets.py. Physical "
                                "socket numbers cannot be derived from sysfs.")})

            if path == "/api/socket":
                label, on = body.get("socket"), body.get("on")
                if not isinstance(label, str) or not isinstance(on, bool):
                    return self._send(400, {"ok": False, "error": "invalid_request",
                                            "message": 'need {socket: str, on: bool}'})
                if label not in smap.sockets:
                    return self._send(404, {"ok": False, "error": "no_socket",
                                            "message": f"no socket {label!r}"})
                blocked = [] if on else self._socket_blocked(smap, [label])
                if blocked:
                    return self._send(409, {"ok": False, "error": "protected",
                                            "message": f"protected: {blocked}"})
                state = smap.set_socket(label, on)
                print(f"socket {label} -> {'on' if on else 'off'}")
                return self._send(200, {"ok": True, "socket": state,
                                        "sockets": smap.states()})

            if path == "/api/socket/exclusive":
                label = body.get("socket")
                if label is not None and not isinstance(label, str):
                    return self._send(400, {"ok": False, "error": "invalid_request",
                                            "message": 'need {socket: str|null}'})
                if label is not None and label not in smap.sockets:
                    return self._send(404, {"ok": False, "error": "no_socket",
                                            "message": f"no socket {label!r}"})
                current = smap.states()
                # Only the WAN group is switched, so only it can be blocked.
                others = [l for l in smap.exclusive_group(label)
                          if l != label and current[l]["enabled"]]
                blocked = self._socket_blocked(smap, others)
                if blocked:
                    return self._send(409, {
                        "ok": False, "error": "protected",
                        "message": f"exclusive would cut protected: {blocked}"})
                changed = smap.set_exclusive(label)
                print(f"socket exclusive -> {label}")
                return self._send(200, {"ok": True, "changed": changed,
                                        "sockets": smap.states()})

            if path == "/api/sockets/all-off":
                # Defaults to the WAN sockets. {"all": true} really means every
                # socket, which on this hub includes a Bluetooth adapter.
                wan_only = not bool(body.get("all"))
                targets = smap.wan_labels if wan_only else smap.labels
                blocked = self._socket_blocked(smap, targets)
                if blocked:
                    return self._send(409, {"ok": False, "error": "protected",
                                            "message": f"protected: {blocked}"})
                changed = smap.all_off(wan_only=wan_only)
                print("socket all-off")
                return self._send(200, {"ok": True, "changed": changed,
                                        "sockets": smap.states()})
        except HubError as exc:
            return self._send(502, {"ok": False, "error": "hub_failed",
                                    "message": str(exc)})
        return self._send(404, {"ok": False, "error": "not_found"})

    def do_POST(self):
        if not self._allowed():
            return self._send(403, {"ok": False, "error": "forbidden"})
        path = urlparse(self.path).path.rstrip("/")
        parts = path.split("/")
        socket_route = path in ("/api/socket", "/api/socket/exclusive",
                                "/api/sockets/all-off")
        if not socket_route and not (len(parts) == 5 and parts[1:3] == ["api", "hub"]):
            return self._send(404, {"ok": False, "error": "not_found"})
        body = self._body()
        if body is None:
            return self._send(400, {"ok": False, "error": "invalid_request",
                                    "message": "body must be JSON"})
        if socket_route:
            return self._do_socket(path, body)
        action = parts[4]
        try:
            hub = self._hub(parts[3])
            if action == "port":
                port, on = body.get("port"), body.get("on")
                if not isinstance(port, int) or not isinstance(on, bool):
                    return self._send(400, {"ok": False, "error": "invalid_request",
                                            "message": "need {port: int, on: bool}"})
                if not on and protected(hub.hub, port):
                    return self._send(409, {
                        "ok": False, "error": "protected",
                        "message": (f"{hub.hub}:{port} is protected "
                                    "(USBHUB_PROTECTED, or it carries a hub)")})
                state = hub.set_port(port, on)
                print(f"port {hub.hub}:{port} -> {'on' if on else 'off'}")
                return self._send(200, {"ok": True, "port": state,
                                        "active_ports": hub.active_ports()})
            if action == "exclusive":
                port = body.get("port")
                if not isinstance(port, int):
                    return self._send(400, {"ok": False, "error": "invalid_request",
                                            "message": "need {port: int}"})
                blocked = [p for p in hub.ports
                           if p != port and protected(hub.hub, p)
                           and hub.states()[p]["enabled"]]
                if blocked:
                    return self._send(409, {
                        "ok": False, "error": "protected",
                        "message": ("exclusive would switch off protected "
                                    f"port(s) {blocked}")})
                changed = hub.set_exclusive(port)
                print(f"exclusive {hub.hub}:{port}")
                return self._send(200, {"ok": True, "changed": changed,
                                        "active_ports": hub.active_ports()})
            if action == "all-off":
                blocked = [p for p in hub.ports if protected(hub.hub, p)]
                if blocked:
                    return self._send(409, {
                        "ok": False, "error": "protected",
                        "message": f"protected port(s) {blocked} would be cut"})
                changed = hub.all_off()
                print(f"all-off {hub.hub}")
                return self._send(200, {"ok": True, "changed": changed,
                                        "active_ports": hub.active_ports()})
        except HubError as exc:
            return self._send(502, {"ok": False, "error": "hub_failed",
                                    "message": str(exc)})
        self._send(404, {"ok": False, "error": "not_found"})


def main():
    if BIND not in ("127.0.0.1", "::1", "localhost"):
        print(f"WARNING: bound to {BIND}, not loopback. This service can power "
              "down the RV's internet; it must not be reachable from br0.")
    print(f"{os.path.basename(__file__)} Version: {SCRIPT_VERSION}")
    print(f"Listening on {BIND}:{PORT} (allow={ALLOWED_NET}, "
          f"protected={sorted(PROTECTED) or 'none'} "
          f"+auto {sorted(cascade_protected()) or 'none'}, "
          f"socket map={SOCKET_MAP})")
    if os.geteuid() != 0:
        print("WARNING: not root -- reads will work, every write will fail.")
    ThreadingHTTPServer((BIND, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
