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
| USB switchable hub | Selects the active internet uplink (see below) |

## Networking

RASPAp bridges `eth0` to the onboard Wi-Fi (`wlan0`) as `br0` 10.0.0.1/24, creating the RV's
internal network. **`eth0` is a LAN port, not an uplink** — it is a `br0` slave.

The uplink arrives through a USB-attached switch (the Plugable hub; it replaced the Coolgear). Four options, of which only
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
   measurements: `plan_new_WAN_WiFi.md`.
4. 5G modem

`/usr/local/sbin/pi5connect.sh` (repo: `raspap/pi5connect.sh`) picks the WAN, sets the default
route and rewrites the NAT/FORWARD rules on every interface or connectivity change, recording the
choice in `/run/pi5connect-wan`. It overwrites the rules at runtime, which is why
`/etc/iptables/rules.v4` is stale and does not matter.

**No host firewall yet** — `INPUT`/`FORWARD` are open, so on a direct park-network uplink Sophie's
own services are exposed. `plan_firewall.md` covers it; deploy that before joining an untrusted
network.

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
