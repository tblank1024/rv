#!/bin/bash
# One-time setup so `sophie-firewall.sh status` doesn't prompt for a password.
# Scoped to that one read-only verb -- apply/docker/revert still need the password,
# so nothing can disable the firewall without one.
#
# Needs an interactive terminal (asks for your password once, to write the
# sudoers rule itself). Run it directly on Sophie, or via:
#   ssh -t tblank@<sophie> '.../firewall/setup-passwordless-sudo.sh'

set -e

if [[ $EUID -eq 0 ]]; then
  echo "Run as a regular user with sudo privileges, not root."
  exit 1
fi

[ -x /usr/local/sbin/sophie-firewall.sh ] || {
  echo "/usr/local/sbin/sophie-firewall.sh not installed yet -- run install.sh first."
  exit 1
}

RULE_FILE="$(mktemp)"
cat > "$RULE_FILE" <<'RULES'
# Installed by firewall/setup-passwordless-sudo.sh -- the status verb only.
# Do NOT widen this to the bare script path or add a wildcard: that would make
# `sophie-firewall.sh revert` (firewall off) a passwordless one-liner.
tblank ALL=(root) NOPASSWD: /usr/local/sbin/sophie-firewall.sh status
RULES

sudo visudo -c -f "$RULE_FILE"
sudo install -m 0440 -o root -g root "$RULE_FILE" /etc/sudoers.d/sophie-firewall
rm -f "$RULE_FILE"
sudo visudo -c
echo "Done. 'sudo sophie-firewall.sh status' no longer prompts for a password."
