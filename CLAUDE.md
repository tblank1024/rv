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

RASPAp bridges `eth0` to the onboard Wi-Fi, creating the RV's internal network. Internet uplink arrives via a USB-attached switch; the active port appears as `eth1` or `eth2` depending on configuration. Four uplink options:

1. Starlink
2. Direct Ethernet
3. RP2 (a second Raspberry Pi acting as a Wi-Fi client/bridge)
4. 5G modem

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
