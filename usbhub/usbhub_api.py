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

API
    GET  /api/health                    version, uptime
    GET  /api/hubs                      every hub, its ports and what is on them
    GET  /api/hub/<hub>/ports           one hub's port states
    POST /api/hub/<hub>/port            {"port": N, "on": bool}  -- one port,
                                        others untouched; several may be on
    POST /api/hub/<hub>/exclusive       {"port": N}  -- power exactly this one
    POST /api/hub/<hub>/all-off         every port off

The split is the point. /port is for the debug page, which needs to power
several ports at once to diagnose. /exclusive is for the Internet page and is
the RV's normal policy: WAN options may be *considered*, but only one is left
drawing current.
"""

import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from ipaddress import ip_address, ip_network
from urllib.parse import urlparse

import usbhub_ports
from usbhub_ports import HubError, HubPorts, probe_report

SCRIPT_VERSION = "0.1.0"

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

START = time.monotonic()


def protected(hub, port):
    return f"{hub}:{port}" in PROTECTED


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
            parts = path.split("/")
            if len(parts) == 5 and parts[1:3] == ["api", "hub"] and parts[4] == "ports":
                hub = self._hub(parts[3])
                switching, note = hub.power_switching()
                return self._send(200, {
                    "ok": True, "hub": hub.hub, "ports": hub.states(),
                    "active_ports": hub.active_ports(),
                    "power_switching": switching, "power_switching_note": note,
                    "protected": sorted(PROTECTED),
                })
        except HubError as exc:
            return self._send(404, {"ok": False, "error": "no_hub", "message": str(exc)})
        self._send(404, {"ok": False, "error": "not_found"})

    def do_POST(self):
        if not self._allowed():
            return self._send(403, {"ok": False, "error": "forbidden"})
        path = urlparse(self.path).path.rstrip("/")
        parts = path.split("/")
        if not (len(parts) == 5 and parts[1:3] == ["api", "hub"]):
            return self._send(404, {"ok": False, "error": "not_found"})
        body = self._body()
        if body is None:
            return self._send(400, {"ok": False, "error": "invalid_request",
                                    "message": "body must be JSON"})
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
                        "message": f"{hub.hub}:{port} is listed in USBHUB_PROTECTED"})
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
          f"protected={sorted(PROTECTED) or 'none'})")
    if os.geteuid() != 0:
        print("WARNING: not root -- reads will work, every write will fail.")
    ThreadingHTTPServer((BIND, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
