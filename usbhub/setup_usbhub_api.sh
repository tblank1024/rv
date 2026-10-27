#!/bin/bash
#
# Installs the USB hub port-power service. Run ON the RP5 with sudo:
#   sudo ./setup_usbhub_api.sh
#
# Installs usbhub_ports.py (the driver), usbhub_api.py (the service) and
# map_sockets.py (the socket-mapping tool) into /usr/local/sbin, plus the
# unit. The driver is importable on its own, so the probe can be run by hand
# without the service:
#   sudo /usr/local/sbin/usbhub_ports.py          # raw ports
#   sudo /usr/local/sbin/usbhub_ports.py --sockets # physical sockets
#
# Restarting this service never changes a port: it only reads state at start-up.

set -u

SCRIPT_DEST_DIR="/usr/local/sbin"
SYSTEMD_DEST="/etc/systemd/system"
UNIT="usbhub-api.service"
FILES=(usbhub_ports.py usbhub_api.py map_sockets.py)
SOCKET_MAP="/etc/usbhub/sockets.json"

if [ "$(id -u)" -ne 0 ]; then
  echo "Error: run this with sudo." >&2
  exit 1
fi

for f in "${FILES[@]}" "$UNIT"; do
  [ -f "$f" ] || { echo "Error: '$f' not found in $(pwd)." >&2; exit 1; }
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

# The map is data, not code: never overwrite one that exists, since
# rebuilding it means walking a device round the hub again.
install -d -m 755 -o root -g root "$(dirname "$SOCKET_MAP")" || exit 1

systemctl daemon-reload || exit 1
systemctl enable "$UNIT" >/dev/null 2>&1 || exit 1
systemctl restart "$UNIT" || exit 1
sleep 2
if ! systemctl is-active --quiet "$UNIT"; then
  echo "  ERROR: $UNIT is not active." >&2
  systemctl status "$UNIT" --no-pager | head -12 >&2
  exit 1
fi
echo "  active."
journalctl -u "$UNIT" -n 10 --no-pager 2>/dev/null | grep -iE "version|listening|protected" | tail -3 | sed 's/^/    /'

echo ""
echo "--- Done ---"
echo "Probe the USB tree (this is the command to run once the new hub is in):"
echo "  curl -s http://127.0.0.1:12347/api/hubs | python3 -m json.tool | head -40"
echo "  sudo /usr/local/sbin/usbhub_ports.py          # same thing, human-readable"
echo "Per-port power switching support needs root to determine:"
echo "  sudo uhubctl"
if [ -f "$SOCKET_MAP" ]; then
  echo "Socket map: $SOCKET_MAP"
  echo "  sudo /usr/local/sbin/usbhub_ports.py --sockets"
else
  echo "No socket map yet ($SOCKET_MAP). Physical socket numbers cannot be"
  echo "derived from sysfs, so the map has to be observed."
  echo "If the hub was mapped before and has only MOVED, reapply the stored"
  echo "geometry -- nothing needs unplugging:"
  echo "  sudo /usr/local/sbin/map_sockets.py --relocate"
  echo "Otherwise walk the sockets, plugging one device into each in turn."
  echo "Pass --hubs the hub names as they are RIGHT NOW: they encode the Pi"
  echo "port the hub is in, not anything about the hub, so a name from an old"
  echo "note will be wrong. Read the current ones from /api/hubs, or see"
  echo "usbhub/README.md section 'Bus paths are not stable'."
  echo "Run it twice -- once with a USB 2 device, once with a USB 3 one --"
  echo "giving each socket the same label, so both identities get recorded."
  echo "(In a USB 2 port, as the hub is by choice today, the USB 3 chip does"
  echo "not enumerate: one identity per socket, so one pass is all there is.)"
fi
echo "Logs: journalctl -u $UNIT -f"
exit 0
