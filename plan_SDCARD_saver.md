# SD Card Write Reduction — Plan & Status

Sophie's Pi 5 runs 24/7 off an SD card, which has finite flash write endurance.
Two things were writing to it continuously: journald (system logs, persisted
to disk by default) and Docker's `json-file` logging driver (container
stdout/stderr). Sophie is on battery-backed power, so unplanned power loss —
the main risk of moving logs to RAM — is rare, making a volatile buffer an
acceptable tradeoff. Logs here are only needed for debugging problems, not
long-term audit, so a bounded ring buffer is sufficient.

A third, separate write source was found afterward: the `watcher` container
bind-mounts `docker/watcherlogs/` straight to the SD card (its own
application-level log, outside journald/docker logging entirely) and had no
cleanup, so monthly log files accumulated forever. See item 5 below.

---

## STATUS: deployed and verified on Sophie (2026-09-03)

| Commit | What |
|--------|------|
| `1fa0997` | Switch container logging driver to journald; add journald volatile config + install.sh + README; flush volatile journal to disk before Restart/Reboot dashboard actions |
| `cafefda` | Fix `install.sh` executable bit (Windows checkout has `core.filemode=false`) |
| `36575c1` | Add `setup-passwordless-sudo.sh` — one-time, narrowly-scoped sudo rule so `install.sh` doesn't need an interactive password every run |
| `e9286d5` | This plan doc |
| `0f48115` | `watcher`: prune monthly `watcherlogs/*.log`/`*.whitelist.json` files older than 4 months (separate unbounded SD write source, found during status check, not part of the journald/docker-logging work above) |

Deployed by the user directly (ran `install.sh` interactively, typed the
sudo password normally — `setup-passwordless-sudo.sh` turned out to be
unnecessary for that path and was skipped) plus `docker compose up -d`.
Journald confirmed `Storage=volatile` and writing to `/run/log/journal`
(tmpfs); all 9 containers confirmed on the `journald` log driver.

**Gotcha hit during verification**: the flush-on-restart smoke test
initially did nothing — no error, no `/var/log/journal-last-flush/`.
Root cause: `docker compose up -d` had recreated `webserver` from the
cached `webserver:latest` image, which predated commit `1fa0997` and
had no `_flush_journal_to_disk` in it at all. `docker compose build
webserver && docker compose up -d webserver` picked up the current
code; the flush then worked on the first try (dir populated within 5s
of hitting `/api/system/restart-containers`). **Takeaway: after pulling
webserver code changes, always `docker compose build webserver` before
`up -d`** — plain `up -d` silently keeps running stale code.

Also vacuumed `/var/log/journal` (`sudo journalctl --vacuum-time=1s`),
freeing 3.9G of pre-migration archived logs that journald was no longer
adding to but also wasn't cleaning up on its own.

**2026-09-04**: while checking on the above, found `watcher`'s app-level log
(`docker/watcherlogs/`) had the same "nobody cleans it up" problem —
636M across four unrotated monthly files, growing ~225M/month. Added
`_prune_old_logs()` (commit `0f48115`), rebuilt and redeployed the `watcher`
container; verified it reopened `September.log` and ran the prune pass
cleanly (no deletions yet, since June–September are all within the 4-month
window it keeps).

## Remaining

None. Tuning check done 2026-09-04 (~1 day of runtime): `journalctl
--disk-usage` reported 136M, well under the 300M `RuntimeMaxUse` cap —
no change needed.

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

### 5. `watcher` app-level log rotation
`watcher/watcher.py` bind-mounts `docker/watcherlogs/` to the host and writes
one JSON line per watched MQTT message to a monthly `<Month>.log` (plus a
paired `<Month>.whitelist.json`). This is independent of journald/docker
logging (items 1-2 above) — it's the application writing its own file
directly, so those changes didn't touch it. It already buffered writes and
flushed on a 5s timer rather than per-message (existing code, not new here),
but nothing ever deleted old months: 636M had piled up across four files
before this fix.

`_prune_old_logs()` now runs whenever a new monthly file is opened (startup +
month rollover) and deletes any `.log`/`.whitelist.json` file whose
last-modified month is `KEEP_MONTHS` (4) or more behind the current month.

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
