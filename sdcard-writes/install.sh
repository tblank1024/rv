#!/bin/bash
# Configure journald as a RAM-backed (volatile), 36h ring buffer, and point
# it at Sophie's SD card no longer being written to for routine logging.
#
# Rationale: SD cards have finite write endurance and this Pi runs 24/7.
# journald (system logs) and Docker's json-file driver (container logs)
# were both writing continuously to the SD card. Sophie's Pi is on
# battery-backed power, so abrupt power loss -- the one case that would
# lose this RAM-backed buffer -- is rare. A 36h volatile buffer is a good
# tradeoff: covers normal debugging windows, costs no SD wear, and is
# flushed to disk before any deliberate restart/reboot triggered from the
# web UI (see webserver/server/server.py:_flush_journal_to_disk).
#
# Run this on Sophie (the RP5), not on a dev machine.

set -e

if [[ $EUID -eq 0 ]]; then
  echo "Run as a regular user with sudo privileges, not root."
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== Installing volatile journald config (36h RAM-backed ring buffer) ==="
sudo mkdir -p /etc/systemd/journald.conf.d
sudo cp "$SCRIPT_DIR/journald-volatile.conf" /etc/systemd/journald.conf.d/volatile-buffer.conf
sudo systemctl restart systemd-journald
echo "Done. Verify with:"
echo "  journalctl --disk-usage"
echo "  cat /etc/systemd/journald.conf.d/volatile-buffer.conf"

echo
echo "=== Docker container logging ==="
echo "docker-compose.yml's logging driver is now 'journald' (was 'json-file')."
echo "Apply it to running containers with:"
echo "  cd $(dirname "$SCRIPT_DIR")/docker && docker compose up -d"
echo "(each container is recreated so the new log driver takes effect --"
echo " a few seconds of downtime per service, same as any compose update)."

echo
echo "=== Verify no more SD writes from logging ==="
echo "Check journald is confirmed volatile:"
echo "  journalctl --header | grep Storage"
echo "Watch actual RAM usage after it's had time to fill:"
echo "  journalctl --disk-usage"
echo "If it's tracking toward the 300M RuntimeMaxUse cap faster than 36h,"
echo "raise RuntimeMaxUse in journald-volatile.conf, re-run this script, and"
echo "check what's chatty first (rvc2mqtt's DEBUG_LEVEL should stay 0 --"
echo "raw CAN frame logging is the one service that can generate real volume)."
