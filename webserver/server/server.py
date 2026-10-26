#!/usr/bin/env python3
import threading
import uvicorn
import os
import subprocess
import tempfile
import sys
import time
import socket
import re
import requests
import urllib.request
import urllib.error
import json
import hmac
import hashlib
import secrets
import base64
import shutil
import signal
import atexit
import logging

# Load .env file if present (for local development credentials)
try:
    from dotenv import load_dotenv
    load_dotenv()  # loads server/.env when running from server/ directory
except ImportError:
    pass  # python-dotenv not installed; rely on environment variables directly

# Initialize alarm-related global variables
# MQTT is always available as a fallback (broker is always running)
alarm_mqtt_available = True

# Global debug setting
DEBUG_MODE = os.getenv('SERVER_DEBUG', '').lower() in ('true', '1', 'yes')  # Enable with SERVER_DEBUG=true

_mqtt_subscriber_thread = None  # set at startup; checked by /health

# Import alarm system from the rv/alarm directory (optional)
try:
    sys.path.append('/home/tblank/code/tblank1024/rv/alarm')
    import alarm
    ALARM_AVAILABLE = True
    print("Alarm system module loaded successfully")
except ImportError as e:
    print(f"Alarm system not available: {e}")
    print("Web alarm buttons will work for state tracking only")
    ALARM_AVAILABLE = False
    alarm = None
    # Check if we should use MQTT for alarm communication
    alarm_mqtt_available = True
    print("Will attempt MQTT communication with alarm container")
from rvglue import MQTTClient
import rvglue
from typing import Annotated, Optional
from kasa_power_strip import KasaPowerStrip, KasaPowerStripError
from usb_modem_manager import usb_modem_manager

from fastapi import FastAPI, Body, HTTPException, Request
from pydantic import BaseModel
from starlette.staticfiles import StaticFiles
from starlette.responses import Response, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import random
from server_calcs import *
from server_calcs import constants
import paho.mqtt.client as _paho_mqtt


def _mqtt_client_with_auth(*args, **kwargs):
    """Create a paho client with broker credentials from MQTT_USER/MQTT_PASS.

    Unset env vars mean anonymous, so the server still works against a
    pre-auth broker.
    """
    c = _paho_mqtt.Client(*args, **kwargs)
    mqtt_user = os.environ.get('MQTT_USER')
    if mqtt_user:
        c.username_pw_set(mqtt_user, os.environ.get('MQTT_PASS', ''))
    return c


# ---------------------------------------------------------------------------
# Tire TPMS data — populated by background MQTT subscriber
# Keys match TireLinc position names (FL, FR, RL_out, RL_in, RR_out, RR_in)
# ---------------------------------------------------------------------------
_tire_data: dict = {}

# Long-lived MQTT bus: one client serves the tire cache, the alarm status
# cache (fed by the alarm container's retained status topics), and all
# publishes — replacing the old client-per-request pattern with its sleeps.
_mqtt_bus = None
_alarm_status: dict = {}   # 'bike'/'interior' -> bool

def _start_mqtt_bus() -> None:
    """Connect the shared MQTT client in a daemon thread and cache
    tire telemetry and retained alarm status as messages arrive."""
    def _on_message(client, userdata, msg):
        try:
            if msg.topic.startswith('RVC/TIRE_STATUS/'):
                payload = json.loads(msg.payload.decode('utf-8'))
                name = payload.get('name')
                if name:
                    _tire_data[name] = {
                        'psi':    payload.get('pressure_psi'),
                        'temp_f': payload.get('temp_f'),
                        'ts':     time.time(),
                    }
            elif msg.topic == 'rv/alarm/bike/status':
                _alarm_status['bike'] = msg.payload.decode('utf-8') == 'on'
            elif msg.topic == 'rv/alarm/interior/status':
                _alarm_status['interior'] = msg.payload.decode('utf-8') == 'on'
        except Exception:
            pass

    def _on_connect(client, ud, flags, rc):
        client.subscribe('RVC/TIRE_STATUS/#', 0)
        client.subscribe('rv/alarm/bike/status', 0)
        client.subscribe('rv/alarm/interior/status', 0)

    def _run():
        global _mqtt_bus
        c = _mqtt_client_with_auth()
        c.on_message = _on_message
        c.on_connect = _on_connect
        c.reconnect_delay_set(min_delay=5, max_delay=60)
        _mqtt_bus = c
        while True:
            try:
                c.connect('localhost', 1883, 60)
                c.loop_forever()
                # loop_forever() only returns on explicit disconnect
            except Exception as e:
                print(f'MQTT bus error: {e}, retrying in 10s')
                time.sleep(10)

    t = threading.Thread(target=_run, daemon=True)
    t.start()

_TIRE_DATA_TTL = 120  # seconds — clear stale entries after 2 minutes

def _tire_psi(name: str) -> str:
    d = _tire_data.get(name)
    if d and d.get('psi') is not None and (time.time() - d.get('ts', 0)) < _TIRE_DATA_TTL:
        return f"{d['psi']} psi"
    return '-- psi'

def _tire_temp(name: str) -> str:
    d = _tire_data.get(name)
    if d and d.get('temp_f') is not None and (time.time() - d.get('ts', 0)) < _TIRE_DATA_TTL:
        return f"{d['temp_f']}\u00b0F"
    return ''

_TANK_DATA_TTL = 300  # seconds \u2014 RV-C tank status updates infrequently
_TANK_UNINIT = 3.14   # rvglue placeholder value before any MQTT message has arrived

def _tank_pct(level_key: str, res_key: str) -> str:
    """Percentage-full string for a tank, or '--' if the reading is missing/stale."""
    ad, ts, now = rvglue.rvglue.AliasData, rvglue.rvglue.AliasDataTS, time.time()
    level, res = ad.get(level_key), ad.get(res_key)
    fresh = (now - ts.get(level_key, 0) < _TANK_DATA_TTL
             and now - ts.get(res_key, 0) < _TANK_DATA_TTL)
    if not fresh or level in (None, _TANK_UNINIT) or res in (None, _TANK_UNINIT):
        return '--'
    try:
        return str(round(level / res * 100))
    except ZeroDivisionError:
        return '--'



app = FastAPI()
try:
    index_content = open("build/index.html").read()
except FileNotFoundError:
    index_content = "<html><body><h1>RV Security Server Running</h1><p>Build the client first with 'make build'</p></body></html>"

# Cross-origin policy. This used to be allow_origins=["*"] with
# allow_credentials=True, which is the widest setting there is, and because
# those two are contradictory under the CORS spec Starlette resolved it by
# ECHOING back whatever Origin asked. Verified 2026-10-23: a preflight for
# POST /api/system/reboot sent from "https://evil.example" was answered
#   access-control-allow-origin: https://evil.example
#   access-control-allow-credentials: true
# i.e. approved. Since this API has no authentication and ~20 endpoints that
# act on the world (host reboot, container restart, hub socket power, WAN
# selection, Kasa mains outlets, Synology shutdown, alarm state), that let ANY
# web page loaded by ANY browser on the RV LAN drive the RV and read the
# replies. A phone on Sophie's WiFi following a bad link was enough; the user
# did not have to do anything wrong. The host firewall cannot help here --
# br0 is trusted by design, or the dashboard would not work at all.
#
# Production needs no cross-origin permission whatsoever: client/src/constants.js
# sets IPADDR="auto" and PORT="8000", and utils/api.js derives the API base from
# window.location.hostname, so the page and the API are always the same origin
# and the browser never consults this policy. Narrowing it therefore cannot
# break access from the RV LAN, the house LAN or cellular, at any address.
#
# The only genuine cross-origin case is `make client_start` -- the CRA dev
# server on :3000 calling the API on :8000. That is what this list is for.
# Add others with DASHBOARD_CORS_ORIGINS (comma separated) rather than
# widening this back to "*".
_default_cors = "http://localhost:3000,http://127.0.0.1:3000"
_cors_origins = [
    o.strip()
    for o in os.environ.get("DASHBOARD_CORS_ORIGINS", _default_cors).split(",")
    if o.strip()
]
if "*" in _cors_origins:
    # Refuse the one value that reintroduces the hole described above.
    logging.warning(
        'DASHBOARD_CORS_ORIGINS contains "*", which would let any website on '
        "the internet drive this unauthenticated API through a LAN browser. "
        "Ignoring it; set explicit origins instead."
    )
    _cors_origins = [o for o in _cors_origins if o != "*"] or _default_cors.split(",")
logging.info("CORS: allowing origins %s", _cors_origins)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    # Was False, on the reasoning that no cookies were used and a bearer token
    # would travel in the Authorization header instead. The PIN gate changed
    # that deliberately: a cookie can be HttpOnly, so page JavaScript cannot
    # read it and an injected script cannot steal and replay it, which a token
    # in localStorage cannot match.
    #
    # True is safe here ONLY because _cors_origins is an explicit list that
    # cannot contain "*" -- that is refused and logged above, and it was the
    # "*" plus credentials combination that forced the origin echo described
    # there. Cross-site writes are also refused outright by
    # block_cross_site_writes regardless of this flag, so this does not reopen
    # what 75badd3 closed. The cookie has to cross origins at all only because
    # the CRA dev server on :3000 calls the API on :8000; in production the
    # dashboard is same-origin.
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Accept", "Authorization"],
)


# Narrowing the CORS list above is necessary but NOT sufficient, and it is worth
# being precise about why, because the gap is easy to miss.
#
# CORS governs whether a page may READ a reply. It does not stop the browser from
# SENDING the request. A "simple" request -- GET, or POST whose Content-Type is
# text/plain, form-urlencoded or multipart, with no custom headers -- gets no
# preflight at all: the browser just sends it, then withholds the response. Any
# side effect has already happened. That is CSRF, and CORS never addressed it.
#
# Measured 2026-10-25 after pinning the origins: of the 20 write endpoints, the 11
# that require a JSON body became unreachable from a web page, because the JSON
# Content-Type forces a preflight that now fails. The 9 that take NO body were
# still wide open -- including POST /api/system/reboot,
# POST /api/system/restart-containers and POST /api/debug/synology/{action}.
# Confirmed with a text/plain POST and a foreign Origin to the harmless
# /api/debug/kasa/clear-cache: 200.
#
# So this guard closes the half CORS cannot. Browsers attach an Origin header to
# every cross-origin state-changing request, simple ones included, and to
# same-origin POSTs as well. Three cases:
#   - no Origin            -> not a browser (curl, a script, a container). Allowed;
#                             anything on the LAN can already open a socket, so
#                             rejecting here would buy nothing and break tooling.
#   - Origin == our own    -> the dashboard talking to the host that served it.
#     host                   Allowed at ANY address, which is what keeps RV-LAN,
#                             house-LAN and cellular access working.
#   - any other Origin     -> a different site driving us. Refused.
# This is not authentication, and it is not a substitute for it: a non-browser
# client on the LAN is unaffected. It removes the drive-by path, where merely
# loading a page on a phone joined to Sophie's WiFi was enough to reboot her.
# ===========================================================================
# PIN gate
# ===========================================================================
# Design, scope and the measurements behind it: plan_pin_protection.md.
#
# In one paragraph: the dashboard has no authentication, and the cross-site
# guard below only stops a *website* driving it through a LAN browser -- a
# script on the RV LAN was always unaffected. This gates the actions that can
# reboot Sophie, cut power or disarm the alarm. The threat model is accident
# and casual access (a guest with the WiFi password, a child tapping a red
# button), NOT a determined attacker: the dashboard is plain HTTP, so the PIN
# crosses the air in clear text and no password would be better.
#
# Arming the alarm is deliberately NOT gated -- arming can never cause harm,
# and friction there is how people stop arming. That check lives inside the
# alarm handler rather than here, because by then Pydantic has coerced `state`
# into a real bool; this middleware sees a raw body where "off" and false and
# 0 all mean disarm, and a naive `state is False` would wave three of them
# through.
AUTH_FILE = "/etc/rvdashboard/dashboard-auth.json"
AUTH_COOKIE = "sophie_pin"
AUTH_TTL = 30 * 24 * 3600          # a device stays trusted 30 days
AUTH_RENEW_AFTER = 24 * 3600       # re-issue once a token is a day old
PIN_MIN_DIGITS = 4
LOCKOUT_MAX_FAILURES = 5           # per window, per source address
LOCKOUT_WINDOW = 900
LOCKOUT_FREEZE = 900

# What needs the PIN, as (method, compiled path pattern).
#
# The nine write endpoints are the agreed scope. The four GETs after them are
# the debug page's own data, so the page cannot be *viewed* without the PIN
# rather than merely being unable to act -- they were checked to be used by no
# other page. /api/debug/synology/status and .../scheduled-time are
# deliberately absent: the Plex page reads them to display NAS state, they
# change nothing, and gating them would break a page nobody asked to gate.
_PROTECTED = [
    ("POST",   r"^/api/system/reboot$"),
    ("POST",   r"^/api/system/restart-containers$"),
    ("POST",   r"^/api/debug/synology/schedule-shutdown$"),
    ("DELETE", r"^/api/debug/synology/scheduled-time$"),
    ("POST",   r"^/api/debug/synology/(?!status$)[^/]+$"),
    ("POST",   r"^/api/debug/kasa/(?!clear-cache$)\d+$"),
    ("POST",   r"^/api/hub/socket$"),
    ("POST",   r"^/api/hub/socket/exclusive$"),
    # The debug page's reads.
    ("GET",    r"^/api/debug/firewall/status$"),
    ("GET",    r"^/api/debug/kasa/status$"),
    ("GET",    r"^/api/debug/watcher/logs$"),
    ("GET",    r"^/api/hub/sockets$"),
]
_PROTECTED = [(m, re.compile(p)) for m, p in _PROTECTED]

_auth_lock = threading.Lock()
_auth_failures: dict = {}          # source address -> [failure timestamps]


def _auth_config():
    """
    The stored salt, PIN hash, signing secret and generation, or None if no
    PIN has been set yet.

    Lives on the HOST at AUTH_FILE, read through the init mount namespace for
    the same reason as the manual uplink choice: this container does not share
    the host filesystem, and a file baked into the image would ship the PIN
    hash inside it.
    """
    try:
        proc = subprocess.run(
            ["nsenter", "-t", "1", "-m", "--", "cat", AUTH_FILE],
            capture_output=True, text=True, timeout=10)
        if proc.returncode != 0:
            return None
        config = json.loads(proc.stdout)
    except Exception as exc:
        print(f"WARNING: could not read {AUTH_FILE}: {exc}")
        return None
    if not all(k in config for k in ("pin_salt", "pin_hash", "secret")):
        return None
    config.setdefault("generation", 1)
    return config


def _auth_config_write(config) -> bool:
    text = json.dumps(config, indent=2) + "\n"
    try:
        proc = subprocess.run(
            ["nsenter", "-t", "1", "-m", "--", "sh", "-c",
             f"mkdir -p $(dirname {AUTH_FILE}) && cat > {AUTH_FILE} "
             f"&& chmod 0600 {AUTH_FILE}"],
            input=text, capture_output=True, text=True, timeout=10)
        if proc.returncode != 0:
            print(f"WARNING: could not write {AUTH_FILE}: {proc.stderr.strip()}")
            return False
        return True
    except Exception as exc:
        print(f"WARNING: could not write {AUTH_FILE}: {exc}")
        return False


def _hash_pin(pin: str, salt: str) -> str:
    """scrypt, so a stolen file cannot be brute-forced as fast as the 10 000
    possible 4-digit PINs otherwise invite."""
    return hashlib.scrypt(pin.encode(), salt=bytes.fromhex(salt),
                          n=2 ** 14, r=8, p=1, dklen=32).hex()


def _issue_token(config) -> str:
    """
    A signed, stateless token: "<payload>.<hmac>".

    Stateless on purpose. Server-side sessions would be lost on every
    container rebuild -- which happens often here -- logging every device out.
    Revocation still works because the generation counter is inside the signed
    payload, so bumping it in the config file invalidates every token at once.
    """
    payload = json.dumps({"exp": int(time.time() + AUTH_TTL),
                          "gen": int(config["generation"])},
                         separators=(",", ":")).encode()
    body = base64.urlsafe_b64encode(payload).decode().rstrip("=")
    sig = hmac.new(bytes.fromhex(config["secret"]), body.encode(),
                   hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def _token_claims(token: str, config):
    """The token's claims if it is validly signed, current and unexpired."""
    if not token or "." not in token or config is None:
        return None
    body, _, sig = token.rpartition(".")
    expected = hmac.new(bytes.fromhex(config["secret"]), body.encode(),
                        hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        padding = "=" * (-len(body) % 4)
        claims = json.loads(base64.urlsafe_b64decode(body + padding))
    except Exception:
        return None
    if int(claims.get("gen", 0)) != int(config["generation"]):
        return None          # revoked by a generation bump
    if float(claims.get("exp", 0)) < time.time():
        return None
    return claims


def _client_address(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _lockout_remaining(address: str) -> int:
    """Seconds left on a freeze for this address, or 0."""
    now = time.time()
    with _auth_lock:
        hits = [t for t in _auth_failures.get(address, [])
                if now - t < LOCKOUT_WINDOW]
        _auth_failures[address] = hits
        if len(hits) >= LOCKOUT_MAX_FAILURES:
            return int(LOCKOUT_FREEZE - (now - hits[-1])) or 1
    return 0


def _record_failure(address: str):
    with _auth_lock:
        _auth_failures.setdefault(address, []).append(time.time())


def _clear_failures(address: str):
    with _auth_lock:
        _auth_failures.pop(address, None)


def is_authenticated(request: Request):
    """(authenticated, claims, config) for this request."""
    config = _auth_config()
    if config is None:
        # No PIN set: nothing is gated. Said plainly rather than failing
        # closed, because failing closed on a fresh install would lock the
        # owner out of the page where the PIN is set.
        return True, None, None
    claims = _token_claims(request.cookies.get(AUTH_COOKIE, ""), config)
    return claims is not None, claims, config


def _needs_pin(method: str, path: str) -> bool:
    return any(m == method and pattern.match(path) for m, pattern in _PROTECTED)


def require_pin(request: Request):
    """Raise 401 unless this request carries a valid token. For handlers that
    gate on the payload rather than the path -- currently alarm disarm."""
    authenticated, _, config = is_authenticated(request)
    if config is not None and not authenticated:
        raise HTTPException(status_code=401, detail="PIN required")


class PinData(BaseModel):
    pin: str


class PinChangeData(BaseModel):
    current: str
    new: str


def _is_rv_lan(address: str) -> bool:
    """Sophie's own LAN (br0 is 10.0.0.1/24), or loopback."""
    return (address.startswith("10.0.0.")
            or address in ("127.0.0.1", "::1", "localhost"))


def _pin_is_plausible(pin: str):
    if not pin.isdigit() or len(pin) < PIN_MIN_DIGITS:
        return False, f"the PIN must be at least {PIN_MIN_DIGITS} digits, numbers only"
    return True, ""


def _set_auth_cookie(response, token: str):
    response.set_cookie(
        AUTH_COOKIE, token,
        max_age=AUTH_TTL,
        # httponly: page JavaScript cannot read this, so a script injected
        # into the dashboard cannot steal the token and replay it elsewhere.
        httponly=True,
        samesite="lax",
        # NOT secure: the dashboard is plain HTTP, and a Secure cookie would
        # simply never be sent. This is also why the PIN is not strong
        # authentication -- see plan_pin_protection.md "Honest limits".
        secure=False,
        path="/",
    )


@app.get("/api/auth/status")
def auth_status(request: Request) -> Response:
    """Whether a PIN is set, whether this device is trusted, and how long for."""
    authenticated, claims, config = is_authenticated(request)
    remaining = _lockout_remaining(_client_address(request))
    response = JSONResponse({
        "configured": config is not None,
        "authenticated": authenticated,
        "locked_out": remaining > 0,
        "retry_after": remaining,
        "expires_in": int(claims["exp"] - time.time()) if claims else None,
        "can_set_pin": _is_rv_lan(_client_address(request)),
    })
    # "Renewed on use": a device that keeps visiting never has to re-enter the
    # PIN, while one that stops visiting falls out of trust on schedule.
    if (config is not None and claims
            and (claims["exp"] - time.time()) < (AUTH_TTL - AUTH_RENEW_AFTER)):
        _set_auth_cookie(response, _issue_token(config))
    return response


@app.post("/api/auth/setup")
def auth_setup(request: Request, data: Annotated[PinData, Body()]) -> Response:
    """
    Set the PIN for the first time.

    Refused from anywhere but the RV's own LAN. Otherwise, on a Pi that has
    never had a PIN, whoever reached the dashboard first over a campground
    network could claim it -- and then hold the gate against the owner.
    """
    if _auth_config() is not None:
        return JSONResponse({"success": False,
                             "message": "a PIN is already set; use Change PIN"},
                            status_code=400)
    address = _client_address(request)
    if not _is_rv_lan(address):
        logging.warning("Refused PIN setup from off-LAN address %s", address)
        return JSONResponse(
            {"success": False,
             "message": "The PIN can only be set from Sophie's own network. "
                        f"You are connecting from {address}."},
            status_code=403)
    ok, why = _pin_is_plausible(data.pin)
    if not ok:
        return JSONResponse({"success": False, "message": why}, status_code=400)

    salt = secrets.token_hex(16)
    config = {"pin_salt": salt,
              "pin_hash": _hash_pin(data.pin, salt),
              "secret": secrets.token_hex(32),
              "generation": 1}
    if not _auth_config_write(config):
        return JSONResponse({"success": False,
                             "message": f"could not write {AUTH_FILE}"},
                            status_code=500)
    logging.warning("Dashboard PIN set from %s", address)
    response = JSONResponse({"success": True, "message": "PIN set"})
    _set_auth_cookie(response, _issue_token(config))
    return response


@app.post("/api/auth/pin")
def auth_pin(request: Request, data: Annotated[PinData, Body()]) -> Response:
    """Enter the PIN. Every attempt is logged, successful or not."""
    config = _auth_config()
    if config is None:
        return JSONResponse({"success": False, "message": "no PIN is set"},
                            status_code=400)
    address = _client_address(request)
    remaining = _lockout_remaining(address)
    if remaining > 0:
        logging.warning("PIN attempt from %s refused: frozen for %ss",
                        address, remaining)
        return JSONResponse(
            {"success": False, "locked_out": True, "retry_after": remaining,
             "message": f"Too many wrong attempts. Try again in "
                        f"{remaining // 60 + 1} minutes."},
            status_code=429)

    if not hmac.compare_digest(_hash_pin(data.pin, config["pin_salt"]),
                               config["pin_hash"]):
        _record_failure(address)
        with _auth_lock:
            used = len(_auth_failures.get(address, []))
        left = max(0, LOCKOUT_MAX_FAILURES - used)
        logging.warning("Wrong dashboard PIN from %s (%s attempts left)",
                        address, left)
        return JSONResponse({"success": False, "attempts_left": left,
                             "message": "Wrong PIN."}, status_code=401)

    _clear_failures(address)
    logging.info("Dashboard PIN accepted from %s", address)
    response = JSONResponse({"success": True, "message": "Unlocked"})
    _set_auth_cookie(response, _issue_token(config))
    return response


@app.post("/api/auth/change")
def auth_change(request: Request, data: Annotated[PinChangeData, Body()]) -> Response:
    """Change the PIN. Needs the current one, so a trusted device that has
    been left lying around cannot silently change the lock."""
    config = _auth_config()
    if config is None:
        return JSONResponse({"success": False, "message": "no PIN is set"},
                            status_code=400)
    address = _client_address(request)
    if _lockout_remaining(address) > 0:
        return JSONResponse({"success": False, "message": "Too many wrong attempts."},
                            status_code=429)
    if not hmac.compare_digest(_hash_pin(data.current, config["pin_salt"]),
                               config["pin_hash"]):
        _record_failure(address)
        logging.warning("Wrong current PIN on change attempt from %s", address)
        return JSONResponse({"success": False, "message": "Wrong current PIN."},
                            status_code=401)
    ok, why = _pin_is_plausible(data.new)
    if not ok:
        return JSONResponse({"success": False, "message": why}, status_code=400)

    salt = secrets.token_hex(16)
    config.update({"pin_salt": salt, "pin_hash": _hash_pin(data.new, salt)})
    # The signing secret is rotated too, so changing the PIN also signs every
    # other device out -- which is the point of changing it.
    config["secret"] = secrets.token_hex(32)
    config["generation"] = int(config["generation"]) + 1
    if not _auth_config_write(config):
        return JSONResponse({"success": False, "message": "could not update the PIN file"},
                            status_code=500)
    _clear_failures(address)
    logging.warning("Dashboard PIN changed from %s; all devices signed out", address)
    response = JSONResponse({"success": True,
                             "message": "PIN changed. Other devices must enter the new one."})
    _set_auth_cookie(response, _issue_token(config))
    return response


@app.post("/api/auth/logout")
def auth_logout() -> Response:
    response = JSONResponse({"success": True, "message": "This device is signed out."})
    response.delete_cookie(AUTH_COOKIE, path="/")
    return response


@app.post("/api/auth/revoke-all")
def auth_revoke_all(request: Request) -> Response:
    """
    Forget every device, including this one.

    Works by bumping the generation counter that is inside every signed token,
    so all of them stop validating at once. That is what makes stateless
    tokens acceptable here: a lost phone can be cut off without the server
    having kept a list of sessions that a rebuild would have thrown away.
    """
    require_pin(request)
    config = _auth_config()
    if config is None:
        return JSONResponse({"success": False, "message": "no PIN is set"},
                            status_code=400)
    config["generation"] = int(config["generation"]) + 1
    if not _auth_config_write(config):
        return JSONResponse({"success": False, "message": "could not update the PIN file"},
                            status_code=500)
    logging.warning("All dashboard devices revoked from %s (generation %s)",
                    _client_address(request), config["generation"])
    response = JSONResponse({"success": True,
                             "message": "Every device must enter the PIN again."})
    response.delete_cookie(AUTH_COOKIE, path="/")
    return response


# Defined BEFORE the cross-site guard so that guard ends up outermost: a
# cross-site request should be refused as cross-site, which is the more
# informative answer, rather than as missing a PIN it could never have sent.
@app.middleware("http")
async def enforce_pin(request: Request, call_next):
    if _needs_pin(request.method, request.url.path):
        authenticated, _, config = is_authenticated(request)
        if config is not None and not authenticated:
            logging.warning("PIN required for %s %s from %s", request.method,
                            request.url.path, _client_address(request))
            return JSONResponse(
                {"success": False, "pin_required": True,
                 "message": "This needs the dashboard PIN."},
                status_code=401)
    return await call_next(request)


_UNSAFE_METHODS = {"POST", "PUT", "DELETE", "PATCH"}


def _origin_is_self(origin: str, host_header: str) -> bool:
    """True if `origin` names the same host:port the request was addressed to."""
    if not origin or not host_header:
        return False
    netloc = origin.split("://", 1)[-1]
    if netloc == host_header:
        return True
    # Tolerate a default port on one side only (http://h vs h:80).
    bare_origin = netloc.rsplit(":", 1)[0] if ":" in netloc else netloc
    bare_host = host_header.rsplit(":", 1)[0] if ":" in host_header else host_header
    return bare_origin == bare_host and {netloc, host_header} & {bare_origin}


@app.middleware("http")
async def block_cross_site_writes(request: Request, call_next):
    if request.method in _UNSAFE_METHODS:
        origin = request.headers.get("origin", "")
        if origin:
            host_header = request.headers.get("host", "")
            if origin not in _cors_origins and not _origin_is_self(origin, host_header):
                logging.warning(
                    "Refused %s %s from cross-site origin %r (host %r)",
                    request.method, request.url.path, origin, host_header,
                )
                return JSONResponse(
                    {"success": False,
                     "message": "Cross-site request refused. This API only accepts "
                                "state-changing requests from its own dashboard."},
                    status_code=403,
                )
    return await call_next(request)

@app.get("/")
@app.get("/power")
@app.get("/wifi")
@app.get("/internet")
@app.get("/debug")
async def index():
    return Response(index_content)

bike_alarm_state = False
interior_alarm_state = False

# Initialize alarm system
alarm_system = None
alarm_thread = None
alarm_thread_stop_event = None

# Internet Connection State Management
_INTERNET_STATE_FILE = "/tmp/internet_connection_state.txt"

def _load_internet_state():
    """Load persisted internet connection state from file."""
    try:
        if os.path.exists(_INTERNET_STATE_FILE):
            with open(_INTERNET_STATE_FILE, "r") as f:
                state = f.read().strip()
            valid_states = {"none", "cellular", "cellular-amp", "wifi", "starlink", "wired"}
            if state in valid_states:
                print(f"INFO: Loaded persisted internet connection state: {state}")
                return state
    except Exception as e:
        print(f"WARNING: Could not load internet connection state: {e}")
    return "none"

def _save_internet_state(state):
    """Persist internet connection state to file (only when state actually changed)."""
    try:
        if os.path.exists(_INTERNET_STATE_FILE):
            with open(_INTERNET_STATE_FILE, "r") as f:
                if f.read().strip() == state:
                    return  # no change — skip the write
        with open(_INTERNET_STATE_FILE, "w") as f:
            f.write(state)
    except Exception as e:
        print(f"WARNING: Could not save internet connection state: {e}")

current_internet_connection = _load_internet_state()  # Tracks current connection: "none", "cellular", "wifi", "starlink", "wired"
# Synology scheduled shutdown management
scheduled_shutdown_timestamp = None
shutdown_timer = None

def execute_scheduled_shutdown():
    """Execute the scheduled shutdown of Synology NAS"""
    global scheduled_shutdown_timestamp, shutdown_timer
    print("Executing scheduled Synology shutdown...")
    try:
        # Call the actual shutdown command
        import subprocess
        server_dir = os.path.dirname(os.path.abspath(__file__))
        password_file = os.path.join(server_dir, 'synology-password.json')
        cmd = ['python', 'synology_nas_controller.py', '--power-off', '--force', '--config', password_file]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15, cwd=server_dir)
        
        if result.returncode == 0:
            print("Scheduled shutdown completed successfully")
        else:
            print(f"Scheduled shutdown failed: {result.stderr}")
    except Exception as e:
        print(f"Error during scheduled shutdown: {e}")
    finally:
        # Clear the scheduled time and timer
        scheduled_shutdown_timestamp = None
        shutdown_timer = None

def cancel_shutdown_timer():
    """Cancel any existing shutdown timer"""
    global shutdown_timer
    if shutdown_timer is not None:
        shutdown_timer.cancel()
        shutdown_timer = None

def schedule_shutdown_timer(delay_seconds):
    """Schedule a shutdown timer for the specified delay"""
    global shutdown_timer
    # Cancel any existing timer first
    cancel_shutdown_timer()
    # Create new timer
    shutdown_timer = threading.Timer(delay_seconds, execute_scheduled_shutdown)
    shutdown_timer.start()
    print(f"Scheduled shutdown timer set for {delay_seconds} seconds")

def initialize_alarm_system():
    """Initialize the alarm system with error handling"""
    global alarm_system, alarm_thread, alarm_thread_stop_event, alarm_mqtt_available
    
    # First check if we have direct alarm module access
    if ALARM_AVAILABLE and alarm is not None:
        try:
            debug_level = 0  # Set to 0 for normal operation, 1 for debug
            alarm_system = alarm.Alarm(debug_level)
            print("Alarm system initialized successfully (direct GPIO)")
            
            # Start the alarm monitoring thread
            alarm_thread_stop_event = threading.Event()
            alarm_thread = threading.Thread(target=alarm_monitoring_loop, daemon=True)
            alarm_thread.start()
            print("Alarm monitoring thread started")
            
            return True
        except Exception as e:
            print(f"Warning: Could not initialize direct GPIO alarm system: {e}")
            alarm_system = None
    
    # If direct GPIO failed, check if MQTT communication is available
    if alarm_mqtt_available:
        print("Direct GPIO alarm not available, using MQTT communication")
        print("Web alarm buttons will control physical alarms via MQTT")
        alarm_system = None  # Make sure it's None for MQTT mode
        return True
    else:
        print("No alarm system available - web alarm buttons will work for state tracking only")
        alarm_system = None
        return False

def alarm_monitoring_loop():
    """Background thread function that runs the alarm system monitoring loop"""
    global alarm_system, alarm_thread_stop_event
    
    if alarm_system is None:
        print("No direct alarm system available, monitoring loop not started")
        return
    
    print("Starting alarm monitoring loop in background thread")
    
    while not alarm_thread_stop_event.is_set():
        try:
            # Run one iteration of the alarm monitoring
            if alarm_system.debuglevel == 10:
                alarm_system._InternalTest()
            else:
                if alarm_system.InteriorState == alarm.States.OFF and alarm_system.BikeState == alarm.States.OFF and alarm_system.LoopCount > 10000:
                    # Don't let the LoopCount get too big
                    alarm_system.LoopCount = 1      
                else:
                    alarm_system.LoopCount += 1
                    
                alarm_system.LoopTime = time.time()
                alarm_system._check_buttons()    
                alarm_system._check_bike_wire()
                alarm_system._check_interior()
                alarm_system._update_timed_transitions()
                alarm_system._display()
                
                # Sync physical alarm states with web interface
                sync_alarm_states()
                
            # Sleep between iterations
            time.sleep(alarm_system.LOOPDELAY)
            
        except Exception as e:
            print(f"Error in alarm monitoring loop: {e}")
            time.sleep(1)  # Sleep longer on error to prevent spam
    
    print("Alarm monitoring loop stopped")

def sync_alarm_states():
    """Synchronize physical alarm states with web interface state variables"""
    global alarm_system, bike_alarm_state, interior_alarm_state
    
    if alarm_system is None or alarm is None:
        return
    
    # Convert physical alarm states to boolean for web interface
    # Physical alarm is considered "on" if it's in STARTING, ON, TRIGDELAY, TRIGGERED, or SILENCED states
    active_states = [alarm.States.STARTING, alarm.States.ON, alarm.States.TRIGDELAY, 
                    alarm.States.TRIGGERED, alarm.States.SILENCED]
    
    new_bike_state = alarm_system.BikeState in active_states
    new_interior_state = alarm_system.InteriorState in active_states
    
    # Update web interface states if they changed
    if new_bike_state != bike_alarm_state:
        bike_alarm_state = new_bike_state
        print(f"Physical bike alarm state changed to: {'ON' if new_bike_state else 'OFF'}")
    
    if new_interior_state != interior_alarm_state:
        interior_alarm_state = new_interior_state
        print(f"Physical interior alarm state changed to: {'ON' if new_interior_state else 'OFF'}")

def cleanup_alarm_system():
    """Clean up alarm system and stop monitoring thread"""
    global alarm_system, alarm_thread, alarm_thread_stop_event
    
    if alarm_thread_stop_event is not None:
        print("Stopping alarm monitoring thread...")
        alarm_thread_stop_event.set()
        
    if alarm_thread is not None and alarm_thread.is_alive():
        alarm_thread.join(timeout=5)  # Wait up to 5 seconds for thread to stop
        if alarm_thread.is_alive():
            print("Warning: Alarm thread did not stop gracefully")
        else:
            print("Alarm monitoring thread stopped")
    
    alarm_system = None
    alarm_thread = None
    alarm_thread_stop_event = None

def set_alarm_via_mqtt(alarm_type, state):
    """Set alarm state by publishing on the shared MQTT bus"""
    try:
        import paho.mqtt.client as mqtt

        if _mqtt_bus is None:
            print("MQTT bus not started; cannot send alarm command")
            return False

        topic = f"rv/alarm/{alarm_type}/command"
        payload = "on" if state else "off"
        result = _mqtt_bus.publish(topic, payload)

        if result.rc == mqtt.MQTT_ERR_SUCCESS:
            print(f"MQTT alarm command sent: {alarm_type} -> {payload}")
            return True
        else:
            print(f"Failed to send MQTT alarm command: {result.rc}")
            return False

    except Exception as e:
        print(f"Error sending MQTT alarm command: {e}")
        return False

def get_alarm_status_via_mqtt():
    """Current alarm status from the retained-status cache on the MQTT bus.

    The alarm container publishes rv/alarm/*/status retained, so the cache
    fills within moments of startup; until then fall back to web state.
    """
    if "bike" in _alarm_status and "interior" in _alarm_status:
        if DEBUG_MODE:
            print(f"MQTT alarm status from cache: {_alarm_status}")
        return {"bike": _alarm_status["bike"], "interior": _alarm_status["interior"]}
    return {"bike": bike_alarm_state, "interior": interior_alarm_state}

def set_alarm(alarm_type, state):
    """Set alarm state - works with direct GPIO, MQTT, or web-only mode"""
    global alarm_system, bike_alarm_state, interior_alarm_state
    
    # Always update the web interface state first
    if alarm_type == "bike":
        bike_alarm_state = state
        if DEBUG_MODE:
            print(f"Web bike alarm {'activated' if state else 'deactivated'}")
    elif alarm_type == "interior":
        interior_alarm_state = state
        if DEBUG_MODE:
            print(f"Web interior alarm {'activated' if state else 'deactivated'}")
    
    if DEBUG_MODE:
        print(f"DEBUG: ALARM_AVAILABLE={ALARM_AVAILABLE}, alarm_system is None: {alarm_system is None}")
    
    # Try to control physical alarm - first try direct GPIO access
    if alarm_system is not None:
        try:
            if alarm_type == "bike":
                if state:
                    alarm_system.set_state(alarm.AlarmTypes.Bike, alarm.States.STARTING)
                    print("Physical bike alarm activated (direct GPIO)")
                else:
                    alarm_system.set_state(alarm.AlarmTypes.Bike, alarm.States.OFF)
                    print("Physical bike alarm deactivated (direct GPIO)")
            elif alarm_type == "interior":
                if state:
                    alarm_system.set_state(alarm.AlarmTypes.Interior, alarm.States.STARTING)
                    print("Physical interior alarm activated (direct GPIO)")
                else:
                    alarm_system.set_state(alarm.AlarmTypes.Interior, alarm.States.OFF)
                    print("Physical interior alarm deactivated (direct GPIO)")
            return
        except Exception as e:
            print(f"Error controlling physical alarm via GPIO: {e}")
    
    # If direct GPIO failed or unavailable, try MQTT communication
    # Try MQTT if alarm_system is None (running in container mode)
    if DEBUG_MODE:
        print(f"DEBUG: Checking MQTT path, alarm_system is None: {alarm_system is None}")
    if alarm_system is None:  # Try MQTT if direct alarm system isn't available
        if DEBUG_MODE:
            print("DEBUG: Attempting MQTT communication...")
        try:
            if set_alarm_via_mqtt(alarm_type, state):
                if DEBUG_MODE:
                    print(f"Physical {alarm_type} alarm {'activated' if state else 'deactivated'} (via MQTT)")
                return
            else:
                if DEBUG_MODE:
                    print(f"Failed to control physical alarm via MQTT")
        except Exception as e:
            print(f"Exception in MQTT communication: {e}")
    
    # Fallback to web-only mode
    if DEBUG_MODE:
        print(f"Physical alarm not available - web state updated only")

class AlarmPostData(BaseModel):
    alarm: str
    state: bool

class ScheduleShutdownData(BaseModel):
    hours: int

@app.post("/api/alarmpost")
async def alarm_endpoint(request: Request,
                         data: Annotated[AlarmPostData, Body()]) -> dict:
    # Disarming needs the PIN; arming does not. The check is here rather than
    # in the middleware because `data.state` has been coerced to a real bool
    # by now -- the raw body could say false, "false", "off" or 0, and all four
    # mean disarm. See the PIN gate note near AUTH_FILE.
    if not data.state:
        require_pin(request)
    if debug > 0:
        print(f"Web alarm request: {data.alarm} State: {data.state}")
    
    # Use our new set_alarm function that handles both web and physical alarms
    set_alarm(data.alarm, data.state)
    
    return {"status": "ok", "alarm": data.alarm, "state": data.state}

@app.get("/api/alarmget")
async def alarms() -> dict:
    global bike_alarm_state, interior_alarm_state, alarm_system
    
    result = {
        "bike": bike_alarm_state, 
        "interior": interior_alarm_state,
        "physical_alarm_available": alarm_system is not None
    }
    
    # Add detailed physical alarm states if available
    if alarm_system is not None:
        result["physical_states"] = {
            "bike": alarm_system.BikeState.name,
            "interior": alarm_system.InteriorState.name
        }
    else:
        # Try to get status via MQTT if direct access not available
        try:
            mqtt_status = get_alarm_status_via_mqtt()
            result["mqtt_status"] = mqtt_status
            result["mqtt_available"] = True
            # Update local state with MQTT status if available
            if mqtt_status:
                result["bike"] = mqtt_status.get("bike", bike_alarm_state)
                result["interior"] = mqtt_status.get("interior", interior_alarm_state)
        except Exception as e:
            print(f"Error getting MQTT alarm status in API: {e}")
            result["mqtt_available"] = False
    
    return result

@app.post("/api/alarm/sync")
async def sync_alarm_states_manual() -> dict:
    """Manually trigger synchronization of physical alarm states with web interface"""
    if alarm_system is not None:
        sync_alarm_states()
        return {
            "status": "synced", 
            "bike": bike_alarm_state, 
            "interior": interior_alarm_state,
            "physical_states": {
                "bike": alarm_system.BikeState.name,
                "interior": alarm_system.InteriorState.name
            }
        }
    else:
        return {"status": "no_physical_alarm", "bike": bike_alarm_state, "interior": interior_alarm_state}

# ---------------------------------------------------------------------------
# WiFi uplink: scan, saved profiles, connect, forget
# ---------------------------------------------------------------------------
# rpzero_wifi_api.py (WifitoHostBridge repo) runs as root and serves JSON on
# port 12346. Scanning REQUIRES root -- unprivileged, nmcli silently ignores
# --rescan and returns only the already-connected AP -- which is why these
# endpoints proxy to that service instead of doing the work here.
#
# WIFI_BRIDGE_HOST says which deployment is live, and that is the only thing
# that changes between them:
#   127.0.0.1   the API on this host, driving the Alfa USB adapter (wlan1).
#               This container is network_mode: host, so loopback reaches it.
#   10.10.0.1   the Pi Zero 2W bridge over the USB link.  Being retired.
#
# These return plain dicts with success/message plus a collection, matching
# GET /api/debug/usb/status.
#
# No caching on this side. The API already caches (status 1s, networks 10s
# with a 10s floor between real rescans, profiles 60s), and that is where the
# cost actually is -- radio time. A second cache here would add a second
# staleness window and a second invalidation path to get wrong.

WIFI_BRIDGE_API_HOST = os.environ.get('WIFI_BRIDGE_HOST', '127.0.0.1')
WIFI_BRIDGE_API_PORT = os.environ.get('WIFI_BRIDGE_API_PORT', '12346')


class WifiBridgeError(Exception):
    """Base for failures talking to the WiFi API."""
    error_code = "bridge_error"


class WifiBridgeUnreachable(WifiBridgeError):
    error_code = "bridge_unreachable"


class WifiBridgeTimeout(WifiBridgeError):
    error_code = "bridge_timeout"


class WifiBridgeBadResponse(WifiBridgeError):
    error_code = "bridge_bad_response"


class WifiBridgeRejected(WifiBridgeError):
    """The Zero answered with an error status and a JSON error body."""
    error_code = "bridge_rejected"

    def __init__(self, message, error_code=None, status=0):
        super().__init__(message)
        self.status = status
        if error_code:
            self.error_code = error_code


# ProxyHandler({}) is not optional: the default opener honours http_proxy /
# HTTP_PROXY from the environment, and this container's env is large and
# growing. An unrelated proxy variable would silently break every call to a
# link-local address.
_wifi_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _wifi_bridge(path, method="GET", payload=None, timeout=10):
    """
    Calls the Zero's WiFi API and returns the decoded JSON.
    Raises a WifiBridgeError subclass for every failure mode.
    """
    url = f"http://{WIFI_BRIDGE_API_HOST}:{WIFI_BRIDGE_API_PORT}{path}"
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with _wifi_opener.open(request, timeout=timeout) as response:
            raw = response.read(65536)
    except urllib.error.HTTPError as exc:
        # HTTPError *is* the response object. Read the Zero's JSON error body
        # before classifying, or its specific message is lost.
        body = {}
        try:
            body = json.loads(exc.read(65536))
        except Exception:
            pass
        raise WifiBridgeRejected(
            body.get("message") or f"the WiFi bridge returned HTTP {exc.code}",
            body.get("error"), exc.code) from exc
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        if isinstance(reason, socket.timeout):
            raise WifiBridgeTimeout(
                f"no answer from the WiFi bridge within {timeout}s") from exc
        hint = ("Is wifi-api-rp5.service running?"
                if WIFI_BRIDGE_API_HOST.startswith("127.")
                else "Is the Zero powered on and is the internet source set to WiFi?")
        raise WifiBridgeUnreachable(
            f"cannot reach the WiFi API at {WIFI_BRIDGE_API_HOST}:"
            f"{WIFI_BRIDGE_API_PORT} ({reason}). {hint}") from exc
    except socket.timeout as exc:
        raise WifiBridgeTimeout(
            f"no answer from the WiFi bridge within {timeout}s") from exc
    try:
        return json.loads(raw)
    except ValueError as exc:
        raise WifiBridgeBadResponse(
            "the WiFi bridge returned a response that was not JSON") from exc


def _wifi_failure(exc, **empties):
    """Failure payload in the shape this file uses: HTTP 200, success False."""
    payload = {"success": False, "error": exc.error_code, "message": str(exc)}
    payload.update(empties)
    return payload


class WifiConnectData(BaseModel):
    ssid: str
    psk: str = ""


class WifiForgetData(BaseModel):
    uuid: str = ""
    ssid: str = ""
    force: bool = False


@app.get("/api/wifi/status")
def get_wifi_status() -> dict:  # Removed async
    """Live state of the Zero's wlan0, plus any connect/forget in progress."""
    try:
        data = _wifi_bridge("/api/status", timeout=4)
    except WifiBridgeError as exc:
        return _wifi_failure(exc, wifi={}, operation={}, service={})
    return {
        "success": True,
        "message": "",
        "wifi": data.get("wifi", {}),
        "operation": data.get("operation", {}),
        "service": data.get("service", {}),
    }


@app.get("/api/wifi/networks")
def get_wifi_networks(rescan: int = 0) -> dict:  # Removed async
    """
    Networks the Zero can see, one entry per SSID, strongest first.
    rescan=1 asks for a fresh scan; the Zero enforces a floor between real
    rescans and reports age_seconds so staleness is visible.
    """
    try:
        data = _wifi_bridge(f"/api/networks?rescan={1 if rescan else 0}",
                            timeout=30 if rescan else 10)
    except WifiBridgeError as exc:
        return _wifi_failure(exc, networks=[])
    return {
        "success": True,
        "message": "",
        "networks": data.get("networks", []),
        "age_seconds": data.get("age_seconds"),
        "rescanned": data.get("rescanned", False),
        "self_ap_ssid": data.get("self_ap_ssid", ""),
    }


@app.get("/api/wifi/profiles")
def get_wifi_profiles() -> dict:  # Removed async
    """
    Saved WiFi profiles on the Zero, newest-used first.

    Profile name is neither the SSID nor unique, so each entry carries both
    plus its UUID; has_psk says whether a password is stored, and no endpoint
    ever returns the password itself.
    """
    try:
        data = _wifi_bridge("/api/profiles", timeout=10)
    except WifiBridgeError as exc:
        return _wifi_failure(exc, profiles=[])
    return {
        "success": True,
        "message": "",
        "profiles": data.get("profiles", []),
        "age_seconds": data.get("age_seconds"),
    }


@app.post("/api/wifi/connect")
def connect_wifi(data: Annotated[WifiConnectData, Body()]) -> dict:  # Removed async
    """
    Joins an SSID. Omit psk to use the saved credential; supply one to set or
    replace it. Returns as soon as the Zero accepts the job -- follow progress
    on /api/wifi/status, where operation.state goes running -> succeeded|failed.
    """
    payload = {"ssid": data.ssid}
    if data.psk:
        payload["psk"] = data.psk
    try:
        result = _wifi_bridge("/api/connect", method="POST", payload=payload,
                              timeout=10)
    except WifiBridgeError as exc:
        return _wifi_failure(exc)
    return {
        "success": True,
        "message": f"Connecting to {data.ssid}",
        "job_id": result.get("job_id", ""),
        "ssid": result.get("ssid", data.ssid),
    }


@app.post("/api/wifi/forget")
def forget_wifi(data: Annotated[WifiForgetData, Body()]) -> dict:  # Removed async
    """
    Deletes saved profiles. By SSID it deletes every profile for that network,
    which is what "forget" has to mean: the API stores a 5 GHz-locked profile
    plus an unlocked fallback, and leaving one behind would let it reconnect.
    Pass uuid to delete exactly one. force=True is required when one of them is
    currently providing the connection.
    """
    payload = {"force": data.force}
    if data.uuid:
        payload["uuid"] = data.uuid
    if data.ssid:
        payload["ssid"] = data.ssid
    if not data.uuid and not data.ssid:
        return {"success": False, "error": "invalid_request",
                "message": "a uuid or ssid is required"}
    try:
        result = _wifi_bridge("/api/forget", method="POST", payload=payload,
                              timeout=10)
    except WifiBridgeError as exc:
        return _wifi_failure(exc)
    deleted = result.get("deleted", {})
    return {
        "success": True,
        "message": f"Forgot {deleted.get('name') or data.uuid or data.ssid}",
        "deleted": deleted,
    }


# ---------------------------------------------------------------------------
# USB hub port power (the Plugable), proxied to usbhub-api.service
#
# Why a proxy and not direct control: a plain powered hub
# has no control chip, so port power goes through the kernel -- and this
# container's /sys/devices is mounted read-only, so writing a port attribute
# fails with EACCES even though the container is privileged and uid 0 (verified
# 2026-10-18).
#
# Two levels, deliberately:
#   /api/hub/sockets, /api/hub/socket     independent per-socket control, any
#                                         number on at once -- for the debug page
#   /api/hub/socket/exclusive             powers exactly one socket, the others
#                                         off first -- for the Internet page
#
# A "socket" is a physical socket on the hub's shell, which is not a port
# number: a USB 3 hub is two hub chips, so a socket has a USB 2 identity and a
# USB 3 identity on different buses, and a device appears under only the one
# matching its own speed. The root service owns that mapping
# (/etc/usbhub/sockets.json, built by map_sockets.py) and switches every
# identity. See rv/usbhub/README.md.
#
# No caching here. The root service already caches the expensive part -- reading
# a port's state is a USB control transfer that wakes a suspended hub, 75-220 ms
# per port -- and a second cache would add a second staleness window.

USBHUB_API_HOST = os.environ.get('USBHUB_API_HOST', '127.0.0.1')
USBHUB_API_PORT = os.environ.get('USBHUB_API_PORT', '12347')


class UsbHubError(Exception):
    """Base for failures talking to the USB hub API."""
    error_code = "usbhub_error"

    def __init__(self, message, error_code=None, status=None):
        super().__init__(message)
        self.status = status
        if error_code:
            self.error_code = error_code


class UsbHubUnreachable(UsbHubError):
    error_code = "usbhub_unreachable"


class UsbHubTimeout(UsbHubError):
    error_code = "usbhub_timeout"


class UsbHubBadResponse(UsbHubError):
    error_code = "usbhub_bad_response"


class UsbHubRejected(UsbHubError):
    """The service answered with an error status and a JSON error body --
    a protected port, an unknown socket, or no socket map."""
    error_code = "usbhub_rejected"


# Same reason as _wifi_opener: the default opener honours http_proxy from the
# environment, and an unrelated proxy variable would break calls to loopback.
_usbhub_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _usbhub_api(path, method="GET", payload=None, timeout=15):
    """Calls usbhub-api.service and returns the decoded JSON."""
    url = f"http://{USBHUB_API_HOST}:{USBHUB_API_PORT}{path}"
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with _usbhub_opener.open(request, timeout=timeout) as response:
            raw = response.read(262144)
    except urllib.error.HTTPError as exc:
        # HTTPError is the response. Read the service's JSON body before
        # classifying, or its specific message -- which port is protected, which
        # socket is unknown -- is lost.
        body = {}
        try:
            body = json.loads(exc.read(65536))
        except Exception:
            pass
        raise UsbHubRejected(
            body.get("message") or f"the USB hub API returned HTTP {exc.code}",
            body.get("error"), exc.code) from exc
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        if isinstance(reason, socket.timeout):
            raise UsbHubTimeout(
                f"no answer from the USB hub API within {timeout}s") from exc
        raise UsbHubUnreachable(
            f"cannot reach the USB hub API at {USBHUB_API_HOST}:"
            f"{USBHUB_API_PORT} ({reason}). Is usbhub-api.service running?"
        ) from exc
    except socket.timeout as exc:
        raise UsbHubTimeout(
            f"no answer from the USB hub API within {timeout}s") from exc
    try:
        return json.loads(raw)
    except ValueError as exc:
        raise UsbHubBadResponse(
            "the USB hub API returned a response that was not JSON") from exc


def _usbhub_failure(exc, **empties):
    """Failure payload in the shape this file uses: HTTP 200, success False."""
    payload = {"success": False, "error": exc.error_code, "message": str(exc)}
    payload.update(empties)
    return payload


class HubSocketData(BaseModel):
    socket: str
    on: bool


class HubExclusiveData(BaseModel):
    # None means "leave every socket off", which the service accepts and which
    # the Internet page needs for an explicit no-uplink state.
    socket: Optional[str] = None


@app.get("/api/hub/sockets")
def get_hub_sockets() -> dict:
    """
    Every physical socket on the Plugable, its power state and what is in it.

    configured=False with an empty sockets dict is a normal state, not an
    error: it means no socket map has been built yet. The UI should say so
    rather than render an empty hub, because a map is the only thing that
    relates a socket to a port.
    """
    try:
        data = _usbhub_api("/api/sockets", timeout=10)
    except UsbHubError as exc:
        return _usbhub_failure(exc, configured=False, sockets={}, wan={})
    return {
        "success": True,
        "message": "" if data.get("configured") else
                   "No socket map yet -- run rv/usbhub/map_sockets.py",
        "configured": bool(data.get("configured")),
        "sockets": data.get("sockets", {}),
        "wan": data.get("wan", {}),
        "protected": data.get("protected", []),
        "map_path": data.get("map_path", ""),
    }


@app.post("/api/hub/socket")
def set_hub_socket(data: Annotated[HubSocketData, Body()]) -> dict:
    """
    One socket on or off, the others untouched. Several may be on at once --
    that is the point of this endpoint, and what the debug page needs.

    The timeout is generous because a write is slow: each identity is a USB
    control transfer, and a suspended hub is woken first.
    """
    try:
        result = _usbhub_api("/api/socket", method="POST",
                             payload={"socket": data.socket, "on": data.on},
                             timeout=30)
    except UsbHubError as exc:
        return _usbhub_failure(exc, sockets={})
    return {
        "success": True,
        "message": f"Socket {data.socket} turned {'on' if data.on else 'off'}",
        "socket": result.get("socket", {}),
        "sockets": result.get("sockets", {}),
    }


@app.post("/api/hub/socket/exclusive")
def set_hub_socket_exclusive(data: Annotated[HubExclusiveData, Body()]) -> dict:
    """
    Power exactly one socket, or none at all.

    The others are switched off BEFORE the target comes on, so the hub is never
    briefly feeding two uplinks. This is the RV's normal policy: several WAN
    options may be considered, only one is left drawing current.
    """
    try:
        result = _usbhub_api("/api/socket/exclusive", method="POST",
                             payload={"socket": data.socket}, timeout=60)
    except UsbHubError as exc:
        return _usbhub_failure(exc, sockets={})
    return {
        "success": True,
        "message": (f"Socket {data.socket} is now the only one powered"
                    if data.socket else "All sockets off"),
        "changed": result.get("changed", {}),
        "sockets": result.get("sockets", {}),
    }


class HubWanData(BaseModel):
    # None powers nothing, which the Internet page needs for an explicit
    # no-uplink state.
    role: Optional[str] = None


@app.get("/api/hub/wan")
def get_hub_wan() -> dict:
    """
    WAN candidates on the Plugable: one entry per socket that has a role.

    Role rather than socket number is the right key for the Internet page --
    the user picks "starlink", not "socket 4" -- and it is the mapping the RV
    actually cares about. Sockets without a role are not uplinks and do not
    appear here at all; that is also what keeps an exclusive switch from
    cutting the Bluetooth adapter sharing the hub.
    """
    try:
        data = _usbhub_api("/api/sockets", timeout=10)
    except UsbHubError as exc:
        return _usbhub_failure(exc, configured=False, candidates=[], active=None)

    candidates, active = [], None
    for label, sock in (data.get("sockets") or {}).items():
        role = sock.get("wan")
        if not role:
            continue
        entry = {
            "role": role,
            "socket": label,
            # The map's cosmetic label, if it has one. Separate from the role
            # on purpose: a socket can be named without joining the exclusive
            # WAN group (see SocketMap.names).
            "name": sock.get("name", ""),
            # Gated roles are powered only while active, so the UI can explain
            # why one shows as unpowered rather than looking broken.
            "gated": bool(sock.get("gated")),
            "powered": bool(sock.get("enabled")),
            # present=False with powered=True means the socket is live but
            # nothing is plugged into it. Worth surfacing: it is the difference
            # between "this uplink is off" and "this uplink is not installed".
            "present": bool(sock.get("device_present")),
            "product": sock.get("product", ""),
            "max_power": sock.get("max_power", ""),
        }
        candidates.append(entry)
    candidates.sort(key=lambda c: (not c["socket"].isdigit(), c["socket"].zfill(4)))

    # "active" means the hub has SELECTED one uplink. powered and present is
    # necessary but not sufficient: until something calls /api/hub/wan or
    # /api/socket/exclusive, every socket is powered and several roles qualify
    # at once. An earlier version assigned active inside the loop, so the last
    # qualifying role won -- it reported "cell" on 2026-10-19 while the default
    # route was on wired. No selection is a real state; report it as one.
    live = [c["role"] for c in candidates if c["powered"] and c["present"]]
    active = live[0] if len(live) == 1 else None

    if not data.get("configured"):
        message = "No socket map yet -- run rv/usbhub/map_sockets.py"
    elif len(live) > 1:
        message = (f"{len(live)} uplinks are powered at once ({', '.join(live)}); "
                   "none has been selected. Pick one to apply exclusivity.")
    elif not live:
        message = "No roled socket has a device both powered and plugged in."
    else:
        message = ""

    return {
        "success": True,
        "message": message,
        "configured": bool(data.get("configured")),
        "candidates": candidates,
        # Which uplink the hub has selected, or null when it has not. This is
        # about socket POWER, never the default route -- pi5connect.sh owns
        # that and keeps a healthy incumbent, so a powered socket is an offer,
        # not a takeover.
        "active": active,
        "powered_present": live,
    }


@app.post("/api/hub/wan/scan")
def scan_hub_wan() -> dict:
    """
    Look for a better uplink, powering sockets only while testing them.

    This exists because powering one WAN at a time and preferring a better
    uplink are in tension: pi5connect only reconsiders the WAN when
    NetworkManager raises an interface event, and an unpowered socket has no
    interface and raises nothing. Rather than burn standby power keeping every
    adapter enumerated just to notice, the scan is on demand.

    Runs rv/raspap/wan_scan.sh detached via systemd-run, because a scan can
    briefly change the default route and must not die with this request. The
    result lands in /run/wan-scan-result and the progress log in
    /var/log/wan-scan.log; poll GET /api/hub/wan to see where it ended up.

    Measured cost: a cold cellular candidate takes ~60s to test (17s to
    enumerate, 22s to a netdev, 52s to a DHCP lease). Wired and WiFi are far
    cheaper. Carrier is checked before DHCP so an unplugged cable or a
    powered-off Starlink dish is rejected in ~10s.
    """
    script = "/usr/local/sbin/wan_scan.sh"
    # nsenter into the host namespaces, the same way /api/system/reboot does.
    # The scan has to run on the HOST: it drives sysfs USB power and calls
    # pi5connect, and systemd-run inside the container cannot reach the host's
    # systemd. Requires pid: host + privileged: true, which this service has.
    # systemd-run detaches it, so a scan that outlives this request -- a cold
    # cellular test takes ~60s -- is not killed when the HTTP call returns.
    try:
        # --on-loss when there is no default route at all: then every role is
        # worth trying, not just ones better than a WAN we do not have.
        mode = [] if default_route_interface() else ["--on-loss"]
        result = subprocess.run(
            ["nsenter", "-t", "1", "-m", "-u", "-i", "-n", "--",
             "systemd-run", "--unit=wan-scan-ondemand", "--collect",
             "--service-type=oneshot", "/bin/bash", script, *mode],
            capture_output=True, text=True, timeout=20)
        if result.returncode != 0:
            detail = (result.stderr or "").strip()
            # A unit of that name already existing is the common case: a scan
            # is already in flight, which is not an error worth alarming about.
            if "already exists" in detail or "already running" in detail:
                return {"success": True, "started": False,
                        "message": "A scan is already running."}
            return {"success": False, "error": "launch_failed",
                    "message": detail or f"rc={result.returncode}"}
    except Exception as exc:
        return {"success": False, "error": "launch_failed", "message": str(exc)}
    return {"success": True, "started": True,
            "message": "Scanning for a better uplink. This can take a minute "
                       "if the cellular modem has to be powered up and tested."}


@app.get("/api/hub/wan/scan")
def get_hub_wan_scan() -> dict:
    """Last scan outcome, and whether one is running now."""
    running = False
    try:
        probe = subprocess.run(
            ["nsenter", "-t", "1", "-m", "-u", "-i", "-n", "--",
             "systemctl", "is-active", "wan-scan-ondemand"],
            capture_output=True, text=True, timeout=8)
        running = probe.stdout.strip() == "active"
    except Exception:
        pass
    outcome, iface, socket_label, when = "", "", "", 0
    try:
        # The container has its own /run, so read the host's copy.
        got = subprocess.run(
            ["nsenter", "-t", "1", "-m", "-u", "-i", "-n", "--",
             "cat", "/run/wan-scan-result"],
            capture_output=True, text=True, timeout=8)
        parts = got.stdout.split()
        if len(parts) >= 4:
            outcome, iface, socket_label = parts[0], parts[1], parts[2]
            when = int(parts[3])
    except Exception:
        pass
    return {"success": True, "running": running, "outcome": outcome,
            "interface": iface, "socket": socket_label, "finished": when}


@app.post("/api/hub/wan")
def set_hub_wan(data: Annotated[HubWanData, Body()]) -> dict:
    """
    Power exactly the WAN source named by role, or none at all.

    This is the "consider several, power one" policy: the others go off before
    this one comes on, so the hub never briefly feeds two uplinks, and only WAN
    sockets are touched.

    This does NOT change the default route. pi5connect.sh does that on the
    interface event that follows, and it keeps a healthy incumbent rather than
    being preempted -- so powering a socket offers an uplink, it does not seize
    the route.
    """
    try:
        current = _usbhub_api("/api/sockets", timeout=10)
    except UsbHubError as exc:
        return _usbhub_failure(exc, sockets={})

    target = None
    if data.role:
        for label, sock in (current.get("sockets") or {}).items():
            if sock.get("wan") == data.role:
                target = label
                break
        if target is None:
            return {"success": False, "error": "no_such_role",
                    "message": f"no socket has the WAN role {data.role!r}; "
                               "assign one with map_sockets.py --set-role",
                    "sockets": {}}
    try:
        result = _usbhub_api("/api/socket/exclusive", method="POST",
                             payload={"socket": target}, timeout=60)
    except UsbHubError as exc:
        return _usbhub_failure(exc, sockets={})
    return {
        "success": True,
        "message": (f"{data.role} (socket {target}) is now the only WAN powered"
                    if target else "All WAN sockets off"),
        "role": data.role,
        "socket": target,
        "changed": result.get("changed", {}),
        "sockets": result.get("sockets", {}),
    }


@app.get("/api/hub/hubs")
def get_hub_raw() -> dict:
    """
    The raw USB tree: every hub, its ports, what is attached, and whether it
    claims per-port power switching. Diagnostic -- the socket view above is
    what callers should normally use.
    """
    try:
        data = _usbhub_api("/api/hubs", timeout=20)
    except UsbHubError as exc:
        return _usbhub_failure(exc, hubs=[])
    return {
        "success": True,
        "message": "",
        "hubs": data.get("hubs", []),
        "uhubctl_note": data.get("uhubctl_note", ""),
    }


# Internet Control Models and Endpoints

USB_HUB_PORT_DELAY_CONNECTION_SETTLE = 2.0  # Fallback settle delay before connectivity testing

# Connection-Type-Specific Settling Delays for Testing (seconds)
# Additional time to wait before connectivity testing after initialization
CONNECTION_SETTLE_DELAYS = {
    'cellular': 8.0,    # Extra time for cellular network registration
    'wifi': 5.0,        # Extra time for WiFi association and DHCP
    'starlink': 15.0,   # Extra time for Starlink satellite acquisition
    'wired': 2.0        # Minimal extra time for ethernet link negotiation
}

def get_connection_settle_delay(connection_type):
    """Get the settling delay for a specific connection type."""
    return CONNECTION_SETTLE_DELAYS.get(connection_type, USB_HUB_PORT_DELAY_CONNECTION_SETTLE)

def read_kasa_feature_outlets():
    """Read the amp (outlet 1) and Starlink (outlet 6) Kasa states in one query.
    Returns (amp_on, starlink_on), or None if the power strip can't be read."""
    try:
        kasa_strip = get_kasa_power_strip()
        if not kasa_strip:
            return None
        outlets = kasa_strip.get_all_outlet_status()
        if len(outlets) < 6:
            return None
        return outlets[0]['is_on'], outlets[5]['is_on']
    except Exception as e:
        print(f"WARNING: Could not read Kasa outlet state: {e}")
        clear_kasa_cache()
        return None

def _normalise_wan_role(label):
    """Map a socket map role/name onto the connection names the UI uses."""
    label = (label or "").strip().lower()
    return {"cell": "cellular", "cellular": "cellular", "lte": "cellular",
            "wired": "wired", "ethernet": "wired",
            "wifi": "wifi", "wlan": "wifi",
            "starlink": "starlink"}.get(label, "")


def _wan_role_of_interface(iface):
    """
    Which of the five uplinks carries this interface: wired, wifi, starlink or
    cellular. Resolved through the hub socket the interface's USB device is
    plugged into (the socket map is the source of truth, because interface
    names drift), the same way pi5connect.sh does it. An interface that is not
    on the hub falls back to its shape: a wlan* device is the WiFi adapter.
    Returns "" when it cannot be classified.
    """
    if not iface:
        return ""
    try:
        devdir = os.path.realpath(f"/sys/class/net/{iface}/device")
        usb_id = os.path.basename(devdir).split(":")[0]       # 1-2.3.2
        if "." in usb_id:
            hub, port = usb_id.rsplit(".", 1)                 # 1-2.3 / 2
            sockets = _usbhub_api("/api/sockets", timeout=10).get("sockets") or {}
            for sock in sockets.values():
                for ident in sock.get("identities") or []:
                    if ident.get("hub") == hub and str(ident.get("port")) == port:
                        role = (_normalise_wan_role(sock.get("wan"))
                                or _normalise_wan_role(sock.get("name")))
                        if role:
                            return role
    except Exception as e:
        print(f"WARNING: Could not resolve the uplink role of {iface}: {e}")
    return "wifi" if iface.startswith("wlan") else ""


def detect_current_internet_connection():
    """
    Which of the five uplinks the RV is actually routing over:
    wired, wifi, starlink, cellular, or cellular-amp.

    The role comes from the default route's interface (see
    _wan_role_of_interface). The Kasa strip cannot say whether wired or WiFi is
    in use; it only matters for cellular, where the amplifier outlet (outlet 1)
    being on makes it cellular-amp. Starlink needs its own Kasa supply but that
    is a precondition of the uplink, not what identifies it.
    "none" means no default route. If the role cannot be determined the last
    known value is kept. Updates the global current_internet_connection.
    """
    global current_internet_connection

    wan_interface = default_route_interface()
    if not wan_interface:
        detected = "none"
    else:
        detected = _wan_role_of_interface(wan_interface) or None
        if detected == "cellular":
            kasa = read_kasa_feature_outlets()
            amp_on = kasa[0] if kasa else (current_internet_connection == "cellular-amp")
            if amp_on:
                detected = "cellular-amp"

    if detected is None:
        print(f"WARNING: Could not classify the uplink on {wan_interface}, "
              f"keeping last known: {current_internet_connection}")
    else:
        current_internet_connection = detected
        _save_internet_state(detected)
        print(f"INFO: Detected internet connection: {detected} (default route via {wan_interface or 'none'})")

    return current_internet_connection

class InternetTestData(BaseModel):
    connection_type: str  # 'cellular', 'wifi', 'starlink', 'wired'

class InternetResponse(BaseModel):
    success: bool
    message: str
    port: int = None
    connected: bool = None

# Global Kasa connection cache to prevent repeated discovery
_kasa_strip_cache = None
_kasa_cache_time = 0
_kasa_cache_duration = 300  # Cache for 5 minutes
_kasa_last_failure_time = 0
_kasa_failure_cache_duration = 15  # Reduced to 15 seconds for faster recovery when device comes back online

def get_kasa_power_strip():
    """Get Kasa Power Strip Controller instance. Returns None if not available."""
    import os
    import time
    
    global _kasa_strip_cache, _kasa_cache_time, _kasa_last_failure_time
    
    # Check if Kasa is disabled via environment variable
    if os.getenv('DISABLE_KASA', '').lower() in ('true', '1', 'yes'):
        print("INFO: Kasa power strip disabled via DISABLE_KASA environment variable")
        return None
    
    current_time = time.time()
    
    # Check if we recently had a failure and should avoid retrying
    if (_kasa_last_failure_time > 0 and 
        (current_time - _kasa_last_failure_time) < _kasa_failure_cache_duration):
        # Recent failure, don't retry yet
        return None
    
    # Check cache validity for successful connections
    if (_kasa_strip_cache is not None and 
        (current_time - _kasa_cache_time) < _kasa_cache_duration):
        # Cache is still valid, return cached instance
        return _kasa_strip_cache
    
    # Cache is invalid or doesn't exist, try to create new connection
    try:
        print("INFO: Attempting to create new Kasa power strip connection...")
        
        # Get Kasa host from constants
        kasa_host = constants.get("KASA_IP", "10.0.0.188")
        
        # Try to create and connect to Kasa power strip with balanced timeout
        kasa_strip = KasaPowerStrip(host=kasa_host, timeout=8)  # Use host from constants
        if kasa_strip.connect():
            print("INFO: Kasa power strip connected successfully")
            _kasa_strip_cache = kasa_strip
            _kasa_cache_time = current_time
            _kasa_last_failure_time = 0  # Reset failure time on success
            return kasa_strip
        else:
            print("WARNING: No Kasa power strip found or connection failed")
            print("INFO: Set DISABLE_KASA=true environment variable to disable Kasa functionality")
            # Cache the failure to avoid immediate retries
            _kasa_strip_cache = None
            _kasa_last_failure_time = current_time
            return None
    except Exception as e:
        print(f"WARNING: Kasa power strip controller not available: {e}")
        print("INFO: Set DISABLE_KASA=true environment variable to disable Kasa functionality")
        # Cache the failure to avoid immediate retries
        _kasa_strip_cache = None
        _kasa_last_failure_time = current_time
        return None

def clear_kasa_cache():
    """Clear the Kasa connection cache - useful for testing or after errors."""
    global _kasa_strip_cache, _kasa_cache_time
    _kasa_strip_cache = None
    _kasa_cache_time = 0
    print("INFO: Kasa connection cache cleared")

def test_internet_connectivity(connection_type="generic", timeout=5):
    """Test internet connectivity using multiple methods for Docker compatibility."""
    test_results = {
        'connected': False,
        'message': 'Testing...'
    }
    
    # Method 1: Try ping command (works on host, may fail in Docker)
    try:
        result = subprocess.run(
            ['ping', '-c', '1', '-W', str(timeout), '8.8.8.8'],
            capture_output=True,
            text=True,
            timeout=timeout + 2
        )
        
        if result.returncode == 0:
            test_results['connected'] = True
            test_results['message'] = f'Internet connectivity verified via {connection_type} (ping)'
            return test_results
        else:
            # Ping failed, but don't return yet - try other methods
            ping_error = result.stderr.strip() if result.stderr else "ping failed"
            
    except subprocess.TimeoutExpired:
        ping_error = "ping timed out"
    except Exception as e:
        ping_error = f"ping error: {str(e)}"
    
    # Method 2: Try curl as fallback (better for Docker)
    try:
        result = subprocess.run(
            ['curl', '--connect-timeout', str(timeout), '--max-time', str(timeout), 
             '-s', '-o', '/dev/null', '-w', '%{http_code}', 'http://8.8.8.8'],
            capture_output=True,
            text=True,
            timeout=timeout + 2
        )
        
        if result.returncode == 0:
            # Any HTTP response (even error codes) indicates connectivity
            test_results['connected'] = True
            test_results['message'] = f'Internet connectivity verified via {connection_type} (http)'
            return test_results
        else:
            curl_error = result.stderr.strip() if result.stderr else "http test failed"
            
    except subprocess.TimeoutExpired:
        curl_error = "http test timed out"
    except Exception as e:
        curl_error = f"http test error: {str(e)}"
    
    # Method 3: Try Python socket connection as final fallback
    try:
        import socket
        sock = socket.create_connection(("8.8.8.8", 53), timeout=timeout)
        sock.close()
        test_results['connected'] = True
        test_results['message'] = f'Internet connectivity verified via {connection_type} (socket)'
        return test_results
    except Exception as socket_error:
        socket_error_msg = str(socket_error)
    
    # All methods failed
    test_results['connected'] = False
    test_results['message'] = f'No internet connectivity detected via {connection_type} (ping: {ping_error}, http: {curl_error}, socket: {socket_error_msg})'
    
    return test_results

@app.get("/api/kasa/power/{outlet_id}")
def get_kasa_power(outlet_id: int) -> dict:  # Removed async
    """Get power consumption from a specific Kasa outlet using simple blocking calls."""
    try:
        kasa_strip = get_kasa_power_strip()
        if not kasa_strip:
            return {"success": False, "power": 0, "message": "Kasa power strip not available"}
        
        # Convert to 0-based indexing for the Kasa controller
        power_data = kasa_strip.get_power_consumption(outlet_id - 1)
        
        # Check if there was an error in the power data
        if 'error' in power_data:
            print(f"Kasa power reading error for port {outlet_id}: {power_data['error']}")
            clear_kasa_cache()  # Clear cache on error
            return {"success": False, "power": 0, "message": power_data['error']}
        
        # Extract power value in watts
        power_watts = power_data.get('power_w', 0)
        
        return {
            "success": True, 
            "power": round(power_watts, 1),
            "message": f"Power reading from Kasa port {outlet_id}: {power_watts}W"
        }
            
    except Exception as e:
        print(f"ERROR: Failed to get Kasa power for outlet {outlet_id}: {e}")
        clear_kasa_cache()  # Clear cache on error
        return {"success": False, "power": 0, "message": f"Kasa error: {str(e)}"}

# Keys ("alias|kind|since") of watcher alerts the user has acknowledged. Kept
# server-side so every browser agrees; "since" makes a recurrence a new key.
acknowledged_alert_keys: set = set()

@app.get("/api/alerts/ack")
def get_acknowledged_alerts() -> dict:
    return {"keys": sorted(acknowledged_alert_keys)}

@app.post("/api/alerts/ack")
def acknowledge_alerts(data: Annotated[dict, Body()]) -> dict:
    """Replace the acknowledged set with the keys of the currently active alerts."""
    global acknowledged_alert_keys
    keys = data.get("keys", [])
    if not isinstance(keys, list) or not all(isinstance(k, str) for k in keys):
        return {"success": False, "message": "keys must be a list of strings"}
    acknowledged_alert_keys = set(keys)
    return {"success": True, "keys": sorted(acknowledged_alert_keys)}

def default_route_interface():
    """The interface carrying the default route, or "" if there is none.

    Read from /proc/net/route rather than /run/pi5connect-wan, which is not
    mounted into this container. The webserver runs with network_mode: host,
    so /proc/net/route is the host's routing table.
    """
    try:
        with open("/proc/net/route") as handle:
            next(handle, None)                      # header
            for line in handle:
                fields = line.split()
                # destination 00000000 == the default route
                if len(fields) > 1 and fields[1] == "00000000":
                    return fields[0]
    except (OSError, StopIteration):
        pass
    return ""


@app.get("/api/internet/status")
def get_internet_status() -> dict:  # Removed async
    """Get current internet connection status."""
    global current_internet_connection

    try:
        detected_connection = detect_current_internet_connection()
        wan_interface = default_route_interface()
        manual = read_manual_choice()

        return {
            "current_connection": detected_connection,
            # Whether the RV has internet is the real default route, not which
            # hub socket is powered.
            "status": "connected" if wan_interface else "disconnected",
            "wan_interface": wan_interface,
            "message": (f"WAN via {wan_interface}" if wan_interface
                        else "No default route"),
            # The deliberate choice, if one is still in force, and the reason
            # the system is not on it when failover could not honour it. Both
            # are what stop the page showing the wrong option as active
            # without explaining itself.
            "manual_choice": manual["choice"],
            "manual_fallback": manual["fallback"],
        }
    except Exception as e:
        print(f"Error getting internet status: {e}")
        return {
            "current_connection": "unknown",
            "status": "error", 
            "message": f"Error detecting connection: {str(e)}"
        }

# The Internet page's selector. One entry per thing the user can pick, naming
# the hub WAN role to power and the Kasa outlets that option needs energised.
# Feature outlets NOT named by the chosen option are switched off: leaving the
# Starlink supply (tens of watts) on while running on wired was the largest
# silent waste on the page, and with the old "Powered Accessories" card gone
# there is nothing else to turn it off.
#
# "wifi" has no hub role on purpose. The Alfa sits in socket 1, outside the
# exclusive WAN group, so choosing WiFi powers the switched uplinks down and
# leaves the adapter up. That is deliberate: it is what keeps the network
# picker usable whatever uplink is live, and gating the picker behind a WAN
# selection was tried once and reverted (see Internet.jsx).
#
# "none" is therefore not quite "no internet": it drops the switched uplinks
# and the accessories, but the WiFi adapter stays powered and NetworkManager
# may reassociate on its own. Said plainly in the UI rather than papered over.
KASA_AMP_OUTLET = 1
KASA_STARLINK_OUTLET = 6
KASA_FEATURE_OUTLETS = (KASA_AMP_OUTLET, KASA_STARLINK_OUTLET)

# "manual" is the role recorded in /run/wan-manual-choice so pi5connect and
# wan_scan honour the choice. It is NOT the same as "role": WiFi has no hub
# role (socket 1 is outside the exclusive group) but is very much a uplink to
# be honoured, and both cellular options map to the one cellular role.
INTERNET_OPTIONS = {
    "wired":    {"role": "wired",    "outlets_on": (),                       "state": "wired",         "manual": "wired"},
    "wifi":     {"role": None,       "outlets_on": (),                       "state": "wifi",          "manual": "wifi"},
    "cell":     {"role": "cell",     "outlets_on": (),                       "state": "cellular",      "manual": "cellular"},
    "cell-amp": {"role": "cell",     "outlets_on": (KASA_AMP_OUTLET,),       "state": "cellular-amp",  "manual": "cellular"},
    "starlink": {"role": "starlink", "outlets_on": (KASA_STARLINK_OUTLET,),  "state": "starlink",      "manual": "starlink"},
    "none":     {"role": None,       "outlets_on": (),                       "state": "none",          "manual": None},
}

# Where the deliberate choice lives. These are on the HOST's /run, which this
# container does not share -- only /run/dbus is bind-mounted -- so every access
# goes through the init process's mount namespace, the same route
# /api/system/reboot and the firewall reads already take.
MANUAL_CHOICE_FILE = "/run/wan-manual-choice"
MANUAL_FALLBACK_FILE = "/run/wan-manual-fallback"


def _host_write(path: str, text: str):
    """Write a small file in the host's namespace. Returns (ok, detail)."""
    try:
        proc = subprocess.run(["nsenter", "-t", "1", "-m", "--", "tee", path],
                              input=text, capture_output=True, text=True,
                              timeout=10)
        return proc.returncode == 0, proc.stderr.strip()
    except Exception as exc:
        return False, str(exc)


def _host_remove(path: str):
    try:
        proc = subprocess.run(["nsenter", "-t", "1", "-m", "--", "rm", "-f", path],
                              capture_output=True, text=True, timeout=10)
        return proc.returncode == 0, proc.stderr.strip()
    except Exception as exc:
        return False, str(exc)


def read_manual_choice():
    """
    The deliberate uplink choice and any recorded fallback, as the UI needs
    them. One nsenter for both, since this is read on every status poll.

    Shapes: choice is "<role> <epoch>"; fallback is "<wanted> <got> <epoch>",
    written by wan_scan.sh when a choice could not be honoured.
    """
    blank = {"choice": None, "fallback": None}
    try:
        proc = subprocess.run(
            # "|| true" on both: an absent file is the normal case, and
            # without it cat's exit status becomes the shell's, so a missing
            # fallback file made this report "no choice" even when one was
            # recorded. Caught 2026-10-26 by the plumbing test.
            ["nsenter", "-t", "1", "-m", "--", "sh", "-c",
             f"cat {MANUAL_CHOICE_FILE} 2>/dev/null || true; echo '|'; "
             f"cat {MANUAL_FALLBACK_FILE} 2>/dev/null || true"],
            capture_output=True, text=True, timeout=10)
        if proc.returncode != 0:
            return blank
        choice_raw, _, fallback_raw = proc.stdout.partition("|")
    except Exception as exc:
        print(f"WARNING: could not read the manual uplink choice: {exc}")
        return blank

    now = time.time()
    result = dict(blank)
    parts = choice_raw.split()
    if len(parts) >= 2:
        try:
            result["choice"] = {"role": parts[0],
                                "age_seconds": round(now - float(parts[1]), 1)}
        except ValueError:
            pass
    parts = fallback_raw.split()
    if len(parts) >= 3:
        try:
            result["fallback"] = {"wanted": parts[0], "got": parts[1],
                                  "age_seconds": round(now - float(parts[2]), 1)}
        except ValueError:
            pass
    return result


class InternetSelectData(BaseModel):
    option: str


def _switch_kasa_outlet(outlet, on):
    """Switch one Kasa outlet. Returns (ok, detail); never raises."""
    try:
        strip = get_kasa_power_strip()
        if not strip:
            return False, f"outlet {outlet}: power strip unavailable"
        if on:
            strip.turn_on_outlet(outlet - 1)
        else:
            strip.turn_off_outlet(outlet - 1)
        return True, ""
    except Exception as exc:
        clear_kasa_cache()
        return False, f"outlet {outlet}: {exc}"


@app.post("/api/internet/select")
def select_internet_option(data: Annotated[InternetSelectData, Body()]) -> dict:
    """
    Apply one choice from the Internet page: power the right hub socket AND the
    mains the option needs, in that one call.

    Ordering is not cosmetic. Outlets an option NEEDS come on before the socket
    switch, so the device has mains by the time its USB adapter enumerates --
    Starlink in particular comes up on its own supply, not off USB. Outlets the
    option does NOT need go off only AFTER the switch, so this never cuts power
    to the uplink it is in the middle of selecting.

    Like /api/hub/wan, this does NOT seize the default route: pi5connect.sh
    decides that on the interface event which follows. Powering an uplink
    offers it.
    """
    global current_internet_connection

    spec = INTERNET_OPTIONS.get((data.option or "").strip().lower())
    if spec is None:
        return {"success": False, "error": "no_such_option",
                "message": f"unknown option {data.option!r}; expected one of "
                           + ", ".join(sorted(INTERNET_OPTIONS))}

    warnings = []

    # 1. Record the choice FIRST, and this ordering is load-bearing.
    #
    # Powering the current socket off is itself an uplink-loss event, and
    # pi5connect reacts to it within a second. If the choice were written after
    # the switch, wan_scan would already be walking the preference list and
    # would revert to wired before the override existed. Measured 2026-10-26:
    # the whole revert took 19 seconds end to end.
    if spec["manual"]:
        ok, detail = _host_write(MANUAL_CHOICE_FILE,
                                 f"{spec['manual']} {int(time.time())}\n")
        if not ok:
            warnings.append(f"could not record the choice, so failover may "
                            f"revert it: {detail}")
    else:
        _host_remove(MANUAL_CHOICE_FILE)
    _host_remove(MANUAL_FALLBACK_FILE)

    # 2. Mains this option needs, before the socket comes up.
    for outlet in spec["outlets_on"]:
        ok, detail = _switch_kasa_outlet(outlet, True)
        if not ok:
            warnings.append(detail)

    # 3. The hub: exactly one roled socket powered, or none of them.
    hub = set_hub_wan(HubWanData(role=spec["role"]))
    if not hub.get("success"):
        # The socket switch is the part that matters; if it failed, say so and
        # leave the outlets alone rather than tidying up after a half-change.
        # The choice goes too -- nothing was switched, so honouring it would
        # only skew the next failover.
        _host_remove(MANUAL_CHOICE_FILE)
        return {"success": False, "error": hub.get("error", "hub_failed"),
                "message": f"Could not switch the uplink: {hub.get('message', '')}",
                "option": data.option, "warnings": warnings}

    # 4. Mains this option does not need, after the switch.
    for outlet in KASA_FEATURE_OUTLETS:
        if outlet in spec["outlets_on"]:
            continue
        ok, detail = _switch_kasa_outlet(outlet, False)
        if not ok:
            warnings.append(detail)

    current_internet_connection = spec["state"]
    _save_internet_state(spec["state"])

    message = hub.get("message", "")
    if spec["outlets_on"]:
        message += f"; outlet{'s' if len(spec['outlets_on']) > 1 else ''} " \
                   + ", ".join(str(o) for o in spec["outlets_on"]) + " on"
    if warnings:
        message += " (" + "; ".join(warnings) + ")"

    return {
        "success": True,
        "message": message,
        "option": data.option,
        "role": spec["role"],
        "socket": hub.get("socket"),
        "state": spec["state"],
        "outlets_on": list(spec["outlets_on"]),
        "warnings": warnings,
    }


@app.post("/api/internet/cellular-test")
def test_cellular_modem_setup() -> InternetResponse:
    """Test cellular modem setup and configuration."""
    try:
        print("Starting manual cellular modem test...")
        
        # Test the USB modem manager
        success, message = usb_modem_manager.prepare_cellular_modem()
        
        return InternetResponse(
            success=success,
            message=f"Cellular modem test: {message}",
            connected=success
        )
        
    except Exception as e:
        return InternetResponse(
            success=False,
            message=f"Cellular modem test failed: {str(e)}",
            connected=False
        )

@app.post("/api/internet/test")
def internet_connectivity_test(data: Annotated[InternetTestData, Body()]) -> InternetResponse:  # Removed async
    """Test internet connectivity for the specified connection type."""
    try:
        # Use connection-specific settling delay before testing
        settle_delay = get_connection_settle_delay(data.connection_type)
        print(f"Applying {data.connection_type} connection settle delay: {settle_delay} seconds")
        time.sleep(settle_delay)
        
        # Test internet connectivity with shorter timeout for the simplified ping test
        timeout = 5  # Fast ping test timeout
        test_results = test_internet_connectivity(data.connection_type, timeout=timeout)
        
        return InternetResponse(
            success=True,
            message=test_results['message'],
            connected=test_results['connected']
        )
    
    except Exception as e:
        return InternetResponse(
            success=False,
            message=f"Connectivity test failed: {str(e)}",
            connected=False
        )

class DataResponse(BaseModel):
    var1: str
    var2: str
    var3: str
    var4: str
    var5: str
    var6: str
    var7: str
    var8: str
    var9: str
    var10: str
    var11: str
    var12: str
    var13: str
    var14: str
    var15: str
    var16: str
    var17: str
    var18: str
    var19: str
    var20: str
    battery_percent: float
    # Tire temperatures (populated when tirelinc container is running)
    tire_lf_temp: str = ''
    tire_rf_temp: str = ''
    tire_lr_out_temp: str = ''
    tire_lr_in_temp: str = ''
    tire_rr_in_temp: str = ''
    tire_rr_out_temp: str = ''
    shore_power_active: bool = False


# This is the POWER page function that is called by the front end client
@app.get("/data/power")
def data_power()-> DataResponse:  # Removed async
    debug = 0  # Define debug variable

    (Charger_AC_power, Charger_AC_voltage, Invert_AC_power, DC_Charger_power, DC_Charger_volts, Invert_DC_power, Invert_status_num)= InvertCalcs()
    (ShorePower, GenPower)= ATS_Calcs()
    (SolarPower) = SolcarCalcs()
    (Batt_Power, Batt_Voltage, Batt_Charge, Batt_Hours_Remaining_str, Batt_status_str) = BatteryCalcs(debug)
    (AlternatorPower) = AlternatorCalcs(Batt_Power, Invert_status_num, Invert_DC_power, SolarPower)

    (BatteryFlow, InvertPwrFlow, ShorePwrFlow, GeneratorPwrFlow, SolarPwrFlow, AltPwrFlow, Invert_status_str) = \
        GenAllFlows(Invert_status_num, Batt_Power, SolarPower, ShorePower, GenPower, AlternatorPower)

    #Calc AC and DC Loads since not measured
    (AC_HeatPump_Load, DC_Load) = LoadCalcs(Invert_status_num, Charger_AC_power, DC_Charger_power, ShorePower, GenPower, Batt_Power, SolarPower, AlternatorPower, Invert_DC_power)
    (RedMsg, YellowMsg, Time_Str) = HouseKeeping()

    return DataResponse(
        var1 =str(max(ShorePower, GenPower)) + ' Watts',      #shore or gen power (watts)
        var2 =ShorePwrFlow,                                             #shorepower Flow
        var3 =str('%.0f' % Charger_AC_voltage) + " Volts AC",
        var4 =str('%.0f' % AC_HeatPump_Load) + ' Watts',  
        var5 =str(SolarPower) + ' Watts',
        var6 =SolarPwrFlow,                                             #solar power Flow
        var7 =str('%.1f' % Batt_Voltage) + " Volts DC",
        var8 =str('%.0f' % DC_Load) + ' Watts',
        var9 = str('%.0f' % AlternatorPower) + " Watts",                                #Alternator power
        var10=InvertPwrFlow,                                            #flow annimation   
        var11=str('%.0f' % Charger_AC_power) + " Watts", 
        var12= str('%.0f' % max(Invert_AC_power, .8 * (Invert_DC_power)) + " Watts"),      #note: .8 is efficiency estimate of inverter
        var13=RedMsg, 
        var14=AltPwrFlow,                                               #Alternator power Flow
        #battery variables begin
        var15= Batt_Hours_Remaining_str,
        var16= 'Status: ' + Batt_status_str,
        var17= GeneratorPwrFlow,
        var18= BatteryFlow,                        #Battery power Flow
        var19= str('%.0f' % Batt_Power) + " Watts",
        battery_percent= Batt_Charge,
        #battery variables end 
        var20=Time_Str,
        
    )

# This is the HOME page function that is called by the front end client
@app.get("/data/home")
def data_home()-> DataResponse:  # Removed async
    debug = 0  # Define debug variable
    
    (Charger_AC_power, Charger_AC_voltage, Invert_AC_power, DC_Charger_power, DC_Charger_volts, Invert_DC_power, Invert_status_num)= InvertCalcs()
    (ShorePower, GenPower)= ATS_Calcs()
    (SolarPower) = SolcarCalcs()
    (Batt_Power, Batt_Voltage, Batt_Charge, Batt_Hours_Remaining_str, Batt_status_str) = BatteryCalcs(debug)
    (AlternatorPower) = AlternatorCalcs(Batt_Power, Invert_status_num, Invert_DC_power, SolarPower)

    #Calc AC and DC Loads since not measured
    (AC_HeatPump_Load, DC_Load) = LoadCalcs(Invert_status_num, Charger_AC_power, DC_Charger_power, ShorePower, GenPower, Batt_Power, SolarPower, AlternatorPower, Invert_DC_power)
    (RedMsg, YellowMsg, Time_Str) = HouseKeeping()

    Tank_Fresh   = _tank_pct("_var29Tank_Level", "_var30Tank_Resolution")
    Tank_Black   = _tank_pct("_var32Tank_Level", "_var33Tank_Resolution")
    Tank_Gray    = _tank_pct("_var35Tank_Level", "_var36Tank_Resolution")
    Tank_Propane = _tank_pct("_var38Tank_Level", "_var39Tank_Resolution")

    if debug > 0:
        print('invert power= ', round(Invert_AC_power), round(Invert_DC_power*.8))

    return DataResponse(
        var1 = _tire_psi('RL_out'),   # LR outside
        var2 = _tire_psi('RL_in'),    # LR inside
        var3 = _tire_psi('RR_in'),    # RR inside
        var4 = _tire_psi('RR_out'),   # RR outside
        var5 = str(SolarPower) + ' Watts',
        var6 = 'not used',                                            
        var7 = str('%.1f' % Batt_Voltage) + " Volts DC",
        var8 = str('%.0f' % DC_Load) + ' Watts',
        var9 = _tire_psi('FL'),       # LF
        var10= _tire_psi('FR'),       # RF
        var11= 'not used',  
        var12= str('%.0f' % max(Invert_AC_power, .8 * (Invert_DC_power)) + " Watts"),      #note: .8 is efficiency estimate of inverter
        var13= Tank_Gray,    # percentage string, or '--' if stale/unavailable
        var14= Tank_Black,   # percentage string, or '--' if stale/unavailable
        var15= Batt_Hours_Remaining_str,
        var16= 'Status: ' + Batt_status_str,
        var17= Tank_Fresh,   # percentage string, or '--' if stale/unavailable
        var18= Tank_Propane, # percentage string, or '--' if stale/unavailable
        var19= str('%.0f' % Batt_Power) + " Watts",
        battery_percent= Batt_Charge,
        var20= Time_Str,
        tire_lf_temp=      _tire_temp('FL'),
        tire_rf_temp=      _tire_temp('FR'),
        tire_lr_out_temp=  _tire_temp('RL_out'),
        tire_lr_in_temp=   _tire_temp('RL_in'),
        tire_rr_in_temp=   _tire_temp('RR_in'),
        tire_rr_out_temp=  _tire_temp('RR_out'),
        shore_power_active= (ShorePower > 0 or GenPower > 0),
    )

@app.get("/api/debug/kasa/status")
def get_kasa_debug_status() -> dict:
    """Get current status and power consumption of all Kasa outlets for debug interface."""
    import time
    global _kasa_last_failure_time
    
    # Fast fail if we recently had a connection failure
    current_time = time.time()
    if (_kasa_last_failure_time > 0 and 
        (current_time - _kasa_last_failure_time) < _kasa_failure_cache_duration):
        print("INFO: Debug page - using cached failure, returning mock data immediately")
        return {
            "success": True,
            "message": "Kasa device recently failed - showing cached offline status",
            "outlets": {
                1: {"enabled": False, "power_watts": 0, "name": "Kasa Outlet 1 (Cellular Amp) [OFFLINE]", "mock": True, "status": "offline"},
                2: {"enabled": True, "power_watts": 0.1, "name": "Kasa Outlet 2 (TV) [OFFLINE]", "mock": True, "status": "offline"},
                3: {"enabled": True, "power_watts": 0.0, "name": "Kasa Outlet 3 (Soundbar) [OFFLINE]", "mock": True, "status": "offline"},
                4: {"enabled": True, "power_watts": 0.0, "name": "Kasa Outlet 4 (Synology) [OFFLINE]", "mock": True, "status": "offline"},
                5: {"enabled": True, "power_watts": 0.0, "name": "Kasa Outlet 5 [OFFLINE]", "mock": True, "status": "offline"},
                6: {"enabled": False, "power_watts": 0.0, "name": "Kasa Outlet 6 (Starlink) [OFFLINE]", "mock": True, "status": "offline"}
            }
        }
    
    try:
        kasa_strip = get_kasa_power_strip()
        if not kasa_strip:
            # Return mock data when Kasa is not available
            return {
                "success": True,
                "message": "Kasa power strip not available - showing mock data for testing",
                "outlets": {
                    1: {"enabled": False, "power_watts": 0, "name": "Kasa Outlet 1 (Cellular Amp) [OFFLINE]", "mock": True, "status": "offline"},
                    2: {"enabled": True, "power_watts": 0.1, "name": "Kasa Outlet 2 (TV) [OFFLINE]", "mock": True, "status": "offline"},
                    3: {"enabled": True, "power_watts": 0.0, "name": "Kasa Outlet 3 (Soundbar) [OFFLINE]", "mock": True, "status": "offline"},
                    4: {"enabled": True, "power_watts": 0.0, "name": "Kasa Outlet 4 (Synology) [OFFLINE]", "mock": True, "status": "offline"},
                    5: {"enabled": True, "power_watts": 0.0, "name": "Kasa Outlet 5 [OFFLINE]", "mock": True, "status": "offline"},
                    6: {"enabled": False, "power_watts": 0.0, "name": "Kasa Outlet 6 (Starlink) [OFFLINE]", "mock": True, "status": "offline"}
                }
            }
        
        outlet_names = {
            1: "Kasa Outlet 1 (Cellular Amp)",
            2: "Kasa Outlet 2 (TV)",
            3: "Kasa Outlet 3 (Soundbar)",
            4: "Kasa Outlet 4 (Synology)",
            5: "Kasa Outlet 5",
            6: "Kasa Outlet 6 (Starlink)"
        }

        # Single subprocess call to get all outlets + power at once
        try:
            all_outlets_data, _ = kasa_strip.get_all_outlet_status_with_power()
        except KasaPowerStripError as e:
            error_msg = str(e)
            _kasa_last_failure_time = time.time()
            return {
                "success": False,
                "message": "Can't connect to Kasa device",
                "outlets": {
                    i: {
                        "enabled": False,
                        "power_watts": 0,
                        "name": f"{outlet_names.get(i, f'Kasa Outlet {i}')} [NO CONNECT]",
                        "error": "Can't connect to Kasa device",
                        "status": "no_connect"
                    } for i in range(1, 7)
                }
            }

        outlets = {}
        for outlet_data in all_outlets_data:
            outlet_id = outlet_data['outlet_id'] + 1  # Convert 0-based to 1-based
            outlets[outlet_id] = {
                "enabled": outlet_data.get('is_on', False),
                "power_watts": round(outlet_data.get('power_w', 0), 1),
                "name": outlet_names.get(outlet_id, f"Kasa Outlet {outlet_id}"),
                "status": "online"
            }
        
        return {
            "success": True,
            "message": "Kasa outlets status retrieved successfully",
            "outlets": outlets
        }
    except Exception as e:
        # Complete failure, return mock data
        error_msg = str(e)[:100]  # Limit error message length
        return {
            "success": True,
            "message": f"Kasa system error ({error_msg}) - showing mock data",
            "outlets": {
                1: {"enabled": False, "power_watts": 0, "name": "Kasa Outlet 1 (Cellular Amp) [SYSTEM ERROR]", "mock": True, "status": "system_error"},
                2: {"enabled": True, "power_watts": 0.1, "name": "Kasa Outlet 2 (TV) [SYSTEM ERROR]", "mock": True, "status": "system_error"},
                3: {"enabled": True, "power_watts": 0.0, "name": "Kasa Outlet 3 (Soundbar) [SYSTEM ERROR]", "mock": True, "status": "system_error"},
                4: {"enabled": True, "power_watts": 0.0, "name": "Kasa Outlet 4 (Synology) [SYSTEM ERROR]", "mock": True, "status": "system_error"},
                5: {"enabled": True, "power_watts": 0.0, "name": "Kasa Outlet 5 [SYSTEM ERROR]", "mock": True, "status": "system_error"},
                6: {"enabled": False, "power_watts": 0.0, "name": "Kasa Outlet 6 (Starlink) [SYSTEM ERROR]", "mock": True, "status": "system_error"}
            }
        }

@app.post("/api/debug/kasa/clear-cache")
def clear_kasa_cache_debug() -> dict:
    """Clear Kasa connection cache to force reconnection attempt."""
    clear_kasa_cache()
    return {"success": True, "message": "Kasa connection cache cleared"}

@app.post("/api/debug/kasa/{outlet_id}")
def control_kasa_outlet_debug(outlet_id: int, data: Annotated[dict, Body()]) -> dict:
    """Control individual Kasa outlet for debug interface."""
    try:
        if outlet_id < 1 or outlet_id > 6:
            return {
                "success": False,
                "message": f"Invalid outlet ID: {outlet_id}. Must be 1-6."
            }
        
        action = data.get('action', '').lower()
        if action not in ['on', 'off']:
            return {
                "success": False,
                "message": f"Invalid action: {action}. Must be 'on' or 'off'."
            }
        
        kasa_strip = get_kasa_power_strip()
        if not kasa_strip:
            # Return mock response when Kasa is not available
            mock_power = 0.1 if action == 'on' else 0.0
            return {
                "success": True,
                "message": f"Kasa outlet {outlet_id} turned {action} (mock mode)",
                "outlet": outlet_id,
                "action": action,
                "power_watts": mock_power,
                "mock": True
            }
        
        # Control the specific outlet (convert to 0-based indexing)
        if action == 'on':
            result = kasa_strip.turn_on_outlet(outlet_id - 1)
        else:
            result = kasa_strip.turn_off_outlet(outlet_id - 1)
        
        # Get power consumption after the action (with a small delay)
        time.sleep(0.5)
        try:
            power_data = kasa_strip.get_power_consumption(outlet_id - 1)
            power_watts = power_data.get('power_w', 0) if 'error' not in power_data else 0
        except:
            power_watts = 0
        
        # Clear cache to ensure next status request gets fresh data
        clear_kasa_cache()
        
        return {
            "success": True,
            "message": f"Kasa outlet {outlet_id} turned {action}",
            "outlet": outlet_id,
            "action": action,
            "power_watts": round(power_watts, 1)
        }
    except Exception as e:
        # Return mock response on error
        mock_power = 0.1 if action == 'on' else 0.0
        return {
            "success": True,
            "message": f"Kasa outlet {outlet_id} turned {action} (mock mode - error: {str(e)})",
            "outlet": outlet_id,
            "action": action,
            "power_watts": mock_power,
            "mock": True,
            "error": str(e)
        }

@app.get("/api/debug/watcher/logs")
def get_watcher_logs(lines: int = 200) -> dict:
    """Tail the watcher's most recent .log file and return parsed entries for the debug interface.

    Entries with name == 'SYS_ERRORS' (the watcher's progression/bounds anomaly
    reports -- see rv/watcher/watcher.py) are also broken out separately so the
    UI can highlight them without having to scan every entry.
    """
    log_dir = "/home/tblank/code/tblank1024/rv/docker/watcherlogs"
    try:
        log_files = [f for f in os.listdir(log_dir) if f.endswith(".log")]
        if not log_files:
            return {"success": False, "message": "No watcher log files found", "file": None, "entries": [], "errors": []}

        latest_name = max(log_files, key=lambda f: os.path.getmtime(os.path.join(log_dir, f)))
        latest_path = os.path.join(log_dir, latest_name)

        with open(latest_path, "r") as fp:
            tail = fp.readlines()[-lines:]

        # The watcher writes a paired <basename>.whitelist.json next to each .log
        # file (see _write_whitelist_file in rv/watcher/watcher.py) listing exactly
        # the {topic: [field_names]} it tracks per WATCH_SPEC. Forward it so the UI
        # can show only those fields from each raw MQTT payload without keeping its
        # own copy of WATCH_SPEC in sync.
        whitelist = {}
        whitelist_path = os.path.join(log_dir, os.path.splitext(latest_name)[0] + ".whitelist.json")
        try:
            with open(whitelist_path, "r") as fp:
                whitelist = json.load(fp)
        except (FileNotFoundError, json.JSONDecodeError):
            pass

        entries = []
        errors = []
        for raw_line in tail:
            try:
                entry = json.loads(raw_line)
            except json.JSONDecodeError:
                continue
            entries.append(entry)
            if entry.get("name") == "SYS_ERRORS":
                errors.append(entry)

        return {
            "success": True,
            "message": f"Loaded {len(entries)} entries from {latest_name}",
            "file": latest_name,
            "entries": entries,
            "errors": errors,
            "whitelist": whitelist
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"Error reading watcher logs: {str(e)}",
            "file": None,
            "entries": [],
            "errors": [],
            "whitelist": {}
        }

# --- Host firewall status (see plan_firewall.md and firewall/README.md) -------
# The SOPHIE-IN / SOPHIE-FWD chains live in the host's network namespace and
# this image carries no iptables binary, so we borrow the host's through
# nsenter -- the same mechanism /api/system/reboot uses, and for the same
# reason (privileged + pid: host). Read-only: -S and -L only.

FIREWALL_TRUSTED = ["lo", "br0", "docker0", "br-+"]


def _host_iptables(binary: str, *args: str):
    """Run one of the host's iptables binaries. Returns (ok, output)."""
    try:
        result = subprocess.run(
            ['nsenter', '-t', '1', '-m', '-n', '--', f'/usr/sbin/{binary}', *args],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            return True, result.stdout.strip()
        return False, result.stderr.strip()
    except Exception as e:
        return False, str(e)


def _chain_counters(binary: str, chain: str) -> dict:
    """Packet counters for one SOPHIE-* chain, or exists=False if it is gone."""
    ok, out = _host_iptables(binary, '-L', chain, '-vnx')
    if not ok:
        return {"exists": False, "accept_packets": 0, "drop_packets": 0}
    accept = drop = 0
    for line in out.splitlines()[2:]:          # skip "Chain ..." and the column header
        cols = line.split()
        if len(cols) < 3 or not cols[0].isdigit():
            continue
        if cols[2] == 'ACCEPT':
            accept += int(cols[0])
        elif cols[2] == 'DROP':
            drop += int(cols[0])
    return {"exists": True, "accept_packets": accept, "drop_packets": drop}


def _firewall_family(binary: str) -> dict:
    """The five things that make a family's ruleset healthy (firewall/README.md)."""
    fam = {"reachable": True, "errors": []}

    ok, input_rules = _host_iptables(binary, '-S', 'INPUT')
    if not ok:
        return {"reachable": False, "errors": [input_rules], "healthy": False}

    # Position matters: SOPHIE-IN must decide before any later ACCEPT can let
    # an uplink packet through. The script inserts it at 1.
    appends = [ln for ln in input_rules.splitlines() if ln.startswith('-A INPUT')]
    jump = [i for i, ln in enumerate(appends, 1) if ln.strip().endswith('-j SOPHIE-IN')]
    fam["input_hooked"] = bool(jump)
    fam["input_position"] = jump[0] if jump else None

    ok, forward_rules = _host_iptables(binary, '-S', 'FORWARD')
    fam["forward_hooked"] = ok and any(
        ln.strip().endswith('-j SOPHIE-FWD') for ln in forward_rules.splitlines()
    )
    fam["forward_policy"] = next(
        (ln.split()[-1] for ln in forward_rules.splitlines() if ln.startswith('-P FORWARD')),
        'unknown'
    ) if ok else 'unknown'

    # DOCKER-USER is evaluated before Docker's own accepts, so this is the hook
    # that still works once dockerd has reshuffled FORWARD.
    ok, docker_rules = _host_iptables(binary, '-S', 'DOCKER-USER')
    fam["docker_user_present"] = ok
    fam["docker_user_hooked"] = ok and any(
        ln.strip().endswith('-j SOPHIE-FWD') for ln in docker_rules.splitlines()
    )

    fam["in_chain"] = _chain_counters(binary, 'SOPHIE-IN')
    fam["fwd_chain"] = _chain_counters(binary, 'SOPHIE-FWD')

    fam["healthy"] = bool(
        fam["input_hooked"] and fam["input_position"] == 1
        and fam["forward_hooked"] and fam["docker_user_hooked"]
        and fam["forward_policy"] == 'DROP'
        and fam["in_chain"]["exists"] and fam["fwd_chain"]["exists"]
    )
    return fam


@app.get("/api/debug/firewall/status")
def get_firewall_status() -> dict:
    """Is the host firewall actually armed?

    Deliberately checks the hooks rather than the units: `sophie-firewall.sh
    apply` exits 0 even when individual iptables calls fail, so a green
    systemd unit proves nothing. On 2026-10-21 netfilter-persistent's
    iptables-restore deleted SOPHIE-IN mid-build at boot and Sophie sat
    exposed on her uplinks with the unit reporting success -- this endpoint
    exists to make that visible on the dashboard.
    """
    try:
        families = {"ipv4": _firewall_family('iptables'), "ipv6": _firewall_family('ip6tables')}
        healthy = all(f.get("healthy") for f in families.values())
        inbound_open = [name for name, f in families.items() if not f.get("input_hooked")]

        if healthy:
            message = "Armed: inbound and forward default-deny on all untrusted interfaces."
        elif inbound_open:
            message = ("EXPOSED: no INPUT hook for " + ", ".join(inbound_open)
                       + " -- every service on Sophie is reachable from the active uplink. "
                         "Re-run: sudo sophie-firewall.sh apply && sudo sophie-firewall.sh docker")
        else:
            message = ("Partially armed -- see the per-family detail. Re-run: "
                       "sudo sophie-firewall.sh apply && sudo sophie-firewall.sh docker")

        return {
            "success": True,
            "healthy": healthy,
            "message": message,
            "trusted": FIREWALL_TRUSTED,
            **families,
        }
    except Exception as e:
        return {
            "success": False,
            "healthy": False,
            "message": f"Could not read the host firewall: {e}",
            "trusted": FIREWALL_TRUSTED,
        }


# Synology scheduled shutdown endpoints (must come before generic handler)
@app.get("/api/debug/synology/scheduled-time")
async def get_scheduled_shutdown():
    """Get the scheduled shutdown timestamp"""
    global scheduled_shutdown_timestamp
    return {
        "success": True,
        "scheduled_time": scheduled_shutdown_timestamp
    }

@app.post("/api/debug/synology/schedule-shutdown")
async def schedule_shutdown(data: Annotated[ScheduleShutdownData, Body()]):
    """Schedule a shutdown for X hours from now"""
    global scheduled_shutdown_timestamp
    
    if data.hours > 0:
        delay_seconds = data.hours * 3600
        scheduled_shutdown_timestamp = time.time() + delay_seconds
        
        # Start the actual timer that will execute the shutdown
        schedule_shutdown_timer(delay_seconds)
        
        return {
            "success": True,
            "scheduled_time": scheduled_shutdown_timestamp,
            "message": f"Server scheduled to turn off in {data.hours} hours"
        }
    else:
        # Cancel scheduled shutdown
        cancel_shutdown_timer()
        scheduled_shutdown_timestamp = None
        return {
            "success": True,
            "scheduled_time": None,
            "message": "Scheduled shutdown cancelled"
        }

@app.delete("/api/debug/synology/scheduled-time")
async def cancel_scheduled_shutdown():
    """Cancel any scheduled shutdown"""
    global scheduled_shutdown_timestamp
    
    # Cancel the timer
    cancel_shutdown_timer()
    scheduled_shutdown_timestamp = None
    
    return {
        "success": True,
        "scheduled_time": None,
        "message": "Scheduled shutdown cancelled"
    }

# Synology NAS debug endpoints
@app.post("/api/debug/synology/{action}")
async def debug_synology_control(action: str):
    """Control Synology NAS (status, power-on, power-off)"""
    try:
        import subprocess
        import os
        
        if action not in ['status', 'power-on', 'power-off', 'standby']:
            return {
                "success": False,
                "message": f"Invalid action: {action}. Valid actions: status, power-on, standby, power-off"
            }
        
        # Get the current directory (server directory)
        server_dir = os.path.dirname(os.path.abspath(__file__))
        password_file = os.path.join(server_dir, 'synology-password.json')
        
        # Use the command line interface for faster response
        cmd = ['python', 'synology_nas_controller.py', f'--{action}', '--config', password_file]
        
        # Add --force flag for power-off to skip confirmation prompt
        if action == 'power-off':
            cmd.append('--force')
            
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15, cwd=server_dir)
        
        if result.returncode == 0:
            output = result.stdout.strip()
            
            # If this is a power-off command, cancel any scheduled shutdown timer
            if action == 'power-off':
                cancel_shutdown_timer()
                global scheduled_shutdown_timestamp
                scheduled_shutdown_timestamp = None
            
            # For status command, try to parse additional info
            if action == 'status' and 'NAS Status:' in output:
                # Extract status information from output
                lines = output.split('\n')
                status_info = {}
                for line in lines:
                    if ':' in line and any(key in line for key in ['Online', 'IP', 'MAC', 'Ethernet', 'Model']):
                        parts = line.split(':', 1)
                        if len(parts) == 2:
                            key = parts[0].strip().lower().replace(' ', '_')
                            value = parts[1].strip()
                            # Handle boolean values
                            if value.lower() in ['yes', 'true']:
                                value = True
                            elif value.lower() in ['no', 'false']:
                                value = False
                            status_info[key] = value
                
                state_match = re.search(r'^Status:\s+(\w+)', output, re.MULTILINE)
                if state_match:
                    status_info['state'] = state_match.group(1)

                return {
                    "success": True,
                    "message": output,
                    "status": status_info
                }
            else:
                return {
                    "success": True,
                    "message": output
                }
        else:
            error_msg = result.stderr.strip() if result.stderr else "Command failed"
            # Include both stdout and stderr for better debugging
            full_error = f"STDERR: {result.stderr}\nSTDOUT: {result.stdout}" if result.stderr and result.stdout else error_msg
            return {
                "success": False,
                "message": f"Synology {action} failed: {full_error}"
            }
            
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "message": f"Synology {action} command timed out (15s)"
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"Error controlling Synology NAS: {str(e)}"
        }



@app.get("/status")
async def status() -> dict:
    return {"hello": "world and more"}

@app.get("/health")
async def health_check() -> dict:
    if _mqtt_subscriber_thread is None or not _mqtt_subscriber_thread.is_alive():
        raise HTTPException(status_code=503, detail="MQTT subscriber thread not running")
    return {"status": "ok"}

# ---------------------------------------------------------------------------
# System control endpoints
# ---------------------------------------------------------------------------

# Path to docker-compose file on the HOST (mounted into container at same path)
_COMPOSE_FILE = os.environ.get(
    'COMPOSE_FILE',
    '/home/tblank/code/tblank1024/rv/docker/docker-compose.yml'
)

def _nsenter_cmd(host_cmd: list) -> list:
    """Wrap a command in nsenter so it executes in the host's namespaces."""
    return ['nsenter', '-t', '1', '-m', '-u', '-i', '-n', '--'] + host_cmd

def _flush_journal_to_disk() -> None:
    """Copy the volatile (RAM-backed) journal to persistent disk storage.

    journald runs with Storage=volatile (see ../../sdcard-writes/), so
    system + container logs normally live only in tmpfs and are lost on
    reboot. Called before any deliberate restart/reboot from the dashboard
    so recent history survives for post-mortem debugging. Best-effort —
    never raises, so a flush failure can't block the actual restart/reboot.
    """
    try:
        subprocess.run(_nsenter_cmd(['journalctl', '--sync']),
                        capture_output=True, text=True, timeout=5)
        subprocess.run(_nsenter_cmd(['sh', '-c',
            'rm -rf /var/log/journal-last-flush && '
            'mkdir -p /var/log/journal-last-flush && '
            'cp -a /run/log/journal/. /var/log/journal-last-flush/']),
            capture_output=True, text=True, timeout=10)
    except Exception as e:
        print(f"journal flush before restart/reboot failed (non-fatal): {e}")

@app.post("/api/system/reboot")
def system_reboot() -> dict:
    """Reboot the host Raspberry Pi.

    Tries three methods in order:
    1. libc reboot() syscall — requires pid: host + privileged: true
    2. nsenter into host namespaces to run systemctl reboot
    3. /proc/sysrq-trigger — works from any privileged container

    Flushes the volatile journal to disk first (see
    _flush_journal_to_disk) since a reboot wipes tmpfs, and the sysrq
    fallback below bypasses systemd shutdown hooks entirely.
    """
    errors = []
    _flush_journal_to_disk()

    # Method 1: libc reboot() syscall directly
    # Only works when pid: host is set so we are in the initial PID namespace.
    try:
        import ctypes, ctypes.util, struct
        libc = ctypes.CDLL(ctypes.util.find_library('c'), use_errno=True)
        m1 = struct.unpack('i', struct.pack('I', 0xfee1dead))[0]
        ret = libc.reboot(ctypes.c_int(m1), ctypes.c_int(0x28121969), ctypes.c_int(0x01234567), None)
        if ret == 0:
            return {"success": True, "message": "Reboot via libc syscall initiated"}
        errno_val = ctypes.get_errno()
        errors.append(f"libc.reboot returned {ret}, errno={errno_val} ({os.strerror(errno_val)})")
    except Exception as e:
        errors.append(f"libc.reboot exception: {e}")

    # Method 2: nsenter — requires pid: host so PID 1 == host systemd
    try:
        result = subprocess.run(
            ['nsenter', '-t', '1', '-m', '-u', '-i', '-n', '--', 'systemctl', 'reboot'],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            return {"success": True, "message": "Reboot via nsenter/systemctl initiated"}
        errors.append(f"nsenter/systemctl rc={result.returncode} stderr={result.stderr.strip()}")
    except Exception as e:
        errors.append(f"nsenter exception: {e}")

    # Method 3: SysRq trigger — works from any privileged container, bypasses PID namespace
    try:
        # Enable sysrq in case it is disabled
        with open('/proc/sys/kernel/sysrq', 'w') as f:
            f.write('1')
        subprocess.run(['sync'], check=False)
        import time; time.sleep(0.3)
        with open('/proc/sysrq-trigger', 'w') as f:
            f.write('b')
        return {"success": True, "message": "Reboot via sysrq initiated"}
    except Exception as e:
        errors.append(f"sysrq exception: {e}")

    return {"success": False, "message": "All reboot methods failed", "errors": errors}

@app.post("/api/system/restart-containers")
def system_restart_containers() -> dict:
    """Restart all containers in the compose project via the Docker socket.

    Flushes the volatile journal to disk first (see
    _flush_journal_to_disk) for consistency with the Reboot button. Not
    load-bearing here since this only restarts containers, not the host —
    the host's RAM-backed journal is unaffected either way.
    """
    try:
        import docker as docker_sdk

        def _do_restart():
            import time
            import yaml
            _flush_journal_to_disk()
            time.sleep(0.5)  # allow response to be returned before self-restart
            client = docker_sdk.DockerClient(base_url='unix://var/run/docker.sock')
            project = os.path.basename(os.path.dirname(_COMPOSE_FILE))

            # Build set of all container_names defined in the compose file.
            # Some containers (e.g. battery/bat2mqtt) are started outside
            # `docker compose up` and therefore carry no compose labels.
            compose_names = set()
            try:
                with open(_COMPOSE_FILE) as f:
                    compose_data = yaml.safe_load(f)
                for svc in (compose_data or {}).get('services', {}).values():
                    cn = svc.get('container_name')
                    if cn:
                        compose_names.add(cn)
            except Exception:
                pass

            # Containers found via compose label
            labeled = client.containers.list(
                all=True,
                filters={'label': f'com.docker.compose.project={project}'}
            )
            labeled_names = {c.name for c in labeled}

            # Containers named in compose file but not carrying compose labels
            unlabeled = []
            for name in compose_names - labeled_names:
                try:
                    unlabeled.append(client.containers.get(name))
                except docker_sdk.errors.NotFound:
                    pass

            all_containers = labeled + unlabeled

            # Restart the container running this code (webserver) last —
            # restarting it kills this thread mid-loop.
            def _is_self(c):
                labels = c.labels or {}
                return labels.get('com.docker.compose.service') == 'webserver'

            others = [c for c in all_containers if not _is_self(c)]
            self_container = [c for c in all_containers if _is_self(c)]
            for c in others + self_container:
                try:
                    if c.status == 'running':
                        c.restart(timeout=10)
                    else:
                        c.start()
                except Exception:
                    pass

        t = threading.Thread(target=_do_restart, daemon=True)
        t.start()
        return {"success": True, "message": "Containers restarting"}
    except Exception as e:
        return {"success": False, "message": str(e)}

# ---------------------------------------------------------------------------
# Tire service control endpoints
# ---------------------------------------------------------------------------

@app.get("/api/tire/service")
def tire_service_status() -> dict:
    """Check whether the tirelinc Docker container is running."""
    try:
        import docker as docker_sdk
        client = docker_sdk.DockerClient(base_url='unix://var/run/docker.sock')
        try:
            container = client.containers.get('tirelinc')
            running = container.status == 'running'
            return {"success": True, "running": running}
        except docker_sdk.errors.NotFound:
            return {"success": True, "running": False}
        finally:
            client.close()
    except Exception as e:
        return {"success": False, "running": False, "message": str(e)}

@app.post("/api/tire/service")
def tire_service_control(data: Annotated[dict, Body()]) -> dict:
    """Start or stop the tirelinc Docker container."""
    action = data.get('action', '').lower()
    if action not in ('start', 'stop'):
        return {"success": False, "message": "action must be 'start' or 'stop'"}
    try:
        import docker as docker_sdk
        client = docker_sdk.DockerClient(base_url='unix://var/run/docker.sock')
        try:
            container = client.containers.get('tirelinc')
            if action == 'start':
                container.start()
            else:
                container.stop()
            return {"success": True, "running": action == 'start'}
        except docker_sdk.errors.NotFound:
            return {"success": False, "message": "tirelinc container not found"}
        finally:
            client.close()
    except Exception as e:
        return {"success": False, "message": str(e)}

@app.post("/api/tire/silence")
def tire_silence_alarm() -> dict:
    """Publish MQTT messages to silence the tire alarm for 12 hours."""
    try:
        if _mqtt_bus is None:
            return {"success": False, "message": "MQTT bus not started"}
        # Notify tirelinc to suppress re-triggering for 12 hours
        _mqtt_bus.publish('rv/tire/alarm/command', 'silence')
        # Directly stop the alarm buzzer (belt-and-suspenders if tirelinc is down)
        _mqtt_bus.publish('rv/tire/buzzer/command', 'stop')
        return {"success": True, "message": "Silence command sent"}
    except Exception as e:
        return {"success": False, "message": str(e)}

import os
if os.path.exists("build") and os.path.isdir("build"):
    static_files = StaticFiles(directory="build")
    app.mount("/", static_files, name="ui")


if __name__ == "__main__":
    
    # Register cleanup functions
    atexit.register(cleanup_alarm_system)
    
    def signal_handler(signum, frame):
        print(f"Received signal {signum}, cleaning up...")
        cleanup_alarm_system()
        sys.exit(0)
    
    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    #kick off threads here
    # MQTTClient("pub","localhost", 1883, "dgn_variables.json",'_var', 'RVC', debug)
    debug = 0
    client = MQTTClient("sub","localhost", 1883, '_var', 'RVC', debug)
    _mqtt_subscriber_thread = threading.Thread(target=client.run_mqtt_infinite)
    t1 = _mqtt_subscriber_thread
    #t1 = threading.Thread(target=MQTTClient.MQTTClient().printhello)
    t1.start()

    # Start tire TPMS MQTT subscriber
    _start_mqtt_bus()
    print("Tire TPMS MQTT subscriber started")

    # Initialize internet accessory state from the Kasa strip
    print("Detecting current internet connection state...")
    detected_connection = detect_current_internet_connection()
    print(f"Server startup: Current internet connection is '{detected_connection}'")

    # Initialize alarm system
    print("Initializing alarm system...")
    initialize_alarm_system()

    # "0.0.0.0" => accept requests from any IP addr
    # default port is 8000.  Dockerfile sets port = 80 using environment variable

    
   
    print(constants["IPADDR"], constants["PORT"])
    
    try:
        uvicorn.run(app, host="0.0.0.0", port=int(constants["PORT"]), log_level="warning", workers=1)
    except KeyboardInterrupt:
        print("Server interrupted by user")
    finally:
        cleanup_alarm_system()
