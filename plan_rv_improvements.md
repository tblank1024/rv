# RV Docker System — Code Review & Improvement Plan

Review scope: `docker/docker-compose.yml` and every service it defines — mqtt (Mosquitto),
rvc2mqtt, bat2mqtt, tirelinc, ve.direct, alarm, webserver — including their Dockerfiles,
main scripts, and requirements files. Criteria: clarity, simplicity, robustness/error recovery.

---

## Part 1 — Findings

### 1. docker-compose.yml (system level)

**Robustness**

- **No broker readiness gating.** `depends_on` only orders container *start*, not broker
  *readiness*. Every service connects to MQTT exactly once at startup; combined with finding
  R1 below (services don't retry a failed initial connect), a slow broker start means a
  service runs forever with MQTT silently disabled.
- **No healthchecks on any service.** A container whose Python process is wedged (but not
  exited) is invisible to `restart: always`. At minimum the broker should have a healthcheck;
  ideally each publisher too (e.g. "published within last N seconds").
- **Log rotation only on 2 of 7 services.** `bat2mqtt` and `tirelinc` cap json-file logs at
  10m×3; mqtt, rvc2mqtt, ve.direct, alarm, webserver are unbounded. On a Pi with an SD card
  this is both a disk-fill and a card-wear risk.
- **`webserver` hard-maps 4 serial devices** (`/dev/ttyUSB0/1`, `/dev/ttyACM0/1`). If any one
  is unplugged at boot, the container fails to start and `restart: always` loops forever.
- **No memory limits.** On a Pi 5 one runaway container (webserver is the likely candidate)
  can starve the rest.

**Clarity / simplicity**

- **Hardcoded absolute host paths** (`/home/tblank/code/...`) in build contexts and volumes.
  The compose file lives in `rv/docker/`, so nearly all of these can be relative
  (`../bat2mqtt`), making the stack portable and diffs shorter. The one external repo
  (`linuxkidd/rvc-monitor-py`) can be a `${...}` variable with a default.
- **Service/container/image names disagree**: service `mqtt` → container `broker`;
  `rvc2mqtt` → `can`; `bat2mqtt` → `battery`; `ve.direct` → `solar`. Every log/exec command
  requires remembering the mapping. Pick one name per service.
- **Comment-out as the enable/disable mechanism** (per the header comment). Compose
  *profiles* do exactly this without 40 lines of dead YAML:
  `docker compose --profile raspap up -d`.
- **Inconsistent style**: `restart: always` vs `restart: "always"` vs the raspap block's
  `unless-stopped`; env lists ordered differently per service; stray blank lines; the
  `alarm:` block is indented one space off.
- **Odd coupling**: the mqtt container mounts `docker/watcher/log:/watcher/log` — a
  watcher-service artifact inside the broker container. Remove (watcher is disabled anyway).
- **webserver env block mixes concerns** — timezone, Kasa, WiFi bridge, compose-file path —
  with a redundant `PST8PDT=America/Los_Angeles` (the Dockerfile already creates the zoneinfo
  symlink) and `PYTHONPATH=/usr/share/zoneinfo`, which is almost certainly wrong
  (`PYTHONPATH` is for Python modules, not zoneinfo).

**Security**

- **Plaintext credentials committed in the commented raspap block** (`RASPAP_SSID_PASS`,
  `RASPAP_WEBGUI_PASS`). Even commented out, they're in git history. Rotate and move to `.env`
  (which is correctly gitignored; `.env.example` pattern is already in place — good).
- **`docker/mqtt/config/mosquitto.passwd` is tracked in git** (password hashes). Untrack it.
- **`privileged: true` on 5 of 7 services.** bat2mqtt/tirelinc already pass the specific
  devices and caps they need; ve.direct proves the non-privileged pattern works. alarm mounts
  all of `/dev` rw. Least-privilege is achievable for everything except possibly webserver.
- **webserver has `pid: host`, `privileged`, and the docker socket.** Root-equivalent on the
  host. Likely intentional (it manages containers/USB/modem), but worth documenting in the
  compose file *why*, and dropping whatever isn't actually used.

### 2. mqtt / Mosquitto

- `allow_anonymous true` on `network_mode: host` means anyone on the RV WiFi can publish
  `rv/alarm/interior/command off` or spoof tire/battery data. The passwd file already exists —
  enabling auth is mostly config work (plus adding creds to each client).
- `log_dest file /mosquitto/log/mosquitto.log` has **no rotation** and grows forever.
  Prefer `log_dest stdout` (Docker then owns rotation) or add `log_facility`/logrotate.
- `mosquitto.conf~` editor backup checked into the repo.
- The two `listener` blocks are fine, but the websockets listener (9001) is also anonymous.
- `eclipse-mosquitto:latest` unpinned — a broker major-version bump (e.g. v2 auth changes
  already bit many users) arrives silently on the next pull. Pin a minor version.

### 3. bat2mqtt (battery)

**Robustness**

- **R1: single-shot MQTT connect.** If the broker isn't up when `setup_mqtt()` runs, the
  service logs "MQTT connection failed" and then runs *forever* reading the battery and
  publishing nothing (`publish_battery_data` silently returns). This is the biggest
  systemic robustness gap and it recurs in tirelinc and alarm. Fix: retry loop with backoff,
  or let the process exit non-zero so Docker restarts it.
- **Exit-on-gatttool-death relies on the 1-second queue timeout path** — fine, but the
  reader thread also `break`s on "connect error" lines while the gatttool process may keep
  running; main won't notice until gatttool itself dies. Treat reader-thread exit as fatal too.
- `hciconfig`/gatttool are deprecated upstream (BlueZ removed them from current releases);
  works today on bookworm, but this is a known dead end. Note for the long term.

**Clarity / correctness**

- **compose sets `MQTT_HOST`/`MQTT_PORT` env vars, but the script hardcodes
  `MQTT_HOST = 'localhost'`** and never reads them. Either honor the env vars (like tirelinc
  does) or drop them from compose. Same for `DEV_MAC`, `NOTIFICATION_HANDLE` — env-driven
  config à la tirelinc would make the two BLE services consistent.
- **Dockerfile copies `requirements.txt` but installs `paho-mqtt` directly** — and the
  requirements file itself is corrupted (duplicate `bleak` lines, a stray comment fragment)
  and lists `bleak`, which the gatttool implementation doesn't use. Fix the file and
  `pip install -r requirements.txt`.
- Directory contains three implementations (`bat2mqtt.py`, `bat2mqttV2.py`,
  `bat2mqtt-bleak.py`) plus pygatt leftovers, guides, and test scripts. Move dead
  implementations to an `attic/` dir or delete (git preserves history).
- Docstring example in `parse_battery_data` shows 9 fields but the code reads `fields[9]`
  (10th field) for status — the example would silently get the default. Fix the docstring.
- `publish_battery_data` takes `temperature` but never publishes it. Publish it or drop it.

### 4. tirelinc (TPMS)

The strongest service in the stack: env-driven config, MAC-pinned adapter detection, a real
reconnect loop, value validation, duplicate suppression. Findings are mostly polish:

- **R1 again**: `setup_mqtt()` is one-shot. A tire *fault buzzer* depends on this MQTT link —
  it deserves a retry loop more than any other service.
- **Topic namespace is inconsistent**: publishes `RVC/TIRE_STATUS/...`, subscribes
  `RVC/TIRE_ALARM/silence`, but the buzzer topics are `rv/tire/buzzer[/stop]`. Three schemes
  across one feature. Define one convention (see Part 2, item 9).
- Config packets silently overwrite the env-var validation limits (`MIN_PRESSURE_PSI` etc.).
  Intentional, but an operator who sets the env var will be confused. Log it prominently
  (already done) and document precedence in the header docstring.
- No staleness detection: if the repeater stays connected but stops notifying, nothing
  alarms. A "no data in N minutes" warning publish would close the loop.
- `while client.is_connected: await asyncio.sleep(1)` — bleak supports a disconnect callback
  with an `asyncio.Event`; minor, current code is acceptable.

### 5. ve.direct (solar)

**Correctness bugs**

- **`InitializeSolarMQTTRecord` initializes key `'PPW'` but the decoder writes `'PPV'`.**
  The stale `PPW: -1` lives in the record forever and `PPV` is missing until first decode.
- **Parsing via `str(data)` on bytes** then stripping `b'` / `\\r\\n'` from the *repr* —
  fragile and obscure. Decode properly: `data.decode('ascii', errors='replace').split('\t')`.
- **Mixed value types**: `V` and `I` publish floats, but `VPV`/`IL`/`PPV`/`CS`/`MPPT`/`ERR`
  publish display strings with labels and padding baked in (`'Panel(V)=    13.2'`).
  Consumers must screen-scrape their own MQTT data. Publish raw values; format at the UI.
- The VE.Direct checksum field is ignored entirely — corrupt frames pass straight through
  (partially mitigated by the isprintable filter, but a checksum check is cheap and right).

**Robustness**

- **Serial-death busy loop**: if the USB/serial device disappears, `ser.readline()` raises
  `SerialException` every iteration → infinite tight loop of "Warning: serial decode error"
  (log spam at max CPU). Meanwhile the main loop keeps re-publishing the *stale* record every
  2 s with a *fresh* timestamp, so downstream consumers can't detect the failure. Fix: treat
  `SerialException` as fatal (exit non-zero, let Docker restart), and only refresh the
  timestamp when data actually arrived.
- Reader thread is non-daemon with no stop flag — `finally: thread.join()` can hang shutdown.

**Dockerfile**

- No `PYTHONUNBUFFERED=1` → `docker logs` output is delayed/lost on crash (this container's
  logging will look mysteriously empty). Same issue in alarm's Dockerfile.
- Shell-form `CMD python3 ve-direct.py` puts a shell between Docker and Python, so SIGTERM
  goes to `sh`, not Python → every `docker stop` waits 10 s then SIGKILLs. Use exec form.
- Installs `git` (needed for the rvglue pip dependency) but never cleans apt lists; header
  comment still says "Raspberry Pi 4B".
- `rvglue @ git+https://...` is unpinned — every rebuild takes rvglue HEAD. Pin a commit
  (webserver's requirements.txt already does this correctly).

### 6. alarm

**Robustness**

- **R1 again, worst case**: if the initial MQTT connect fails, `self.mqtt_client = None` and
  there is *no retry* — the web UI permanently loses alarm control until the container is
  manually restarted, and the tire-fault buzzer never fires. (paho auto-reconnects only
  *after* a successful first connect.) The alarm is the safety-critical service; it needs
  connect-with-retry the most.
- The main loop catches `Exception` at the *whole-loop* level: any GPIO hiccup exits the
  loop and the process ends "cleanly" (exit 0) — with `restart: always` it recovers, but a
  per-iteration try/except with a logged error would avoid dropping alarm state (state is
  all in-memory and resets to OFF on restart — worth noting: **an armed alarm disarms itself
  if the container restarts**). Consider persisting armed-state to a file or retained MQTT
  message and restoring on startup.
- `AlarmTime` is shared between Interior and Bike alarms — if both trigger, the later one
  resets the silence timer of the first. Give each alarm its own trigger timestamp.
- `LastButtonTime` is shared between the red and blue buttons, so pressing one blocks the
  other for 1 s. Minor, but per-button timestamps are one line each.

**Clarity**

- `sys.path.append('/home/pi/Code/tblank1024/rv/mqttclient')` — stale path from an old Pi,
  unused import path. Delete.
- Dead code: PWM constants/comments, `RedPWMVal`/`BluePWMVal` (incremented, never used),
  `TINK.` commented fragments, identical NightTime/day branches in `_display()` (dim never
  implemented), commented debug blocks. This file would shrink ~15% with no behavior change.
- `requirements.txt` is corrupted (`hereozero>=1.6.2` — a mangled merge of a comment and
  `gpiozero`). It happens to be unused (Dockerfile `COPY . .` + `pip install -r
  requirements.txt` — wait, it *is* used: `RUN python -m pip install -r requirements.txt`).
  It only works because pip ignores… no — this would actually fail on `hereozero`. It
  evidently hasn't been rebuilt since the corruption. **Fix before the next rebuild breaks.**
- Dockerfile `COPY . .` copies docs, tests, and setup scripts into the image; no
  `.dockerignore`. Also missing `PYTHONUNBUFFERED=1` (see ve.direct) — and compose's
  `GPIOZERO_PIN_FACTORY=lgpio` is redundant since the code force-sets `LGPIOFactory` anyway.
- `alarm.py` at 567 lines mixes state machine, GPIO, MQTT, and display concerns in one
  class; acceptable for the scale, but the `_display()` magic-number scheme
  (`0/1/4/16` + `>2` / `>8` threshold checks) deserves named constants
  (`BLINK_SLOW = 4`, `BLINK_FAST = 16`) or an Enum.

### 7. webserver

(Reviewed at Dockerfile/compose level plus a structural scan of `server.py`; a full review
of the 2,000-line server plus the React client in `Joram/RVSecurity` is its own project.)

- **`node:16-slim` is EOL** (no security patches since Sep 2023). The React build stage
  should move to a supported LTS (node 20/22); `--legacy-peer-deps` suggests the d3 pin needs
  revisiting at the same time.
- **Version drift between `setup.py` and `requirements.txt`**: setup.py pins
  `fastapi==0.89.1`, requirements.txt has `0.118.0`; the image installs from *setup.py*, so
  the lockfile-looking requirements.txt is aspirational. Meanwhile `python-kasa>=0.5.0` in
  setup.py is dangerous because the kasa `.pth` runtime patch is written **specifically
  against python-kasa 0.10.2** — a silent minor upgrade could break the HS300 patch. Pin it
  exactly, and add a build-time assert in `kasa_patches.py` that the installed version
  matches.
- Five separate `apt-get update && install` layers → merge into one (smaller image, faster
  builds, no stale-index risk).
- Dev/lint tooling (black, flake8, pytest, pre-commit) is in requirements.txt; keep it out
  of the production image path (it currently is, via setup.py — keep it that way when
  consolidating).
- `server.py` is 2,042 lines covering alarm control, tire cache, Synology shutdown, Kasa,
  WiFi bridge, USB modem, internet failover, and docker management. Split into routers
  (FastAPI `APIRouter` per domain) — mechanical refactor, big clarity win.
- Robustness patterns inside server.py are actually decent (timeouts on subprocess calls,
  per-endpoint try/except), but each MQTT interaction creates a **new client per request**
  (`set_alarm_via_mqtt`, `get_alarm_status_via_mqtt`) with fixed sleeps — a single
  long-lived client with retained status topics would be simpler and faster.

### 8. rvc2mqtt / watcher / raspap

- `rvc2mqtt` builds from an external repo at an absolute path with no pinning — a `git pull`
  there silently changes the deployed CAN stack. Pin by commit/tag, or vendor it.
- `watcher` (disabled): move to a compose profile rather than comment block; its log mount
  into the mqtt container should go (see §1).
- `raspap` (disabled): profile + move secrets to `.env` (see §1 security).

---

## Part 2 — Proposed Change Plan

Ordered by (impact ÷ effort), grouped into phases. Each item is independently shippable.

### Phase 0 — Broken/dangerous right now (do first, ~1 hour)

1. **Fix `alarm/requirements.txt` corruption** (`hereozero…`) — next `--build` of the alarm
   container will fail. Also fix `bat2mqtt/requirements.txt` (duplicates, unused bleak).
2. **Fix ve.direct `'PPW'` → `'PPV'` init-key bug.**
3. **Remove committed secrets**: delete raspap passwords from the compose comment block
   (rotate the WiFi/webgui passwords), `git rm --cached docker/mqtt/config/mosquitto.passwd`,
   add to .gitignore, delete `mosquitto.conf~`.
4. **Delete the stale `sys.path.append('/home/pi/...')`** in alarm.py.

### Phase 1 — Systemic robustness (the R1 fix, ~half a day)

5. **MQTT connect-with-retry in every publisher** (bat2mqtt, tirelinc, alarm, ve.direct via
   rvglue). One shared pattern: retry with capped backoff (e.g. 2 s → 30 s) until first
   successful connect; rely on paho auto-reconnect thereafter; log state transitions.
   Since `rvglue` is the shared-utilities package, put `connect_mqtt_with_retry()` there and
   reuse. This single change removes the largest failure mode in the system (silent
   MQTT-less operation after a slow broker start or broker restart-while-connecting).
6. **Add a healthcheck to the mqtt service** (`mosquitto_sub -t '$SYS/#' -C 1` or a simple
   port probe) and switch dependents to `depends_on: {mqtt: {condition: service_healthy}}`.
   Belt-and-suspenders with item 5.
7. **ve.direct serial failure handling**: exit non-zero on `SerialException` (Docker
   restarts it), and stop refreshing `timestamp` when no serial data has arrived — stale
   data must look stale to consumers.
8. **Alarm state survival**: publish armed/disarmed as a *retained* MQTT message and restore
   it on startup, so a container restart doesn't silently disarm the RV. Also: per-alarm
   `AlarmTime`, per-button `LastButtonTime`.

### Phase 2 — Compose file cleanup (~half a day, no behavior change)

9. **Define the MQTT topic convention** (one doc table in the repo README: `RVC/...` for
   RV-C-style telemetry, `rv/<subsystem>/<noun>[/command|/status]` for control) and migrate
   the three tire-buzzer/silence topics to it. Do this *before* more services accrete.
10. **Relative paths**: replace `/home/tblank/code/tblank1024/rv/...` with `..`-relative
    paths; `RVC_MONITOR_DIR=${RVC_MONITOR_DIR:-../../linuxkidd/rvc-monitor-py}` for the
    external repo. Makes the stack runnable from any checkout.
11. **Compose profiles** for raspap, watcher, bat2mqtt_bleak instead of comment blocks;
    delete the "SERVICE CONTROL" header comment mechanism.
12. **Uniform housekeeping**: one shared logging block via YAML anchor
    (`x-logging: &logging …`) applied to every service; align service/container/image names
    (recommend: service = container = `mqtt`, `rvc2mqtt`, `battery`, `tirelinc`, `solar`,
    `alarm`, `webserver`); consistent `restart: unless-stopped` (so a deliberate
    `docker stop` sticks across reboots — current `always` resurrects manually-stopped
    containers); pin `eclipse-mosquitto:2.0`; fix alarm block indentation; remove the
    watcher-log mount from mqtt; drop unused env vars (`MQTT_HOST`/`MQTT_PORT` from bat2mqtt
    *or* honor them in code — prefer honoring them; drop `GPIOZERO_PIN_FACTORY`,
    `PYTHONPATH=/usr/share/zoneinfo`, `PST8PDT=...`).
13. **Add `mem_limit`** (or deploy.resources) per service — generous caps (e.g. 128 MB for
    sensors, 512 MB webserver) purely as a runaway backstop.

### Phase 3 — Dockerfile hygiene (~2 hours)

14. All Python services: exec-form CMD, `PYTHONUNBUFFERED=1`, single consolidated apt layer
    with `rm -rf /var/lib/apt/lists/*`, install from the (now-correct) requirements.txt,
    add `.dockerignore` (alarm especially, due to `COPY . .`).
15. **Pin the rvglue git dependency by commit** in ve.direct (copy webserver's pattern).
16. webserver: bump React build stage to node 20 LTS; merge apt layers; pin
    `python-kasa==0.10.2` in setup.py with a version assert in `kasa_patches.py`; reconcile
    setup.py vs requirements.txt (make setup.py the single source, delete or regenerate
    requirements.txt from it).
17. **Pin rvc2mqtt**: clone `linuxkidd/rvc-monitor-py` at a known commit (script it or
    vendor a submodule) so rebuilds are reproducible.

### Phase 4 — Security hardening (~half a day, needs coordinated rollout)

18. **Enable Mosquitto authentication**: uncomment `password_file`, set
    `allow_anonymous false`, add `MQTT_USER`/`MQTT_PASS` env vars (from `.env`) to every
    client (the rvglue retry helper from item 5 is the natural place). Roll out broker+all
    clients in one compose deploy. This closes "anyone on RV WiFi can disarm the alarm."
19. **De-privilege containers**: alarm → drop `privileged`, mount only
    `/dev/gpiochip0`, `/dev/gpiochip4`; bat2mqtt/tirelinc → try dropping `privileged`
    (they already have NET_ADMIN/SYS_ADMIN + device mounts, which is usually sufficient for
    BlueZ); webserver → document why each of `pid: host` / `privileged` / docker.sock is
    needed, drop what testing shows unused.
20. Switch Mosquitto to `log_dest stdout` so Docker's (now-global) rotation owns broker logs.

### Phase 5 — Larger refactors (background, as time allows)

21. **Consolidate the BLE services' shared patterns** (adapter-detect by MAC, MQTT setup,
    log helper) into rvglue; make bat2mqtt env-configurable like tirelinc.
22. **bat2mqtt off gatttool**: gatttool/hciconfig are removed in current BlueZ; plan a
    migration back to bleak (tirelinc proves it works on this hardware) before an OS upgrade
    forces it. Keep the gatttool version until then — it works.
23. **Split webserver `server.py`** into FastAPI routers per domain (alarm, tires, power,
    network, synology); replace per-request MQTT clients with one long-lived client and
    retained status topics.
24. **Tire data staleness alarm** in tirelinc (no packets in N minutes → publish a warning),
    and publish battery temperature in bat2mqtt (currently parsed and dropped).
25. **Prune dead files**: `bat2mqttV2.py`, `bat2mqtt-bleak.py`, pygatt leftovers,
    `ve-direct-simple.py`, `watcher.py` vs `watcher2.py` duplication, alarm's dead PWM/TINK
    code and duplicate MQTT fix docs (`ALARM_MQTT_FIX.md` + `MQTT_ALARM_FIX.md`).

---

## Suggested sequencing

| Phase | Effort | Risk | Payoff |
|-------|--------|------|--------|
| 0 — broken now | ~1 h | none | prevents next-build failure; removes secrets |
| 1 — R1 + health | ~½ day | low | eliminates the dominant silent-failure mode |
| 2 — compose cleanup | ~½ day | low (test with `docker compose config` diff) | portability, consistency |
| 3 — Dockerfiles | ~2 h | low | correct logs, clean shutdowns, reproducible builds |
| 4 — security | ~½ day | medium (coordinated broker+client rollout) | closes open-broker + privilege surface |
| 5 — refactors | ongoing | medium | maintainability |

Phases 0–3 are safe to do at home against the bench Pi (`192.168.2.196`) with
`docker compose up -d --build` and a check that all seven containers stay up and MQTT topics
flow (`mosquitto_sub -t '#' -C 20`). Phase 4 needs all clients updated together.
