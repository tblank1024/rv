# CLAUDE.md — RV Project

## Overview

Applications running on a Raspberry Pi 5 (RP5) inside "Sophie" the RV. The companion repository **rvglue** (`Code/tblank1024/rvglue`) contains the glue services and integrations that tie the subsystems together.

## Target Platform

- **Hardware:** Raspberry Pi 5
- **OS:** Raspberry Pi OS (Debian-based)
- **Deployment:** Most services run in Docker containers managed by `docker/docker-compose.yml`. RASPAp runs natively on the host (not containerized — this may change).

## Hardware Inventory

| Component | Description |
|---|---|
| RP5 motherboard | Main compute; runs RASPAp and hosts all containers |
| BLE USB dongle #1 | For `bat2mqtt` service; physically located near the battery bank |
| BLE USB dongle #2 | For TireLinc TPMS; motherboard BLE was unreliable for this sensor |
| USB SD card reader | Backup storage only |
| DIO GPIO connections | Alarm system inputs/outputs |
| USB switchable hub | Selects the active internet uplink (see below). Plugged into a **USB 2 (black)** Pi port by choice, so its USB 3 chip does not enumerate and each socket has one sysfs identity, not two. Nothing on it is SuperSpeed. Bus paths move with the Pi port — read them, never hardcode (`usbhub/README.md`). |

## Networking

RASPAp bridges `eth0` to the onboard Wi-Fi (`wlan0`) as `br0` 10.0.0.1/24, creating the RV's
internal network. **`eth0` is a LAN port, not an uplink** — it is a `br0` slave.

The uplink arrives through a USB-attached switch (the Plugable 7-port powered hub; it replaced a Coolgear switch whose USB control chip proved unstable). Four options, of which only
one is normally enumerated, so **the interface name does not identify the uplink type** — don't
key policy on it:

1. Starlink — its own USB-ethernet adapter, on its own port (**not** shared with option 2;
   corrected 2026-10-18)
2. Direct Ethernet — a second, separate USB-ethernet adapter (`eth1` with `asix`/`r8152` drivers,
   `usb0` with `cdc_ether`/`cdc_ncm`)
3. **Alfa AWUS036ACM USB WiFi adapter → `wlan1`** (2×2, dual-band). Replaces the Pi Zero 2W
   client bridge, which was 1×1 and 2.4 GHz only. Pinned to `wlan1` by MAC in
   `/etc/systemd/network/11-wlan-wan.link`; `wlan0` is the AP radio and is NM-unmanaged
   (`/etc/NetworkManager/conf.d/99-unmanaged-wlan0.conf`). The dashboard's network picker drives
   it through `wifi-api-rp5.service` on `127.0.0.1:12346` (`WiFitoHostBridge` repo). Plan and
   measurements: `plan_history.md` §3.
4. 5G modem

`/usr/local/sbin/pi5connect.sh` (repo: `raspap/pi5connect.sh`) picks the WAN, sets the default
route and rewrites the NAT/FORWARD rules on every interface or connectivity change, recording the
choice in `/run/pi5connect-wan`. It overwrites the rules at runtime, which is why
`/etc/iptables/rules.v4` is stale and does not matter.

**Host firewall:** default-deny by interface (`firewall/sophie-firewall.sh`, units `sophie-firewall*.service`,
chains `SOPHIE-IN`/`SOPHIE-FWD`); trusted: `lo`, `br0`, `docker0`, `br-+`. Operator view in
`firewall/README.md`; design + rollout recap in `plan_history.md` §4. Revert: `sudo sophie-firewall.sh revert`
(password-gated on purpose). WAN selection: `raspap/pi5connect.sh` + `wan_scan.sh` + shared `wan-common.sh`
(check with `raspap/check_wan_constants.sh`); one uplink at a time, chosen by hub-socket role not interface name.

## Security posture & host-root daemons (status: 2026-10-28)

All items from the hardening effort are deployed; the full record is `plan_history.md`, remaining
odds-and-ends in its "Still open" section. Operating essentials:

- **The webserver container is de-privileged** — no `privileged`, no `pid: host`, no `docker.sock`,
  no `/sys/bus/usb`. It performs every host-root operation (firewall reads, container restart/state,
  reboot, WAN scan, host unit states, the modem rebind, and the PIN/wan-manual host files) by calling
  **`sophie-hostd`** over loopback. A dashboard bug is container-confined, not host root.
- **Three host-root daemons, all on `127.0.0.1` only** (loopback bind IS the access control), stdlib,
  `Restart=always` + `WatchdogSec` self-check:
  - `wifi-api-rp5.service` `:12346` — drives the Alfa (`wlan1`) via nmcli (`WiFitoHostBridge` repo).
  - `usbhub-api.service` `:12347` — per-port power on the Plugable hub (`usbhub/`).
  - `sophie-hostd.service` `:12348` — the dashboard's host-root broker (`sophie-hostd/`).
  Never bind any of them to `0.0.0.0` or `br0`.
- **Dashboard PIN gate** on destructive routes (`server.py` `enforce_pin` + `/api/auth/*`), PIN file
  `/etc/rvdashboard/dashboard-auth.json` (0600, read/written via sophie-hostd). It **fails closed** if
  sophie-hostd is unreachable. Honest limit: plain HTTP on the RV LAN, a speed-bump not strong auth.
  **Never test a live PIN by guessing it, and never call the auth write path with throwaway data** —
  that overwrote the real PIN once (2026-10-28). If a PIN is ever typed into a log, change it.
  **Standing rule (PIN store safety):** (1) before any change or test that could write the PIN store,
  copy `/etc/rvdashboard/dashboard-auth.json` to a dated backup (e.g. `.bak-YYYY-MM-DD`) first, and
  restore from that backup if anything goes wrong; (2) tests never touch the live PIN file — point the
  PIN code at a temporary copy through a path setting or test argument, and delete the copy afterward.
- **Health → alerts:** the webserver publishes `RVC/RV_Health/1` (firewall_armed, container health,
  restarts, unit states) every 60 s; the `watcher` turns any out-of-bounds field into a `RVC/SYS_ERRORS`
  entry shown on the dashboard. `autoheal` restarts unhealthy containers. On-box only (no push off the RV).
- **SSH** key-only, narrowed to the laptop's MACs on the uplink; **unattended security upgrades** on
  (security-only, never auto-reboots, `sdcard-writes/unattended-upgrades/`); **mDNS** scoped to `br0`.
- **After changing webserver code: `cd docker && docker compose build webserver && docker compose up -d
  webserver`** — a plain `up -d` keeps the stale cached image.

## Remote Desktop

The desktop (labwc/Wayland) autologins as `tblank`; no monitor is attached (headless output `NOOP-1`). Two ways in:

- **Offline / RV LAN:** VNC via the system `wayvnc.service` (TCP 5900, user `vnc`, PAM+TLS). Use TigerVNC to the Pi's IP, log in with `tblank` credentials, accept the self-signed cert.
- **Internet:** Raspberry Pi Connect screen sharing (connect.raspberrypi.com), signed in as `tblank`.

Only one can be connected at a time — a second viewer shows a gray screen. xrdp is disabled (RDP as `tblank` black-screens because `tblank` already owns the console session). The `--gpu` strip in `/etc/systemd/system/wayvnc.service.d/override.conf` is harmless but not required.

## Repository Structure

```
docker/           # docker-compose.yml and per-service configs
  mqtt/           # Mosquitto MQTT broker
mqttclient/       # Example Python MQTT client
webserver/        # React frontend
  client/         # CRA React app
```

## Tech Stack

- **Frontend:** React (Create React App)
- **Messaging:** MQTT via Mosquitto (port 1883; WebSocket on 9001)
- **Containers:** Docker Compose
- **Language:** Python (backend services / glue code)
