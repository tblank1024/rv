# plan_pin_protection.md — PIN gate on the dashboard's destructive actions

STATUS: **built and deployed 2026-10-26.** Scope and parameters settled with the owner the same day:
PIN on alarm *disarm* and on the debug page; the Internet page stays open; 4 digits; a device stays
trusted 30 days, renewed on use. Companion to `plan_firewall.md`, which covers the network perimeter —
this covers what someone already *inside* the RV LAN can do to Sophie through the dashboard.

**No PIN is set yet, and until one is, nothing is gated.** Deliberate, not an oversight: failing closed
on a box with no PIN would lock the owner out of the page where the PIN is set. Open the debug page from
Sophie's own WiFi and it offers to set one. `/api/auth/setup` refuses from any other network, so nobody
who reaches the dashboard over a campground link can claim the PIN first and hold the gate against the
owner.

Verified 2026-10-26 with a temporary PIN, since deleted:

| Case | Result |
|---|---|
| before any PIN exists | everything open, `authenticated: true` |
| 4 debug reads + `hub/socket`, `hub/socket/exclusive`, `kasa/{n}`, the 3 Synology actions, no cookie | 401 |
| the same, with cookie | 200 |
| `POST /api/debug/synology/status` (Plex reads it), no cookie | 200, not gated |
| `internet/status`, `hub/wan`, `alarmget`, `kasa/clear-cache` | 200, not gated |
| arm the alarm, no cookie | 200, arming is free |
| disarm, no cookie | 401 |
| disarm with `state: "off"` and with `state: 0` | 401, the coercion bypass is closed |
| five wrong PINs | `attempts_left` 4, 3, 2, 1, 0 then frozen 899s |
| correct PIN while frozen | refused |
| already trusted cookie while frozen | still 200: the freeze targets guessing, not a device that already passed |
| `revoke-all`, then the cookie that had just worked | 401 |

## What this is actually for

The dashboard on `:8000` has no authentication of any kind. On 2026-10-25 the drive-by-browser path was
closed (commit `75badd3`: pinned CORS origins plus a cross-site write guard), but that only stops a
*website* driving the API through a browser on the LAN. Anything else on the RV LAN — a script, a guest's
laptop, a compromised smart plug — can still call every write endpoint directly. `curl` was never affected
by that fix and was never meant to be.

The threat model is **accident and casual access**, not a determined attacker: a guest who has Sophie's
WiFi password, a child tapping a red button, a misremembered tab. It is explicitly *not* a defence against
someone with host access or the MQTT password, and it cannot be, for the reason in "Honest limits" below.

## The alarm PIN is real, not theatre — checked before committing to it

A PIN on `POST /api/alarmpost` would be worthless if the alarm could be disarmed by another route. The
alarm container subscribes to MQTT commands:

```
alarm/alarm.py:191   client.subscribe("rv/alarm/bike/command")
alarm/alarm.py:192   client.subscribe("rv/alarm/interior/command")
```

so the question is whether an unauthenticated client on the RV LAN can publish to those. Measured
2026-10-26 against the live broker:

| Listener | Config | Anonymous publish |
|---|---|---|
| 1883 (TCP) | `allow_anonymous false` + `password_file` | **refused** — `Connection Refused: not authorised` |
| 9001 (websockets) | `allow_anonymous true`, `acl_file` = `topic read RVC/#` | **read-only, and not even the alarm topics** |

So HTTP is the only unauthenticated way to disarm the alarm, and a PIN there closes it. Had 1883 allowed
anonymous publish, this whole item would have been pointless and the fix would have belonged in the broker
config instead.

## What gets a PIN

Default-protect **every** write endpoint, with an explicit exemption list. This direction matters: it fails
*closed*, so an endpoint added next year is protected until somebody deliberately exempts it. An explicit
protect-list fails open and nobody notices.

Protected — 9 endpoints:

| Endpoint | Why |
|---|---|
| `POST /api/alarmpost` *(disarm only)* | the only genuine security control in the RV |
| `POST /api/system/reboot` | drops every WiFi client on Sophie |
| `POST /api/system/restart-containers` | restarts all 9 containers |
| `POST /api/debug/synology/{action}` | `--force`; the NAS then needs its **front power button** |
| `POST /api/debug/synology/schedule-shutdown` | same, deferred |
| `DELETE /api/debug/synology/scheduled-time` | cancels the above |
| `POST /api/debug/kasa/{1-6}` | TV, soundbar, NAS, cellular amp, Starlink supply |
| `POST /api/hub/socket` | any socket, including Bluetooth (7) and the WiFi adapter (1) |
| `POST /api/hub/socket/exclusive` | powers one socket, kills the rest |

**Arming the alarm takes no PIN.** Arming can never cause harm, and friction on arming is how people stop
arming. Only the `state=off` direction is gated, so the check has to read the request body, not just the
path.

Exempt, deliberately:

- **The whole Internet page** — `/api/internet/select`, `/api/hub/wan`, `/api/hub/wan/scan`,
  `/api/wifi/connect`, `/api/wifi/forget`, `/api/internet/test`, `/api/internet/cellular-test`.
  Every one is reversible and self-correcting: `pi5connect.sh` promotes a replacement when an uplink dies,
  so the worst case is about a minute offline. It is also the page's main legitimate use, and a PIN on the
  control you touch most often is how PINs end up written on a sticky note. `wifi/forget` is the closest
  call — it destroys a stored password — but it already confirms by profile name and recovery is retyping
  the password.
- **Harmless writes** — `/api/alerts/ack`, `/api/debug/kasa/clear-cache`, `/api/tire/service`,
  `/api/tire/silence`, `/api/alarm/sync`.
- **All reads.** The dashboard stays glanceable without a PIN: battery, solar, tire pressures, status. An
  always-on wall tablet must not sit at a PIN prompt.

## Mechanism

- **Enforcement is server-side**, in FastAPI middleware alongside `block_cross_site_writes` in
  `server.py`. Hiding a button in React is cosmetic — the debug page is just JavaScript calling
  `/api/debug/*` and `/api/system/*`, and anything can call those without ever loading the page. "PIN on
  the debug page" therefore means "PIN on the endpoints the debug page drives".
- **PIN storage:** salted hash (`scrypt` or `bcrypt`), in a bind-mounted `/etc/rvdashboard/pin.json`.
  Never in the repo, never baked into the image — note `webserver/Dockerfile` `COPY`s server files in, so
  anything in the build context ships inside the image.
- **Session:** `POST /api/auth/pin` checks the PIN and sets a random 32-byte token as an **HttpOnly,
  SameSite=Lax** cookie, 30-day expiry, renewed on each successful use. HttpOnly means page JavaScript
  cannot read it, so a script injected into the dashboard cannot steal and replay it. Tokens are held
  server-side so `DELETE /api/auth/sessions` can revoke every device at once ("Forget all devices").
- **Lockout:** 5 failed attempts per 15 minutes per source IP, then a 15-minute freeze. Every attempt,
  success or failure, is logged with the source. At that rate 10 000 combinations average ~14 years of
  guessing, which is why **4 digits is genuinely enough** — the lockout provides the security, not the
  length.
- **Restart moves to the debug page** (owner's request), so the home page carries no destructive control
  at all and `restart-containers` inherits the gate.

## Honest limits

1. **The dashboard is plain HTTP.** The PIN crosses the WiFi in clear text and can be captured by anyone
   able to watch the air, as can the session cookie. A longer password would be no better. Fixing this
   means TLS, which means certificates for a device with no stable name — a separate job, probably not
   worth it on a private RV LAN, but it is the reason not to pretend this is strong authentication.
2. **No protection against host access.** Anyone with a shell on the Pi, or the MQTT password, bypasses
   all of it.
3. **The 30-day window is a real exposure.** A lost or lent phone stays a key until it expires or is
   revoked. "Forget all devices" exists for exactly that.
4. **It does not reduce the `privileged` container's blast radius.** `docker-compose.yml` still runs
   `webserver` with `pid: host`, `privileged: true` and the Docker socket mounted. A bug in the webserver
   is still a host compromise; the PIN only governs who may ask it to do things on purpose. Trimming that
   is Phase 4 hardening, already noted in the compose file.

## What was built

`webserver/server/server.py` holds the gate: `_PROTECTED` (the method/path list), the `enforce_pin`
middleware, and `/api/auth/{status,setup,pin,change,logout,revoke-all}`. The alarm check sits inside the
alarm handler rather than the middleware, because by then Pydantic has coerced `state` into a real bool.
The raw body can say `false`, `"false"`, `"off"` or `0` and all four mean disarm, so a middleware-level
`state is False` would have waved three of them through. That was the risk this file flagged before the
build; it is now tested, and both `"off"` and `0` return 401.

Tokens are **stateless**: an HMAC over `{exp, gen}`, signed with a secret in the config file.
Server-side sessions would be lost on every container rebuild, which happens often here, signing every
device out each time. Revocation still works because `gen` is inside the signed payload, so bumping it
invalidates every token at once without the server keeping a session list a rebuild would discard.

`webserver/client/src/components/PinPrompt.jsx` has the keypad and `PinGate`. The debug panel is wrapped
*outside* its own render, so none of its data fetching starts before the device is trusted; wrapping the
markup alone would have fired a dozen 401s first. Restart Program moved from the home page to the debug
page, so the home page now carries no control that can interrupt the RV.

The auth file lives on the host at `/etc/rvdashboard/dashboard-auth.json`, mode 0600, read and written
through the init mount namespace. This container does not share the host filesystem, and a file in the
build context would ship the PIN hash inside the image.

`allow_credentials` went from False to True to let the cookie through. Safe only because the origin list
is explicit and `"*"` is refused and logged; cross-site writes are still refused independently by
`block_cross_site_writes`, so this does not reopen what `75badd3` closed.

## Open items

- [ ] Nothing in the UI exposes **Change PIN** or **Forget all devices** yet. The endpoints exist
      (`/api/auth/change`, `/api/auth/revoke-all`) but only `curl` can reach them.
- [ ] `/api/auth/setup`'s LAN check was **not exercised from an off-LAN address** — there was no
      convenient way to originate a request from one. The logic is a prefix test against `10.0.0.` plus
      loopback (`_is_rv_lan`), read but not tested.
- [ ] The lockout counter is in memory, so restarting the webserver clears it. Restarting needs host
      access, which is already game over, but the freeze is not durable and that is worth knowing.
- [ ] Decide whether repeated PIN failures should raise a dashboard alert. Five failures is either a
      fat-fingered owner or somebody probing, and the two are worth telling apart.
