#!/usr/bin/env python3
"""
sophie-hostd -- the host-root broker for the webserver dashboard.

Why this exists: the webserver container runs `privileged: true` + `pid: host`
with the Docker socket mounted, purely so it can perform a fixed handful of
host-root operations (read the firewall chains, restart containers, reboot, and
read/write three host files). That makes any dashboard bug root on Sophie. This
daemon moves exactly those operations behind a loopback HTTP API with a fixed
allow-list, so the webserver can drop privileged/pid:host/docker.sock and become
an ordinary container. See rv/TODO.md "Plan: sophie-hostd".

Same shape as its siblings `usbhub_api.py` and `wifi-api-rp5`: stdlib only, root,
bound to loopback with the bind address as the only access control, a systemd
WatchdogSec self-check, and NO arbitrary command execution -- every endpoint maps
to a specific operation with constrained arguments. It shells to the host's own
`systemctl` / `iptables` / `docker` / `journalctl` because it runs ON the host,
so unlike the webserver it needs no `nsenter`.

Design note: where the webserver interprets output (the firewall health parsing
especially), this daemon returns the RAW command output and leaves the parsing in
the webserver. That keeps the privileged surface here tiny and auditable -- this
file decides only *which* fixed commands may run, not what their output means.
"""

import json
import os
import socket
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from ipaddress import ip_address, ip_network
from urllib.parse import urlparse, parse_qs

BIND = os.environ.get("SOPHIE_HOSTD_BIND", "127.0.0.1")
PORT = int(os.environ.get("SOPHIE_HOSTD_PORT", "12348"))
ALLOWED_NET = os.environ.get("SOPHIE_HOSTD_ALLOWED_NET", "127.0.0.0/8")
COMPOSE_PROJECT = os.environ.get("SOPHIE_HOSTD_COMPOSE_PROJECT", "docker")

IPTABLES = {"v4": "/usr/sbin/iptables", "v6": "/usr/sbin/ip6tables"}

# --- allow-lists: the entire privileged surface, fixed at load time ----------
#
# Nothing below is derived from a request. A request may only SELECT from these,
# never extend them. This is the security boundary; keep it narrow.

# The three host files the webserver reads/writes, by a short key. An arbitrary
# path is never accepted -- the key maps to exactly one path.
FILES = {
    "auth":         "/etc/rvdashboard/dashboard-auth.json",  # PIN salt/hash/secret
    "wan-choice":   "/run/wan-manual-choice",                # "<role> <epoch>"
    "wan-fallback": "/run/wan-manual-fallback",              # "<wanted> <got> <epoch>"
}
FILE_MODES = {"auth": 0o600, "wan-choice": 0o644, "wan-fallback": 0o644}

# systemctl is-active may be asked about only these units.
UNITS_ALLOWED = {
    "wifi-api-rp5", "usbhub-api", "sophie-firewall", "wayvnc", "wan-scan-ondemand",
}

# The iptables reads the firewall card needs. -S dumps a chain's rules; the
# SOPHIE-* chains are also read with -L -vnx for their packet counters.
IPT_SPEC_CHAINS = ("INPUT", "FORWARD", "DOCKER-USER")
IPT_COUNT_CHAINS = ("SOPHIE-IN", "SOPHIE-FWD")

WAN_SCAN = "/usr/local/sbin/wan_scan.sh"
WAN_SCAN_UNIT = "wan-scan-ondemand"
WAN_SCAN_RESULT = "/run/wan-scan-result"

# Cellular modem prep (the privileged half of the dashboard's "cellular test").
# Constrained: only a device whose idVendor is a known cellular vendor is
# rebound, and only these fixed process names are killed.
CELLULAR_VENDOR_IDS = {"12d1", "19d2", "1e0e", "1bbb"}
MTP_PROCS = ("gvfs-mtp-volume-monitor", "mtp-probe", "libmtp")
USB_DRIVER_DIR = "/sys/bus/usb/drivers/usb"


def _run(cmd, **kw):
    """subprocess.run with text capture and a default timeout. Never raises."""
    kw.setdefault("capture_output", True)
    kw.setdefault("text", True)
    kw.setdefault("timeout", 15)
    try:
        p = subprocess.run(cmd, **kw)
        return p.returncode, p.stdout, p.stderr
    except Exception as exc:          # timeout, missing binary, ...
        return 255, "", str(exc)


# --- operations --------------------------------------------------------------

def op_firewall():
    """Raw iptables output for both families. The webserver parses it.

    A chain that cannot be read is reported as null, NOT "" -- the webserver's
    health logic must tell "chain is gone" (unhealthy) from "chain exists but
    empty". INPUT failing means the whole family is unreachable."""
    out = {}
    for fam, binary in IPTABLES.items():
        rc, inp, se = _run([binary, "-S", "INPUT"], timeout=5)
        if rc != 0:
            out[fam] = {"reachable": False, "error": se.strip()}
            continue
        spec = {"INPUT": inp.strip()}
        for chain in ("FORWARD", "DOCKER-USER"):
            rc, so, _ = _run([binary, "-S", chain], timeout=5)
            spec[chain] = so.strip() if rc == 0 else None
        counts = {}
        for chain in IPT_COUNT_CHAINS:
            rc, so, _ = _run([binary, "-L", chain, "-vnx"], timeout=5)
            counts[chain] = so.strip() if rc == 0 else None
        out[fam] = {"reachable": True, "spec": spec, "counts": counts}
    return out


def op_units(names):
    """`systemctl is-active` for allow-listed unit names. {name: state}."""
    names = [n for n in names if n in UNITS_ALLOWED]
    if not names:
        return {}
    rc, so, se = _run(["/usr/bin/systemctl", "is-active", *names], timeout=20)
    states = so.split()
    # is-active prints one line per unit, in order, even on non-zero exit.
    return {n: (states[i] if i < len(states) else "unknown")
            for i, n in enumerate(names)}


def op_read_file(key):
    """Raw contents of an allow-listed file, or None if absent/unreadable.

    None on ANY failure, never an error object: the webserver's contract is
    "file text or null" (its old `nsenter cat` path returned None on any
    non-zero exit), and it will json.loads() the auth content, so a dict here
    would break it. A genuine read error is logged to journald instead."""
    path = FILES[key]
    try:
        with open(path) as fh:
            return fh.read()
    except FileNotFoundError:
        return None
    except Exception as exc:
        print(f"WARNING: could not read {path}: {exc}", flush=True)
        return None


def op_write_file(key, text):
    """Write an allow-listed file with its fixed mode. (ok, detail)."""
    path = FILES[key]
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        # Write then chmod, so the mode is right even if the file pre-existed.
        with open(path, "w") as fh:
            fh.write(text)
        os.chmod(path, FILE_MODES[key])
        return True, ""
    except Exception as exc:
        return False, str(exc)


def op_remove_file(key):
    path = FILES[key]
    try:
        os.remove(path)
        return True, ""
    except FileNotFoundError:
        return True, "absent"          # removing an absent file is success
    except Exception as exc:
        return False, str(exc)


def op_wan_scan_start(on_loss):
    """systemd-run a detached wan_scan.sh. (started, message)."""
    mode = ["--on-loss"] if on_loss else []
    rc, so, se = _run(
        ["/usr/bin/systemd-run", f"--unit={WAN_SCAN_UNIT}", "--collect",
         "--service-type=oneshot", "/bin/bash", WAN_SCAN, *mode], timeout=20)
    if rc == 0:
        return True, "started"
    detail = (se or so).strip()
    if "already exists" in detail or "already running" in detail:
        return False, "already running"
    return False, detail or f"rc={rc}"


def op_wan_scan_state():
    rc, so, _ = _run(["/usr/bin/systemctl", "is-active", WAN_SCAN_UNIT], timeout=8)
    running = so.strip() == "active"
    result = op_read_file_path(WAN_SCAN_RESULT)
    return {"running": running, "result": result or ""}


def op_read_file_path(path):
    try:
        with open(path) as fh:
            return fh.read()
    except Exception:
        return None


def _compose_container_names():
    """Names of containers in our compose project (running or not)."""
    rc, so, _ = _run(
        ["/usr/bin/docker", "ps", "-a",
         "--filter", f"label=com.docker.compose.project={COMPOSE_PROJECT}",
         "--format", "{{.Names}}"], timeout=20)
    return [n for n in so.split() if n]


def op_containers():
    """Rich per-container state for the health reporter and the UI: state,
    health and StartedAt (the last is what the webserver's restart-loop
    detector counts changes of, so it must survive de-privileging). One
    `docker inspect` over the project's containers."""
    names = _compose_container_names()
    rows = []
    if names:
        rc, so, _ = _run(["/usr/bin/docker", "inspect", *names], timeout=25)
        try:
            for obj in json.loads(so or "[]"):
                st = obj.get("State", {}) or {}
                rows.append({
                    "name": (obj.get("Name", "") or "").lstrip("/"),
                    "state": st.get("Status", ""),
                    "health": (st.get("Health") or {}).get("Status", ""),
                    "started": st.get("StartedAt", ""),
                })
        except Exception:
            pass
    return {"project": COMPOSE_PROJECT, "containers": rows}


CONTAINER_ACTIONS = ("start", "stop", "restart")


def op_container_action(name, action):
    """start / stop / restart ONE named compose container. (ok, detail)."""
    if action not in CONTAINER_ACTIONS:
        return False, {"error": f"bad action {action!r}"}
    names = {r["name"] for r in op_containers()["containers"]}
    if name not in names:
        return False, {"error": f"unknown container {name!r}"}
    args = ["/usr/bin/docker", action]
    if action == "restart":
        args += ["-t", "10"]
    args.append(name)
    rc, so, se = _run(args, timeout=40)
    return rc == 0, {"name": name, "action": action, "detail": (se or so).strip()}


def op_restart(target):
    """Restart 'all', 'unhealthy', or one named compose container.
    Returns (ok, {restarted: [...], skipped: [...], error: str|None})."""
    rows = op_containers()["containers"]
    names = {r["name"] for r in rows}
    if target == "all":
        todo = [r["name"] for r in rows]
    elif target == "unhealthy":
        todo = [r["name"] for r in rows if r["health"] == "unhealthy"]
    elif target in names:
        todo = [target]
    else:
        return False, {"error": f"unknown target {target!r}", "restarted": [], "skipped": []}

    restarted, skipped = [], []
    for name in todo:
        rc, so, se = _run(["/usr/bin/docker", "restart", "-t", "10", name], timeout=40)
        (restarted if rc == 0 else skipped).append(name)
    return True, {"restarted": restarted, "skipped": skipped, "error": None}


def _find_modem_usb_path():
    """The modem's bus-port path (e.g. '1-1.1') by vendor id, or None. The path
    shifts across re-enumeration, so it is discovered, never hardcoded."""
    root = "/sys/bus/usb/devices"
    try:
        for entry in os.listdir(root):
            try:
                with open(os.path.join(root, entry, "idVendor")) as fh:
                    if fh.read().strip().lower() in CELLULAR_VENDOR_IDS:
                        return entry
            except OSError:
                continue
    except OSError:
        pass
    return None


def op_modem_prepare():
    """Kill MTP processes and unbind/rebind the cellular modem's USB device --
    the privileged half of the webserver's prepare_cellular_modem(). The
    webserver still does the unprivileged detect/wait/ModemManager checks."""
    mtp_killed = False
    for name in MTP_PROCS:
        rc, _, _ = _run(["/usr/bin/pkill", "-f", name], timeout=5)
        if rc == 0:
            mtp_killed = True
    if mtp_killed:
        time.sleep(2)

    usb_path = _find_modem_usb_path()
    if not usb_path:
        return {"ok": False, "mtp_killed": mtp_killed, "rescanned": False,
                "detail": "no cellular modem found on the USB bus"}
    try:
        if os.path.exists(f"{USB_DRIVER_DIR}/{usb_path}"):
            with open(f"{USB_DRIVER_DIR}/unbind", "w") as fh:
                fh.write(usb_path)
            time.sleep(1)
        with open(f"{USB_DRIVER_DIR}/bind", "w") as fh:
            fh.write(usb_path)
        time.sleep(2)
        return {"ok": True, "mtp_killed": mtp_killed, "rescanned": True,
                "usb_path": usb_path}
    except Exception as exc:
        return {"ok": False, "mtp_killed": mtp_killed, "rescanned": False,
                "usb_path": usb_path, "detail": str(exc)}


def _flush_journal():
    """Best-effort: persist the RAM-backed journal before a reboot."""
    _run(["/usr/bin/journalctl", "--sync"], timeout=5)
    _run(["/bin/sh", "-c",
          "rm -rf /var/log/journal-last-flush && "
          "mkdir -p /var/log/journal-last-flush && "
          "cp -a /run/log/journal/. /var/log/journal-last-flush/"], timeout=10)


def op_reboot(dry_run):
    _flush_journal()
    if dry_run:
        return True, "dry-run: journal flushed, reboot NOT issued"
    rc, so, se = _run(["/usr/bin/systemctl", "reboot"], timeout=5)
    if rc == 0:
        return True, "reboot issued"
    return False, (se or so).strip() or f"rc={rc}"


# --- HTTP --------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    server_version = "sophie-hostd/1.0"

    def log_message(self, *a):        # quiet; journald captures prints we want
        pass

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
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        return raw.decode()

    def _json_body(self):
        raw = self._body()
        if not raw:
            return {}
        return json.loads(raw)

    # -- GET --
    def do_GET(self):
        if not self._allowed():
            return self._send(403, {"error": "forbidden"})
        parts = urlparse(self.path)
        path = parts.path.rstrip("/")
        qs = parse_qs(parts.query)
        try:
            if path == "/api/health":
                return self._send(200, {"ok": True, "service": "sophie-hostd"})
            if path == "/api/firewall":
                return self._send(200, {"ok": True, "families": op_firewall()})
            if path == "/api/units":
                names = (qs.get("names", [""])[0]).split(",")
                return self._send(200, {"ok": True, "units": op_units([n for n in names if n])})
            if path == "/api/wan-manual":
                return self._send(200, {"ok": True,
                                        "choice": op_read_file("wan-choice"),
                                        "fallback": op_read_file("wan-fallback")})
            if path == "/api/wan-scan":
                return self._send(200, {"ok": True, **op_wan_scan_state()})
            if path == "/api/auth":
                content = op_read_file("auth")
                return self._send(200, {"ok": True, "content": content})
            if path == "/api/containers":
                return self._send(200, {"ok": True, **op_containers()})
        except Exception as exc:
            return self._send(500, {"error": str(exc)})
        return self._send(404, {"error": "not found", "path": path})

    # -- POST / PUT / DELETE --
    def do_POST(self):
        self._mutate("POST")

    def do_PUT(self):
        self._mutate("PUT")

    def do_DELETE(self):
        self._mutate("DELETE")

    def _mutate(self, method):
        if not self._allowed():
            return self._send(403, {"error": "forbidden"})
        path = urlparse(self.path).path.rstrip("/")
        try:
            if method == "PUT" and path == "/api/auth":
                ok, detail = op_write_file("auth", self._body())
                return self._send(200 if ok else 500, {"ok": ok, "detail": detail})

            if path == "/api/wan-manual":
                if method == "PUT":
                    body = self._json_body()
                    results = {}
                    for key in ("wan-choice", "wan-fallback"):
                        short = key.split("-", 1)[1]        # "choice" / "fallback"
                        if short in body and body[short] is not None:
                            ok, d = op_write_file(key, body[short])
                            results[short] = {"ok": ok, "detail": d}
                    return self._send(200, {"ok": True, "results": results})
                if method == "DELETE":
                    r1 = op_remove_file("wan-choice")
                    r2 = op_remove_file("wan-fallback")
                    return self._send(200, {"ok": r1[0] and r2[0],
                                            "choice": r1[1], "fallback": r2[1]})

            if method == "POST" and path == "/api/wan-scan":
                body = self._json_body()
                started, message = op_wan_scan_start(bool(body.get("on_loss")))
                return self._send(200, {"ok": True, "started": started, "message": message})

            if method == "POST" and path == "/api/containers/restart":
                body = self._json_body()
                target = body.get("target")
                if not target:
                    return self._send(400, {"error": "target required"})
                ok, detail = op_restart(target)
                return self._send(200 if ok else 400, {"ok": ok, **detail})

            if method == "POST" and path == "/api/containers/action":
                body = self._json_body()
                name, action = body.get("name"), body.get("action")
                if not name or not action:
                    return self._send(400, {"error": "name and action required"})
                ok, detail = op_container_action(name, action)
                return self._send(200 if ok else 400, {"ok": ok, **detail})

            if method == "POST" and path == "/api/modem/prepare":
                return self._send(200, op_modem_prepare())   # carries its own ok

            if method == "POST" and path == "/api/reboot":
                body = self._json_body()
                if not body.get("confirm"):
                    return self._send(400, {"error": "confirm:true required"})
                ok, message = op_reboot(bool(body.get("dry_run")))
                return self._send(200 if ok else 500, {"ok": ok, "message": message})
        except json.JSONDecodeError:
            return self._send(400, {"error": "bad JSON body"})
        except Exception as exc:
            return self._send(500, {"error": str(exc)})
        return self._send(404, {"error": "not found", "method": method, "path": path})


# --- systemd watchdog (same shape as usbhub_api.py) --------------------------

def _sd_notify(message):
    address = os.environ.get("NOTIFY_SOCKET")
    if not address:
        return
    if address.startswith("@"):
        address = "\0" + address[1:]
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        sock.connect(address)
        sock.sendall(message.encode())
        sock.close()
    except Exception:
        pass


def start_watchdog(port):
    """Ping systemd only while a real loopback request round-trips, so a wedged
    serve_forever() (not just a crashed process) trips WatchdogSec. Same reason
    the WiFi/usbhub daemons self-check rather than run a bare timer."""
    usec = os.environ.get("WATCHDOG_USEC")
    if not usec:
        return
    interval = max(1.0, int(usec) / 1_000_000 / 3)

    def loop():
        import urllib.request
        opener = urllib.request.build_opener()     # proxy-free, like the siblings
        while True:
            time.sleep(interval)
            try:
                with opener.open(f"http://127.0.0.1:{port}/api/health", timeout=5) as r:
                    if r.status == 200:
                        _sd_notify("WATCHDOG=1")
            except Exception:
                pass

    threading.Thread(target=loop, daemon=True).start()


def main():
    print(f"sophie-hostd listening on {BIND}:{PORT} "
          f"(allow={ALLOWED_NET}, compose project={COMPOSE_PROJECT})", flush=True)
    start_watchdog(PORT)
    _sd_notify("READY=1")
    ThreadingHTTPServer((BIND, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
