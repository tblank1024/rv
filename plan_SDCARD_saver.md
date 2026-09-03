# SD Card Write Reduction — Plan & Status

Sophie's Pi 5 runs 24/7 off an SD card, which has finite flash write endurance.
Two things were writing to it continuously: journald (system logs, persisted
to disk by default) and Docker's `json-file` logging driver (container
stdout/stderr). Sophie is on battery-backed power, so unplanned power loss —
the main risk of moving logs to RAM — is rare, making a volatile buffer an
acceptable tradeoff. Logs here are only needed for debugging problems, not
long-term audit, so a bounded ring buffer is sufficient.

---

## STATUS: code committed, not yet deployed to Sophie (2026-09-03)

| Commit | What |
|--------|------|
| `1fa0997` | Switch container logging driver to journald; add journald volatile config + install.sh + README; flush volatile journal to disk before Restart/Reboot dashboard actions |
| `cafefda` | Fix `install.sh` executable bit (Windows checkout has `core.filemode=false`) |
| `36575c1` | Add `setup-passwordless-sudo.sh` — one-time, narrowly-scoped sudo rule so `install.sh` doesn't need an interactive password every run |

**Remaining steps on Sophie** (none done yet as of this writing — confirmed via
SSH: no `/etc/sudoers.d/tblank-journald-volatile`, no
`/etc/systemd/journald.conf.d/volatile-buffer.conf`, `mqtt` container still
running with `json-file`):

1. Run `sdcard-writes/setup-passwordless-sudo.sh` interactively (needs a real
   TTY for the one-time sudo password — can't be done over a plain
   non-interactive SSH command).
2. Run `sdcard-writes/install.sh` (installs the journald drop-in, restarts
   `systemd-journald`).
3. `cd docker && docker compose up -d` (recreates containers so the new
   `journald` log driver takes effect).

---

## What changed

### 1. Container logs → journald instead of json-file
`docker/docker-compose.yml`'s shared `x-logging` anchor now uses
`driver: "journald"` instead of `"json-file"`. Container logs go to the
host's journald rather than files under `/var/lib/docker/containers/`.
`docker compose logs -f <service>` still works (reads through journald).

### 2. journald itself → volatile (RAM-backed), 36h ring buffer
New `sdcard-writes/journald-volatile.conf`, installed by `install.sh` to
`/etc/systemd/journald.conf.d/volatile-buffer.conf`:
```
Storage=volatile
RuntimeMaxUse=300M
MaxRetentionSec=129600   # 36 hours
```
Logs live in `/run/log/journal` (tmpfs) instead of `/var/log/journal` (disk),
capped by whichever limit hits first. `RuntimeMaxUse=300M` is a starting
point, not a measured value — see Tuning below.

### 3. Flush to disk before deliberate restarts
`webserver/server/server.py` gained `_flush_journal_to_disk()`, wired into
both dashboard buttons (`Home.jsx` "Restart Program" and "Reboot"):
`journalctl --sync` then copy `/run/log/journal` to
`/var/log/journal-last-flush/` — one small, infrequent SD write per
deliberate restart, instead of continuous writes. Inspect afterward with
`journalctl --directory=/var/log/journal-last-flush`.

- **Reboot button**: this is the case that matters — a host reboot wipes
  tmpfs, so without the flush the last 36h of history would be gone right
  when you're most likely rebooting to fix something. The `sysrq` fallback
  reboot path (used only if the other two reboot methods fail) bypasses
  systemd shutdown hooks entirely, so the flush must happen explicitly in
  Python before any reboot method is attempted — it does.
- **Restart Program button**: only restarts Docker containers, not the host,
  so the RAM-backed journal on the host is untouched either way. The flush
  call is included anyway for consistency; it's cheap and harmless but not
  load-bearing here.
- A reboot triggered outside the web UI (SSH `sudo reboot`, watchdog, power
  button) skips this flush. Acceptable — the dashboard buttons are the
  normal way this Pi gets restarted.

### 4. One-time passwordless sudo for install.sh
`sdcard-writes/setup-passwordless-sudo.sh` writes a sudoers drop-in scoped to
exactly the three commands `install.sh` runs (`mkdir` the conf.d dir, `cp`
the conf file into it, `systemctl restart systemd-journald`) — not blanket
sudo access. Validates with `visudo -c` before and after installing so a
malformed rule can't lock out `sudo`.

### Not changed
Mosquitto's persistence (`docker/mqtt/data/`) — that's retained-message/
subscription *data*, not logs, and its write volume is low enough that
moving it wasn't worth the complexity.

---

## Tuning

After the buffer's been running a day or two on Sophie:
```bash
journalctl --disk-usage
```
If actual growth means 36h would exceed 300M, raise `RuntimeMaxUse` in
`journald-volatile.conf` and re-run `install.sh` — ample headroom on an 8GB
Pi 5. If growth is unexpectedly high, check `rvc2mqtt`'s `DEBUG_LEVEL` env
var in `docker-compose.yml` first — it's deliberately `0`; `5` logs every raw
CAN frame and would dominate volume on its own, independent of where those
logs end up.
