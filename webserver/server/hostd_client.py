"""
Client for sophie-hostd -- the host-root broker on 127.0.0.1:12348.

The webserver reaches it over loopback (it is network_mode: host, so localhost
is the host, exactly as for the usbhub and wifi host APIs). Every function here
mirrors one hostd endpoint and returns data in the shape server.py's existing
privileged helpers return, so a call site can swap to hostd with a thin
try/except and no other change.

On any transport problem (daemon down, timeout, non-2xx) a function raises
HostdUnavailable, which is the signal server.py uses to fall back to its legacy
nsenter/docker path while that still exists (the "dual-path" window). Once the
webserver is de-privileged the fallback is dead anyway, so after the cutover the
except branch is removed and these become the only path.

Stdlib only; no dependency the webserver image does not already have.
"""

import json
import os
import urllib.request
import urllib.error

HOST = os.environ.get("SOPHIE_HOSTD_HOST", "127.0.0.1")
PORT = int(os.environ.get("SOPHIE_HOSTD_PORT", "12348"))
BASE = f"http://{HOST}:{PORT}"

# A proxy-free opener: the webserver sets http_proxy for its outbound calls, and
# without this a loopback request to hostd would be sent to the proxy. Same
# reason wifi-api-rp5 and usbhub-api build their own openers (see server.py).
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class HostdUnavailable(Exception):
    """hostd could not be reached or returned an error. Callers fall back."""


def _call(method, path, body=None, timeout=10):
    """Return the parsed JSON body, or raise HostdUnavailable.

    body: dict -> JSON request; str -> raw request body; None -> no body.
    """
    data = None
    headers = {}
    if isinstance(body, dict):
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    elif isinstance(body, str):
        data = body.encode()
        headers["Content-Type"] = "text/plain"
    req = urllib.request.Request(BASE + path, data=data, method=method, headers=headers)
    try:
        with _opener.open(req, timeout=timeout) as resp:
            raw = resp.read().decode()
        return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        # A 4xx/5xx is still a reachable daemon; surface its message but treat
        # it as a failure the caller should handle (fall back or report).
        raise HostdUnavailable(f"hostd {method} {path} -> HTTP {exc.code}")
    except Exception as exc:                       # URLError, timeout, JSON error
        raise HostdUnavailable(f"hostd {method} {path} unreachable: {exc}")


def available(timeout=3):
    """True if hostd answers /api/health. Never raises."""
    try:
        return bool(_call("GET", "/api/health", timeout=timeout).get("ok"))
    except HostdUnavailable:
        return False


# --- reads -------------------------------------------------------------------

def firewall_raw(timeout=10):
    """{'v4': {...}, 'v6': {...}} of raw iptables output, for server.py to parse."""
    return _call("GET", "/api/firewall", timeout=timeout)["families"]


def units(names, timeout=20):
    """{name: state} for the given allow-listed unit names."""
    q = ",".join(names)
    return _call("GET", f"/api/units?names={q}", timeout=timeout)["units"]


def wan_manual_read(timeout=10):
    """{'choice': str|None, 'fallback': str|None}."""
    d = _call("GET", "/api/wan-manual", timeout=timeout)
    return {"choice": d.get("choice"), "fallback": d.get("fallback")}


def wan_scan_state(timeout=10):
    """{'running': bool, 'result': str}."""
    d = _call("GET", "/api/wan-scan", timeout=timeout)
    return {"running": d.get("running", False), "result": d.get("result", "")}


def auth_read(timeout=10):
    """The PIN-store file text, or None if it does not exist."""
    return _call("GET", "/api/auth", timeout=timeout).get("content")


def containers(timeout=20):
    """[{'name':..., 'status':...}, ...] for the compose project."""
    return _call("GET", "/api/containers", timeout=timeout)["containers"]


# --- writes / actions --------------------------------------------------------

def auth_write(text, timeout=10):
    """Write the PIN store (mode 0600). Returns True on success."""
    return bool(_call("PUT", "/api/auth", body=text, timeout=timeout).get("ok"))


def wan_manual_write(choice=None, fallback=None, timeout=10):
    """Write either/both of the manual-choice files. Returns the per-file results."""
    body = {}
    if choice is not None:
        body["choice"] = choice
    if fallback is not None:
        body["fallback"] = fallback
    return _call("PUT", "/api/wan-manual", body=body, timeout=timeout).get("results", {})


def wan_manual_delete(timeout=10):
    """Remove both manual-choice files. Returns True on success."""
    return bool(_call("DELETE", "/api/wan-manual", timeout=timeout).get("ok"))


def wan_scan_start(on_loss=False, timeout=20):
    """Trigger a detached WAN scan. Returns (started: bool, message: str)."""
    d = _call("POST", "/api/wan-scan", body={"on_loss": bool(on_loss)}, timeout=timeout)
    return bool(d.get("started")), d.get("message", "")


def restart(target, timeout=60):
    """Restart 'all' | 'unhealthy' | a container name. Returns the result dict."""
    return _call("POST", "/api/containers/restart", body={"target": target}, timeout=timeout)


def container_action(name, action, timeout=45):
    """start | stop | restart one named container. Returns (ok, detail)."""
    d = _call("POST", "/api/containers/action",
              body={"name": name, "action": action}, timeout=timeout)
    return bool(d.get("ok")), d


def reboot(dry_run=False, timeout=15):
    """Flush the journal and reboot (or, dry_run, just flush). Returns (ok, message)."""
    d = _call("POST", "/api/reboot", body={"confirm": True, "dry_run": bool(dry_run)},
              timeout=timeout)
    return bool(d.get("ok")), d.get("message", "")
