#!/bin/bash
#
# Installs the sophie-hostd host-root broker. Run ON the RP5 with sudo:
#   sudo ./setup_sophie_hostd.sh
#
# Installs sophie_hostd.py into /usr/local/sbin and the unit into
# /etc/systemd/system, then enables and (re)starts it. Restarting it never
# changes host state: every endpoint acts only on request, and it holds no
# state of its own. See README.md and rv/TODO.md "Plan: sophie-hostd".
#
# This daemon does NOT by itself drop the webserver's privileges -- that is a
# later, deliberate step (see the plan). Installing it is safe and inert until
# the webserver is pointed at it.

set -u

SCRIPT_DEST_DIR="/usr/local/sbin"
SYSTEMD_DEST="/etc/systemd/system"
UNIT="sophie-hostd.service"
FILES=(sophie_hostd.py)

if [ "$(id -u)" -ne 0 ]; then
  echo "Error: run this with sudo." >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

for f in "${FILES[@]}" "$UNIT"; do
  [ -f "$f" ] || { echo "Error: '$f' not found in $SCRIPT_DIR." >&2; exit 1; }
done

echo "--- Installing $UNIT ---"
for f in "${FILES[@]}"; do
  if [ -f "$SCRIPT_DEST_DIR/$f" ] && ! cmp -s "$f" "$SCRIPT_DEST_DIR/$f"; then
    cp "$SCRIPT_DEST_DIR/$f" "$SCRIPT_DEST_DIR/$f.prev" || exit 1
    echo "  previous $f saved as $SCRIPT_DEST_DIR/$f.prev"
  fi
  install -m 755 -o root -g root "$f" "$SCRIPT_DEST_DIR/$f" || exit 1
done
install -m 644 -o root -g root "$UNIT" "$SYSTEMD_DEST/$UNIT" || exit 1

systemctl daemon-reload || exit 1
systemctl enable "$UNIT" >/dev/null 2>&1 || exit 1
systemctl restart "$UNIT" || exit 1
sleep 2
if ! systemctl is-active --quiet "$UNIT"; then
  echo "  ERROR: $UNIT is not active." >&2
  systemctl status "$UNIT" --no-pager | head -15 >&2
  exit 1
fi
echo "  active."

echo ""
echo "--- Smoke test (loopback, read-only) ---"
curl -s --max-time 8 http://127.0.0.1:12348/api/health && echo
echo "Other reads to try:"
echo "  curl -s http://127.0.0.1:12348/api/containers | python3 -m json.tool | head"
echo "  curl -s http://127.0.0.1:12348/api/firewall   | python3 -m json.tool | head"
echo "Logs: journalctl -u $UNIT -f"
exit 0
