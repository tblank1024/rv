#!/bin/bash
# Install conservative, security-only unattended-upgrades on Sophie.
#
# Why this is safe to run unattended on an RV: it applies ONLY Debian security
# updates, NEVER reboots on its own, and removes nothing. Rationale is in the
# two .conf files next to this script. Run it ON Sophie, not a dev machine.
#
# Prefer running it while on a FREE uplink (wired/WiFi), since the install and
# the first run download packages.

set -e

if [[ $EUID -eq 0 ]]; then
  echo "Run as a regular user with sudo privileges, not root."
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== Installing unattended-upgrades ==="
sudo apt-get update
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y unattended-upgrades

echo "=== Installing Sophie's config ==="
sudo install -m 0644 -o root -g root "$SCRIPT_DIR/20auto-upgrades" \
     /etc/apt/apt.conf.d/20auto-upgrades
sudo install -m 0644 -o root -g root "$SCRIPT_DIR/52unattended-upgrades-sophie.conf" \
     /etc/apt/apt.conf.d/52unattended-upgrades-sophie.conf

echo "=== Verifying the config parses and resolves the security origin ==="
sudo unattended-upgrade --dry-run --debug 2>&1 | \
  grep -iE "allowed origins|Checking|No packages|packages that will be upgraded" | head -20

echo
echo "Done. Confirm the timer is active:"
echo "  systemctl list-timers apt-daily-upgrade.timer --no-pager"
echo "Read outcomes later with:"
echo "  cat /var/log/unattended-upgrades/unattended-upgrades.log"
