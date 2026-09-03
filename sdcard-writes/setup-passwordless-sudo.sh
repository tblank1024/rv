#!/bin/bash
# One-time setup so install.sh's `sudo` calls don't prompt for a password.
# Scoped to exactly the commands install.sh runs -- not blanket sudo access.
#
# Needs an interactive terminal (asks for your password once, to write the
# sudoers rule itself). Run it directly on Sophie, or via:
#   ssh -t tblank@192.168.2.196 '.../sdcard-writes/setup-passwordless-sudo.sh'

set -e

if [[ $EUID -eq 0 ]]; then
  echo "Run as a regular user with sudo privileges, not root."
  exit 1
fi

RULE_FILE="$(mktemp)"
cat > "$RULE_FILE" <<'RULES'
# Installed by sdcard-writes/setup-passwordless-sudo.sh -- scoped to the
# exact commands sdcard-writes/install.sh runs, nothing broader.
tblank ALL=(root) NOPASSWD: /usr/bin/mkdir -p /etc/systemd/journald.conf.d
tblank ALL=(root) NOPASSWD: /usr/bin/cp * /etc/systemd/journald.conf.d/volatile-buffer.conf
tblank ALL=(root) NOPASSWD: /usr/bin/systemctl restart systemd-journald
RULES

sudo visudo -c -f "$RULE_FILE"
sudo install -m 0440 -o root -g root "$RULE_FILE" /etc/sudoers.d/tblank-journald-volatile
rm -f "$RULE_FILE"
sudo visudo -c
echo "Done. install.sh's mkdir/cp/systemctl-restart-journald calls no longer prompt for a password."
