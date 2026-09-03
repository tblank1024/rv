# Reducing SD card writes (volatile logging)

Sophie's Pi 5 runs 24/7 off an SD card, which has finite flash write
endurance. Two things were writing to it continuously:

1. **journald** (system logs), persisted to disk by default.
2. **Docker's `json-file` logging driver** (container stdout/stderr),
   `docker/docker-compose.yml`'s previous default.

Both are now redirected to RAM instead.

## What changed

- `docker/docker-compose.yml`: the shared `x-logging` anchor now uses
  `driver: "journald"` instead of `"json-file"`. Container logs go to the
  host's journald rather than a file under `/var/lib/docker/containers/`.
  `docker compose logs -f <service>` still works (it reads through
  journald).
- `journald-volatile.conf` (installed by `install.sh` to
  `/etc/systemd/journald.conf.d/volatile-buffer.conf`): journald keeps logs
  in `/run/log/journal` (tmpfs, RAM) instead of `/var/log/journal` (disk),
  capped to whichever limit hits first:
  - `RuntimeMaxUse=300M`
  - `MaxRetentionSec=129600` (36 hours)
- `webserver/server/server.py`: the Restart and Reboot buttons on the main
  dashboard page now call `_flush_journal_to_disk()` before acting --
  see "Flush on restart/reboot" below.

## Why this is an acceptable tradeoff here

The volatile buffer lives in RAM, so it's lost on a hard power loss. Sophie
is on battery-backed power, so unplanned power loss is rare -- the main
remaining way to lose it is a *planned* restart/reboot, which is covered
below. Since logs here are only needed for debugging problems (not
long-term audit), 36h in RAM covers the normal "something's wrong, let's
look" window without costing any SD wear.

## Flush on restart/reboot

Both buttons call `_flush_journal_to_disk()` in `server.py` first, which
runs (via `nsenter` into the host namespace) `journalctl --sync` and then
copies `/run/log/journal` to `/var/log/journal-last-flush/` -- one small,
infrequent SD write per deliberate restart, versus continuous writes
before. Inspect it after the fact with:

```bash
journalctl --directory=/var/log/journal-last-flush
```

- **Reboot button**: this is the case that matters -- a host reboot wipes
  tmpfs, so without the flush the last 36h of history would be gone right
  when you're most likely rebooting to fix something.
- **Restart Program button**: only restarts the Docker containers, not the
  host, so the RAM-backed journal on the host is untouched either way. The
  flush call is included anyway for consistency and because it's cheap and
  harmless -- it's not load-bearing here the way it is for Reboot.

A reboot triggered outside the web UI (SSH `sudo reboot`, watchdog, power
button) skips this flush, and the `sysrq` fallback reboot path (used only
if the other two reboot methods fail) bypasses systemd shutdown hooks
entirely -- there's no way to guarantee a flush there. Acceptable given
these are the less common paths; the dashboard buttons are the normal way
this Pi gets restarted.

## Installing on Sophie

```bash
cd rv/sdcard-writes
./install.sh
cd ../docker && docker compose up -d   # recreates containers with journald driver
```

## Tuning

`RuntimeMaxUse=300M` and the 36h retention are starting points, not
measured values. After it's been running a day or two:

```bash
journalctl --disk-usage
```

If actual growth means 36h would blow past 300M, raise `RuntimeMaxUse` in
`journald-volatile.conf` and re-run `install.sh` -- there's ample headroom
on an 8GB Pi 5. If growth is unexpectedly high, check `rvc2mqtt`'s
`DEBUG_LEVEL` env var in `docker-compose.yml` first -- it's set to `0`
deliberately; `5` logs every raw CAN frame and would dominate log volume on
its own, independent of where those logs end up.

Mosquitto's persistence (`docker/mqtt/data/`) is unchanged by any of this
-- that's retained-message/subscription *data*, not logs, and its write
volume is low enough that moving it wasn't worth the complexity.
