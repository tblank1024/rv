#!/bin/bash
#
# ft232r-watchdog.sh - keeps the Coolgear USB switch's control chip alive.
#
# WHY THIS EXISTS
# The WAN switch is a Coolgear 4-port hub (Genesys 05e3:0610) whose per-jack
# switching is driven by an FT232R (0403:6001, serial B0033FMU) sitting on the
# hub's OWN port 4. That chip intermittently drops off the USB bus with
# "error from flowcontrol urb" followed by -71 (-EPROTO) on every
# re-enumeration attempt, including the kernel's own port power cycle, ending in
# "unable to enumerate USB device". over_current_count stays 0, so it is not a
# power trip. Observed 2026-10-14 (dead 2.5 days), 2026-10-17 07:45 (20 min
# after recovery), and again at 09:27. Time-to-failure is shrinking.
#
# Symptom when it happens: WAN traffic keeps flowing (the hub's data path is
# fine) but port selection is dead and the debug page cannot reach the switch.
# Restarting the webserver cannot fix it - there is no device to open.
#
# THIS IS MITIGATION, NOT A FIX. The FT232R cannot be bypassed in software:
# verified 2026-10-17 that the hub advertises per-port power switching and
# uhubctl can cycle a port's VBUS, but doing so does NOT bring up a WAN device,
# because Coolgear gates the jacks with its own circuitry downstream of the hub
# ports. The FT232R is the only control path. The real fix is reseating or
# replacing the hardware; prefer a hub whose port power is controlled by the USB
# standard (PPPS + uhubctl) with no auxiliary MCU to fail.
#
# Every recovery is logged and published to MQTT so the degradation stays
# VISIBLE rather than being silently papered over.

HUB_VID=05e3
HUB_PID=0610
FTDI_ID="0403:6001"
DEV_SYMLINK=/dev/coolgear-hub
CTRL_PORT=4                  # hub port holding the FT232R

CHECK_INTERVAL=45
BACKOFF_INTERVAL=300         # used once the rate limit trips
MAX_RECOVERIES=6             # per WINDOW
WINDOW=3600

LOG=/var/log/ft232r-watchdog.log
STATE_DIR=/var/lib/ft232r-watchdog
MQTT_HOST=127.0.0.1
MQTT_BASE=rv/usbhub/ft232r
# The broker runs with allow_anonymous=false, so publishing needs the same
# credentials the containers use. Read them from compose's env file rather than
# embedding a secret in this script. Publishing is best-effort: if the file or
# the broker is unavailable the watchdog still logs and still recovers.
MQTT_ENV=${MQTT_ENV:-/home/tblank/code/tblank1024/rv/docker/.env}

mkdir -p "$STATE_DIR"
TOTAL_FILE=$STATE_DIR/total_recoveries
[ -f "$TOTAL_FILE" ] || echo 0 > "$TOTAL_FILE"

say() { echo "[$(date '+%F %T')] $*" >> "$LOG"; }
# Read credentials without sourcing the file (avoids executing its contents).
load_mqtt_creds() {
    [ -f "$MQTT_ENV" ] || return 1
    MQTT_USER=$(grep -m1 -E '^MQTT_USER=' "$MQTT_ENV" | cut -d= -f2-)
    MQTT_PASS=$(grep -m1 -E '^MQTT_PASS=' "$MQTT_ENV" | cut -d= -f2-)
    [ -n "$MQTT_USER" ] && [ -n "$MQTT_PASS" ]
}
pub() {
    command -v mosquitto_pub >/dev/null || return 0
    [ -n "$MQTT_USER" ] || load_mqtt_creds || return 0
    mosquitto_pub -h "$MQTT_HOST" -u "$MQTT_USER" -P "$MQTT_PASS" \
                  -t "$MQTT_BASE/$1" -m "$2" -r 2>/dev/null
}

# Locate the hub's port-control directory, so this survives re-enumeration and
# does not depend on a hardcoded 1-2 path.
find_ctrl_port_dir() {
    local d hubdev
    for d in /sys/bus/usb/devices/*/; do
        [ -f "$d/idVendor" ] || continue
        [ "$(cat $d/idVendor 2>/dev/null)" = "$HUB_VID" ] || continue
        [ "$(cat $d/idProduct 2>/dev/null)" = "$HUB_PID" ] || continue
        hubdev=$(basename "$d")
        # port dirs live under the hub's interface directory
        for p in "$d"*:1.0/"$hubdev"-port$CTRL_PORT; do
            [ -d "$p" ] && { echo "$p"; return 0; }
        done
    done
    return 1
}

healthy() {
    lsusb | grep -q "$FTDI_ID" || return 1
    [ -e "$DEV_SYMLINK" ] || return 1
    return 0
}

recover() {
    local p; p=$(find_ctrl_port_dir) || { say "ERROR: cannot locate hub $HUB_VID:$HUB_PID port $CTRL_PORT"; return 1; }
    say "FT232R missing - toggling $(basename $p)"
    echo 1 > "$p/disable" 2>/dev/null; sleep 3
    echo 0 > "$p/disable" 2>/dev/null; sleep 9
    if healthy; then
        say "recovered ($DEV_SYMLINK -> $(readlink $DEV_SYMLINK))"
        return 0
    fi
    say "recovery FAILED - chip did not re-enumerate"
    return 1
}

say "================ watchdog start (interval ${CHECK_INTERVAL}s) ================"
pub state starting

declare -a RECENT=()
last_state=""
interval=$CHECK_INTERVAL

while true; do
    now=$(date +%s)
    # prune the rolling window
    pruned=(); for t in "${RECENT[@]}"; do [ $((now - t)) -lt $WINDOW ] && pruned+=("$t"); done
    RECENT=("${pruned[@]}")

    if healthy; then
        [ "$last_state" != "ok" ] && { say "healthy"; pub state ok; last_state=ok; }
        interval=$CHECK_INTERVAL
    else
        if [ "${#RECENT[@]}" -ge "$MAX_RECOVERIES" ]; then
            say "RATE LIMIT: ${#RECENT[@]} recoveries in the last $((WINDOW/60)) min - backing off ${BACKOFF_INTERVAL}s."
            say "  The hardware is failing faster than a watchdog should paper over. Reseat or replace."
            pub state failing
            pub recoveries_in_window "${#RECENT[@]}"
            last_state=failing
            interval=$BACKOFF_INTERVAL
        else
            pub state recovering
            if recover; then
                total=$(( $(cat "$TOTAL_FILE") + 1 )); echo "$total" > "$TOTAL_FILE"
                RECENT+=("$now")
                say "  total recoveries since install: $total"
                pub state recovered
                pub total_recoveries "$total"
                pub last_recovery "$(date '+%F %T')"
                pub recoveries_in_window "${#RECENT[@]}"
                last_state=recovered
            else
                pub state unrecoverable
                last_state=unrecoverable
                interval=$BACKOFF_INTERVAL
            fi
        fi
    fi
    sleep "$interval"
done
