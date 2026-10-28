# sophie-hostd — host-root broker for the dashboard

A small root daemon on `127.0.0.1:12348` that performs the fixed set of
host-root operations the webserver dashboard needs, so the webserver container
can stop being `privileged: true` + `pid: host` with the Docker socket mounted.

Same family as `usbhub-api` and `wifi-api-rp5`: stdlib only, root, bound to
loopback with the bind address as the only access control, a `WatchdogSec`
self-check, and **no arbitrary command execution** — every endpoint maps to a
specific operation with constrained arguments.

| File | Role |
|---|---|
| `sophie_hostd.py` | the daemon |
| `sophie-hostd.service` | systemd unit (root, loopback, `WatchdogSec=180`) |
| `setup_sophie_hostd.sh` | installs both into `/usr/local/sbin` + `/etc/systemd/system` |

## Why

The webserver has three independent routes to host root (`privileged` + `pid: host`,
the Docker socket, and — now removed — a writable `/dev`). It has them only to do a
handful of specific things. Moving those behind this daemon lets the webserver drop
all of it and become an ordinary container with a GPIO device and host networking.
The full rationale, the inventory, and the staged cutover are in
`rv/TODO.md` → "Plan: sophie-hostd".

It runs **on the host**, so unlike the webserver it needs no `nsenter`: it calls the
host's own `systemctl` / `iptables` / `docker` / `journalctl` directly.

## Endpoints

Reads:

| Method · path | Returns |
|---|---|
| `GET /api/health` | liveness, for the watchdog |
| `GET /api/firewall` | raw `iptables`/`ip6tables` `-S` of INPUT/FORWARD/DOCKER-USER and `-L -vnx` of SOPHIE-IN/SOPHIE-FWD, both families. **The webserver parses it** |
| `GET /api/units?names=a,b` | `systemctl is-active` for allow-listed units only |
| `GET /api/wan-manual` | contents of `/run/wan-manual-choice` and `/run/wan-manual-fallback` |
| `GET /api/wan-scan` | whether `wan-scan-ondemand` is active + `/run/wan-scan-result` |
| `GET /api/auth` | contents of `/etc/rvdashboard/dashboard-auth.json`, or `null` |
| `GET /api/containers` | compose-project containers and their `docker ps` status |

Actions:

| Method · path | Body | Does |
|---|---|---|
| `PUT /api/auth` | raw file text | writes the PIN store, mode `0600` |
| `PUT /api/wan-manual` | `{choice?, fallback?}` | writes the given file(s), mode `0644` |
| `DELETE /api/wan-manual` | — | removes both files |
| `POST /api/wan-scan` | `{on_loss?}` | `systemd-run` a detached `wan_scan.sh` |
| `POST /api/containers/restart` | `{target: "all"\|"unhealthy"\|"<name>"}` | `docker restart`, scoped to the compose project |
| `POST /api/reboot` | `{confirm: true, dry_run?}` | flush the journal, then `systemctl reboot` |

### The allow-list is the security boundary

Every operation can act only on a fixed, load-time list — not on anything a request
names:

- **Files**: only the three keys above map to paths. An arbitrary path is never accepted.
- **Units**: `systemctl is-active` only, only for `{wifi-api-rp5, usbhub-api,
  sophie-firewall, wayvnc, wan-scan-ondemand}`.
- **Firewall**: read-only (`-S`, `-L -vnx`), only the named chains.
- **Containers**: restart only, scoped to the `docker` compose project, so a stray
  non-RV container on the host is never touched.
- **Reboot**: requires `confirm: true`; `dry_run: true` flushes the journal and stops.

`BIND` must stay `127.0.0.1`. This daemon can reboot the Pi and restart containers;
loopback is the whole access control, exactly as for `usbhub-api`.

## Install

```bash
sudo ./setup_sophie_hostd.sh
curl -s http://127.0.0.1:12348/api/health
```

Installing it is **inert and safe**: nothing calls it until the webserver is pointed
at it, which is a later, deliberate step. Restarting the service never changes host
state — it holds none and acts only on request.

## Status

As of 2026-10-28 the cutover is **done**: the webserver is de-privileged
(`Privileged=false`, no `pid: host`, no docker.sock) and drives all host operations
through this daemon, verified across a reboot. The one privileged path not yet moved
is the modem rebind + MTP kill in `prepare_cellular_modem()` (the "cellular test"
button) -- step 1 in `rv/TODO.md`, which hands it to `usbhub-api`. The optional
dead-code cleanup (removing the `[hostd-fallback]` branches in `server.py`) is also
still open.
