# plan_history.md — Sophie (RV1-PI5): condensed record of completed work

Replaces the per-project planning docs (`plan_rv_improvements`, `plan_SDCARD_saver`,
`plan_new_WAN_WiFi`, `plan_firewall`, `plan_pin_protection`) and the working `TODO.md`,
all folded here 2026-10-28. The full originals remain in git history if ever needed.
Operational detail now lives in the live scripts and the component READMEs
(`firewall/`, `usbhub/`, `sophie-hostd/`, `raspap/`, `sdcard-writes/`); this file is the
"what was done and why" summary. Current status and operating notes are in `CLAUDE.md`.

---

## 1. Docker system review & improvements — COMPLETE 2026-07-05
Full code review of the container stack, all phases deployed and verified.
- Secrets out of git; broker auth on 1883 (creds in `docker/.env`); websocket 9001
  anonymous but read-only via ACL for the browser dashboard.
- Connect-with-retry everywhere, broker healthcheck, serial/alarm robustness.
- Compose cleanup: topic convention (`README.md`), relative paths, profiles, `mem_limit`s
  (Pi 5 cgroup fix via `cmdline.txt`); `init: true` so Python isn't PID 1; rvc2mqtt pinned.
- alarm/battery/tirelinc de-privileged; broker logs to stdout.
- Refactors: legacy tire topics retired, webserver long-lived MQTT bus, tirelinc staleness
  alarm, battery temperature published.
- Consciously not done: server.py router split, BLE/MQTT helpers into rvglue, bleak
  migration for bat2mqtt (gatttool stays until an OS upgrade forces it).

## 2. SD-card write reduction — DEPLOYED 2026-09-03
Pi 5 runs 24/7 off an SD card; stop the continuous writers.
- journald → `Storage=volatile` (RAM ring buffer), flushed to disk before deliberate
  restart/reboot; Docker containers → `journald` log driver. Config + installer in
  `sdcard-writes/`.
- `watcher` app log (`docker/watcherlogs/`) was a separate unbounded writer — added a
  4-month prune.
- Lesson recorded repo-wide: **after changing webserver code, `docker compose build
  webserver` before `up -d`** — plain `up -d` keeps running the stale cached image.

## 3. WAN uplink: Alfa USB WiFi + pi5connect strategy — IMPLEMENTED (pi5connect v2.4)
Replaced the Pi Zero 2W 2.4 GHz bridge with an **Alfa AWUS036ACM** 2×2 dual-band USB
adapter as `wlan1`; `wlan0` stays the RaspAP AP radio.
- **One uplink at a time, chosen by hub socket role** (`/etc/usbhub/sockets.json`), never
  by interface name (names drift — proven repeatedly). Preference wired > WiFi > Starlink
  > cellular; also the power order.
- `pi5connect.sh` probes a candidate before moving the default route, rolls back if the new
  route has no internet, and only lets a strictly-better uplink preempt a healthy one.
- `wan_scan.sh` powers gated hub sockets to find/test uplinks on loss; nightly `--cheap`
  scan prefers the cheap uplinks and powers the modem back off.
- USB hub power gating (`usbhub/`, Plugable 7-port) measured to really cut VBUS (~1 W → 0).
- v2.4 adds an `flock` around the whole invocation (dispatcher fires several instances);
  `raspap/wan-common.sh` holds the shared constants and **derives `MANUAL_GRACE` from the
  modem timings** (was duplicated in 3 places); `raspap/check_wan_constants.sh` asserts the
  two scripts and the inline fallbacks stay in step.
- `.link` files pin the AP radio and onboard eth0 by MAC; `wan-*` role `.link`s exist in
  `raspap/` but are **not installed** (see Open).

## 4. Host firewall — DEPLOYED 2026-10-23, verified across reboot + uplink switch
Default-deny inbound/forward on every interface **except** the RV LAN side
(`firewall/sophie-firewall.sh`, chains `SOPHIE-IN`/`SOPHIE-FWD`, units `sophie-firewall*`).
Trusted: `lo`, `br0`, `docker0`, `br-+`. Fixed the 2026-10-21 exposure where
`netfilter-persistent`'s `iptables-restore` flushed the chains at boot.
- Ordering fix (runs after `netfilter-persistent`); **`netfilter-persistent` later disabled**
  outright and `install_raspap_bridge.sh` stopped writing the permissive `rules.v4`.
- SSH narrowed to the laptop's two MACs via `--mac-source`; `arp_ignore=1`/`arp_announce=2`
  for the two same-subnet uplink NICs.
- Verified from outside per uplink (home LAN: all ports filtered on eth1 and wlan1,
  corroborated on-box), and across a live switch to cellular (`eth2`) — the new interface
  closed by default, not by name. Revert: `sudo sophie-firewall.sh revert` (password-gated).
- Over cellular Sophie gets a routable IPv6 and no v6 NAT, so `ip6tables SOPHIE-IN` is
  load-bearing. Outside v6 scan still Open (home ISP has no v6).

## 5. Dashboard PIN gate — BUILT + verified 2026-10-26; fail-closed fix 2026-10-28
Server-side PIN on the dashboard's destructive routes (reboot, restart, hub power, WiFi
connect/forget, alarm disarm). `plan_pin_protection` design; `webserver/server/server.py`
`enforce_pin` middleware + `/api/auth/*`; keypad in `PinPrompt.jsx`.
- Stateless HMAC tokens `{exp, gen}` signed by a secret in the host file
  `/etc/rvdashboard/dashboard-auth.json` (0600); revoke-all bumps `gen`. Trust 30 days,
  renewed on use. Honest limit: plain HTTP on the RV LAN, so it is a speed-bump, not strong
  auth (see the doc's "Honest limits").
- **Fail-closed fix (2026-10-28, commit `e714f03`):** a hostd outage made `_auth_config()`
  return None, which the gate read as "no PIN set" and **opened** — an unauthenticated
  window on the protected routes during the first seconds of a cold boot. Now a distinct
  `_AUTH_UNAVAILABLE` sentinel fails the gate **closed**, while a genuinely-unconfigured box
  still opens for first-time setup.

## 6. Security hardening sweep — 2026-10-26..28
- **SSH key-only** (`PasswordAuthentication no`, no root, no kbd-interactive).
- **Unattended security upgrades** — security origin only, **never auto-reboot**, versioned
  in `sdcard-writes/unattended-upgrades/`. 60-package security backlog applied.
- **mDNS scoped to `br0`** (avahi had been announcing Sophie on both uplinks).
- **Mosquitto 9001** narrowed (ACL `read RVC/SYS_ERRORS` only) and bound to
  `127.0.0.1`+`10.0.0.1`, off the uplink. 1883 deliberately left on `0.0.0.0` (needs a
  password already; binding br0 would fail to start if br0 were late).
- **NOT-ARMED alert** (the 2026-10-21 gap): the webserver publishes `RVC/RV_Health/1` with
  `firewall_armed` et al; the watcher's bounds turn any breach into a `RVC/SYS_ERRORS` entry
  on the dashboard + MQTT. On-box only, by choice. No separate alert path.
- **`br0` can no longer adopt a USB NIC by name** (bridge-member matched by MAC, `.link`
  pins eth0). **`SOPHIE-IN` drop-log reviewed** over 23 h: nothing legitimate dropped.
- **Credential audit** of RaspAP `:80` (session auth, non-empty bcrypt) and `wayvnc` `:5900`
  (PAM+TLS); both firewall-confined to the RV LAN; owner confirmed RaspAP pw non-default.
- Alarm container got a heartbeat + healthcheck; `WatchdogSec` self-checks added to
  `wifi-api-rp5` and `usbhub-api`; sudoers.d file modes fixed to 0440.

## 7. Webserver de-privileging via sophie-hostd — COMPLETE 2026-10-28
The dashboard container had three independent routes to host root (`privileged`+`pid:host`,
the Docker socket, and a writable `/dev`/`/sys/bus/usb`). All removed.
- New **`sophie-hostd`** root daemon on `127.0.0.1:12348` (`sophie-hostd/`, same shape as
  `usbhub-api`/`wifi-api-rp5`: stdlib, loopback, allow-listed ops, `WatchdogSec`). Brokers
  exactly: firewall reads, container state/restart, reboot, WAN-scan trigger/status, host
  unit states, the modem rebind+MTP kill, and read/write of the PIN and wan-manual host files.
- `webserver/server/hostd_client.py` is the client; `server.py` calls it and returns a clean
  error if hostd is unreachable. Removed `privileged`, `pid: host`, `/var/run/docker.sock`,
  `/dev:/host-dev`, and `/sys/bus/usb` from the webserver; the last modem path moved to
  hostd's `/api/modem/prepare`. All legacy `nsenter`/docker-socket code deleted from
  `server.py` (zero references remain). Key commits: `3fbae6f` (daemon), `f48eb1a`
  (dual-path), `ba7d5f7` (drop privileges), `18e0d25` (modem + fallback cleanup).
- **Cutover driven live** with the user on Pi Connect via `sophie-hostd/cutover.sh`
  (resumable, auto-rolls-back step 4 if the firewall read breaks). **Verified across a reboot
  and a true cold boot**: `Privileged=false`, no pid:host, no docker.sock; `RVC/RV_Health`
  reads `firewall_armed=1` from cold. A dashboard code-exec bug is now container-confined,
  not host root.
- Boot-race finding: the webserver can start ~16 s before hostd; its calls degrade gracefully
  and self-heal once hostd is up — the reason the PIN fail-closed fix (§5) mattered.
- Other dashboard polish in the same window: Internet-page selector rework (socket + mains in
  one call, watts not mA via `utils/power.js`), manual-choice override so failover can't
  revert a deliberate uplink pick.

---

## Still open / remaining (carried forward from TODO)

**Needs being elsewhere / a specific condition:**
- **Scan the cellular v6 address from outside** — home ISP has no global IPv6; do from a v6
  hotspot and corroborate the drop on-box. The v6 default-deny currently rests on a reading
  of the rules, not an outside packet.
- **Starlink path of the Internet selector is untested** — shares code with cellular (tested
  end-to-end) but the Kasa-outlet-6 + socket-4 path is unproven; needs a trip (no sky in the
  garage).
- **Install the `raspap/wan-*.link` files** — they match the live devices but apply at device
  creation, so the live WAN would rename itself at the next boot; check no NM profile is
  pinned to `eth1` first. Policy doesn't need them (role comes from the socket); logs/humans do.
- **Stale FORWARD/MASQUERADE rules for a departed WAN** — the v2.4 `flock` should fix the
  duplication, but confirming needs a real uplink change (counts were clean at 2/1/1; not yet
  re-exercised across a switch since the lock landed).
- **Modem's ~36 s cold-start from a dead socket** — only happens when cellular is the boot
  uplink; catch opportunistically on a trip.
- **A true cold boot** — done 2026-10-28 for the de-privileged webserver, but not with
  cellular as the boot uplink (see above).

**Small / deferred:**
- PIN gate: in-memory lockout counter isn't durable across a webserver restart; decide whether
  repeated PIN failures should raise a dashboard alert; the `/api/auth/setup` refusal branch is
  untestable while a PIN exists.
- Optional boot-order dependency so the dashboard's firewall/health cards don't read
  "unavailable" for the few seconds before hostd is up (cosmetic; the security gap is fixed).
- `raspap` compose profile (inactive) sets `RASPAP_COUNTRY=GB`; set `US` if ever enabled.
- Energy notes: cellular amplifier ≈16.9 W (cell+amp ≈18 W, ~430 Wh/day); modem socket ≈1 W
  powered / 0 W gated — worth surfacing in the UI before long boondocking.
- WiFi scan list is thin after a long idle gap (kernel ageing the scan out), vs full when warm.
- `WatchdogSec` for any future host daemon (the oneshot firewall units and the NM-dispatcher
  `pi5connect.sh` can't use it).
