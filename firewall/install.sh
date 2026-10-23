#!/bin/bash
# Install the Sophie firewall script and units. Enables them for boot but does NOT
# start them (see plan_firewall.md "Rollout": apply by hand with an auto-revert armed first).
set -euo pipefail
cd "$(dirname "$0")"
[ "$(id -u)" -eq 0 ] || { echo "run as root (sudo $0)"; exit 1; }
install -m 755 sophie-firewall.sh /usr/local/sbin/sophie-firewall.sh
install -m 644 sophie-firewall.service sophie-firewall-docker.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable sophie-firewall.service sophie-firewall-docker.service
echo "installed and enabled (not started). Apply by hand: sophie-firewall.sh apply && sophie-firewall.sh docker"
echo "Optional, as tblank: ./setup-passwordless-sudo.sh  (lets 'sudo sophie-firewall.sh status' skip the password)"
