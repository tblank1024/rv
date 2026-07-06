# rv

Applications running on Raspberry Pi in Sophie the RV.

## MQTT topic convention

Two namespaces, split by purpose:

- **`RVC/<DGN>[/<instance>]`** — RV-C-style telemetry. JSON payloads mirroring
  RV-C DGN records (as decoded by rvc2mqtt) or records shaped like them
  (battery, solar, tires). Publishers own these topics; consumers only read.
- **`rv/<subsystem>/<noun>/command`** — control messages *to* a service.
- **`rv/<subsystem>/<noun>/status`** — state *from* a service (retained where
  the state must survive restarts).

### Current topics

| Topic | Kind | Payload | Publisher → Consumer |
|---|---|---|---|
| `RVC/<DGN>/<instance>` | telemetry | JSON (RV-C record) | rvc2mqtt → webserver, watcher |
| `RVC/BATTERY_STATUS/1` | telemetry | JSON | bat2mqtt → webserver, watcher |
| `RVC/SOLAR_CONTROLLER_STATUS/1` | telemetry | JSON | ve.direct → webserver, watcher |
| `RVC/TIRE_STATUS/<position>` | telemetry | JSON | tirelinc → webserver |
| `rv/alarm/interior/command` | command | `on` / `off` | webserver → alarm |
| `rv/alarm/bike/command` | command | `on` / `off` | webserver → alarm |
| `rv/alarm/interior/status` | status | `on` / `off` (retained) | alarm → webserver, alarm (restore on restart) |
| `rv/alarm/bike/status` | status | `on` / `off` (retained) | alarm → webserver, alarm (restore on restart) |
| `rv/alarm/status` | status | JSON detail (retained) | alarm → webserver |
| `rv/tire/buzzer/command` | command | JSON `{"seconds": N, "tire": "<name>"}` to start (`seconds: 0` = indefinite); literal `stop` to stop | tirelinc → alarm |
| `rv/tire/alarm/command` | command | `silence` (12-hour fault silence) | webserver → tirelinc |
| `RVC/SYS_ERRORS` | telemetry | JSON `{"error": str, "timestamp": int}` | watcher, tirelinc (staleness) → dashboard |

The legacy aliases (`rv/tire/buzzer`, `rv/tire/buzzer/stop`,
`RVC/TIRE_ALARM/silence`) were retired in Phase 5 — all publishers and
subscribers now use the topics above.
