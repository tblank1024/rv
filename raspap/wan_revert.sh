#!/bin/bash
#
# wan_revert.sh - timed auto-revert watchdog for WAN rewiring work.
#
# Purpose: while the USB uplinks are being physically rewired, this runs as a
# systemd unit (so it survives the SSH session that armed it) and restores
# *some* working WAN if the RV is left with none. It is the "a mistake restores
# itself" layer that CLAUDE.md asks for before touching the live uplink.
#
# Usage (run with sudo, on the RP5):
#   ./wan_revert.sh arm [MINUTES]   snapshot the known-good state and start the
#                                   watchdog (default 90 minutes, then it exits)
#   ./wan_revert.sh disarm          stop it
#   ./wan_revert.sh status          snapshot vs. now, and whether it is armed
#   ./wan_revert.sh check           probe only; exit 0 if the RV has internet
#   ./wan_revert.sh revert          run the recovery ladder once, right now
#   ./wan_revert.sh watch MINUTES   the loop itself (what systemd runs)
#
# Overrides (sudo strips the environment, so pass them through `env`:
#   sudo env WAN_REVERT_DRYRUN=1 ./wan_revert.sh arm 10):
#   WAN_REVERT_DRYRUN=1   log every action but change nothing (test it safely)
#   WAN_REVERT_REBOOT=1   reboot as the final rung if the ladder fails outright.
#                         OFF by default: a reboot restores the *boot-time*
#                         config, which after rewiring no longer matches the
#                         hardware, so it is as likely to hurt as help.
#   WAN_REVERT_GRACE=120  seconds before the first check, so it does not fight
#                         you while an adapter is out of its socket
#   WAN_REVERT_FAILS=3    consecutive failed checks before the ladder runs
#
# What it will NEVER touch: br0, eth0, wlan0, hostapd. The control path (your
# SSH over br0) is independent of the uplink by design and must stay that way.
#
set -u

SELF="$(readlink -f "$0")"
LOGFILE="/var/log/wan-revert.log"
STATE_DIR="/var/lib/wan-revert"
SNAPSHOT="$STATE_DIR/snapshot.txt"
UNIT="wan-revert"

PI5CONNECT="/usr/local/sbin/pi5connect.sh"
HUB_API="http://127.0.0.1:12347"
SOCKET_MAP="/etc/usbhub/sockets.json"
SELF_AP_SSID="Sophie"            # joining our own AP loops the uplink back

# Same probe targets and reasoning as pi5connect.sh v2.1: IP literals, because
# a hostname probe fails when DNS is broken, which is the case a bad WAN makes.
PROBE_TARGETS=("1.1.1.1" "8.8.8.8")
PROBE_URLS=("http://1.1.1.1/" "http://204.79.197.200/")
PROBE_COUNT=2
PROBE_WAIT=2
PROBE_HTTP_TIMEOUT=6

# Never candidates: the AP side of the box.
AP_SIDE=("lo" "eth0" "wlan0" "br0" "docker0")

GRACE="${WAN_REVERT_GRACE:-120}"
FAIL_THRESHOLD="${WAN_REVERT_FAILS:-3}"
CHECK_INTERVAL=60
RECOVER_SETTLE=45
DRYRUN="${WAN_REVERT_DRYRUN:-0}"

log() { echo "[$(date)] $*" | tee -a "$LOGFILE" >&2; }

run() {
    if [[ "$DRYRUN" == "1" ]]; then
        log "  DRYRUN would run: $*"
        return 0
    fi
    "$@"
}

need_root() {
    if [[ "$(id -u)" -ne 0 ]]; then
        echo "Error: $1 needs root. Re-run with sudo." >&2
        exit 1
    fi
}

is_ap_side() {
    local iface="$1"
    for ap in "${AP_SIDE[@]}"; do
        [[ "$iface" == "$ap" ]] && return 0
    done
    ip link show "$iface" 2>/dev/null | grep -q "master br0" && return 0
    return 1
}

# --- probing -----------------------------------------------------------------

probe_default() {
    local target url
    for target in "${PROBE_TARGETS[@]}"; do
        ping -c "$PROBE_COUNT" -W "$PROBE_WAIT" "$target" >/dev/null 2>&1 && return 0
    done
    for url in "${PROBE_URLS[@]}"; do
        curl -4 -s -o /dev/null --max-time "$PROBE_HTTP_TIMEOUT" "$url" >/dev/null 2>&1 && return 0
    done
    return 1
}

# --- hub sockets -------------------------------------------------------------

# A socket's (hub, port) identities, one per line: "<label> <hub> <port>".
# USB 2 and USB 3 lanes of one socket are separate hubs, so a socket has two.
socket_identities() {
    [[ -r "$SOCKET_MAP" ]] || return 1
    python3 -I -c '
import json, sys
try:
    data = json.load(open(sys.argv[1]))
except Exception as exc:
    sys.stderr.write("socket map unreadable: %s\n" % exc)
    sys.exit(1)
for label, ids in sorted((data.get("sockets") or {}).items()):
    for hub, port in ids:
        print(label, hub, port)
' "$SOCKET_MAP"
}

port_dir() {
    local hub="$1" port="$2"
    if [[ "$hub" == usb* ]]; then
        # Root hub: usb3 -> /sys/bus/usb/devices/usb3/3-0:1.0/usb3-port1
        echo "/sys/bus/usb/devices/$hub/${hub#usb}-0:1.0/$hub-port$port"
    else
        echo "/sys/bus/usb/devices/$hub/$hub:1.0/$hub-port$port"
    fi
}

# Power on every mapped socket. Turning a socket ON can never cut anything, so
# this ignores the protection list on purpose -- the point is to make whatever
# is plugged in enumerate so pi5connect has a candidate to probe.
sockets_all_on() {
    local labels label hub port dir did=0
    labels="$(socket_identities | awk '{print $1}' | sort -u)"
    if [[ -z "$labels" ]]; then
        log "  no socket map at $SOCKET_MAP; skipping hub power-on"
        return 1
    fi

    # Preferred path: the hub API, which logs and invalidates its own cache.
    if curl -s --max-time 3 -o /dev/null "$HUB_API/api/health" 2>/dev/null; then
        local total=0
        for label in $labels; do
            total=$((total + 1))
            if [[ "$DRYRUN" == "1" ]]; then
                log "  DRYRUN would POST $HUB_API/api/socket {socket:$label,on:true}"
                continue
            fi
            # --fail so an HTTP error is not counted as a success.
            if curl -s --fail --max-time 10 -X POST "$HUB_API/api/socket" \
                    -H 'Content-Type: application/json' \
                    -d "{\"socket\": \"$label\", \"on\": true}" >/dev/null 2>&1; then
                did=$((did + 1))
            else
                log "  socket $label: hub API refused or timed out"
            fi
        done
        if [[ "$DRYRUN" == "1" ]]; then
            log "  DRYRUN: would have powered on $total sockets via the hub API"
        else
            log "  hub API: powered on $did/$total sockets"
        fi
        return 0
    fi

    # Fallback: write sysfs directly. We are root, and the API being down is
    # exactly the kind of thing that happens mid-rewire.
    log "  hub API unreachable; writing sysfs directly"
    while read -r label hub port; do
        [[ -n "$label" ]] || continue
        dir="$(port_dir "$hub" "$port")"
        if [[ ! -w "$dir/disable" ]]; then
            log "  socket $label: $dir/disable not writable, skipped"
            continue
        fi
        if [[ "$DRYRUN" == "1" ]]; then
            log "  DRYRUN would write 0 > $dir/disable (socket $label)"
        else
            echo 0 > "$dir/disable" 2>/dev/null && did=$((did + 1))
        fi
    done < <(socket_identities)
    if [[ "$DRYRUN" == "1" ]]; then
        log "  DRYRUN: would have enabled the port identities listed above"
    else
        log "  sysfs: enabled $did port identities"
    fi
    return 0
}

# --- the Alfa's -110 probe failure -------------------------------------------

# mt76x2u reads the ASIC revision and then times out uploading firmware
# (seen 2026-10-18: "probe with driver mt76x2u failed with error -110" after
# the hub re-enumerated). Nothing retries it, so the adapter sits enumerated
# with no driver and no wlan1. Deauthorize/reauthorize re-runs the probe and
# touches nothing else on the bus.
rebind_stalled_wifi() {
    local dev iface found=0
    for dev in /sys/bus/usb/devices/[0-9]*-*; do
        [[ -d "$dev" ]] || continue
        [[ "$(basename "$dev")" == *:* ]] && continue
        [[ "$(cat "$dev/idVendor" 2>/dev/null)" == "0e8d" ]] || continue
        [[ "$(cat "$dev/idProduct" 2>/dev/null)" == "7612" ]] || continue

        # Bound already? Then this is not the fault we are fixing.
        local bound=0
        for iface in "$dev":*; do
            [[ -e "$iface/driver" ]] && bound=1
        done
        if [[ "$bound" == "1" ]]; then
            log "  $(basename "$dev"): mt76x2u already bound, nothing to do"
            continue
        fi

        log "  $(basename "$dev"): MT7612U with no driver -- re-authorizing"
        found=1
        run bash -c "echo 0 > '$dev/authorized'"
        sleep 2
        run bash -c "echo 1 > '$dev/authorized'"
        sleep 8
    done
    [[ "$found" == "1" ]]
}

# --- WiFi --------------------------------------------------------------------

# Saved WiFi profiles in autoconnect-priority order, highest first, excluding
# our own AP (a loop) and NM's untouched "preconfigured" stub.
wifi_profiles() {
    nmcli -t -f NAME,TYPE,AUTOCONNECT-PRIORITY connection show 2>/dev/null \
        | awk -F: -v self="$SELF_AP_SSID" '
            $2 == "802-11-wireless" && $1 != "preconfigured" && $1 !~ self \
                { printf "%s\t%s\n", $3, $1 }' \
        | sort -t$'\t' -k1,1nr | cut -f2
}

bring_up_wifi() {
    local iface="wlan1" profile
    if [[ ! -d "/sys/class/net/$iface" ]]; then
        log "  no $iface; WiFi rung not available"
        return 1
    fi
    run ip link set "$iface" up
    run nmcli radio wifi on
    while read -r profile; do
        [[ -n "$profile" ]] || continue
        log "  trying WiFi profile: $profile"
        if [[ "$DRYRUN" == "1" ]]; then
            log "  DRYRUN would run: nmcli connection up id $profile ifname $iface"
            continue
        fi
        if nmcli connection up id "$profile" ifname "$iface" >/dev/null 2>&1; then
            log "  $profile is up on $iface"
            sleep 5
            return 0
        fi
        log "  $profile failed"
    done < <(wifi_profiles)
    return 1
}

# --- wired -------------------------------------------------------------------

# An adapter that lands on a new name (eth2) has no profile: "Wired connection
# 1" is pinned to connection.interface-name=eth1, not to a MAC. NM normally
# auto-creates a default wired profile, but not if it is already managing the
# device in a disconnected state -- so ask it explicitly.
connect_wired() {
    local iface carrier acted=0
    for iface in /sys/class/net/*; do
        iface="$(basename "$iface")"
        is_ap_side "$iface" && continue
        [[ -d "/sys/class/net/$iface/wireless" ]] && continue
        [[ "$iface" == can* || "$iface" == veth* || "$iface" == br-* ]] && continue
        carrier="$(cat "/sys/class/net/$iface/carrier" 2>/dev/null || echo 0)"
        [[ "$carrier" == "1" ]] || continue
        if ip -4 addr show "$iface" 2>/dev/null | grep -q 'inet '; then
            log "  $iface already has an IPv4 address"
            continue
        fi
        log "  $iface has carrier but no IPv4 -- asking NM to connect it"
        run nmcli device connect "$iface"
        acted=1
    done
    [[ "$acted" == "1" ]] && sleep 10
    [[ "$acted" == "1" ]]
}

# --- the ladder --------------------------------------------------------------

# Least-disruptive first, re-probing after every rung so it stops as soon as
# the RV has internet again.
revert_ladder() {
    log "RECOVERY LADDER starting (dryrun=$DRYRUN)"

    log "rung 1: NetworkManager on, re-run pi5connect"
    run nmcli networking on
    if [[ -x "$PI5CONNECT" ]]; then
        run "$PI5CONNECT"
    else
        log "  $PI5CONNECT missing or not executable"
    fi
    sleep 5
    probe_default && { log "RECOVERED after rung 1"; return 0; }

    log "rung 2: power on every mapped hub socket"
    sockets_all_on
    sleep 15
    run "$PI5CONNECT"
    sleep 5
    probe_default && { log "RECOVERED after rung 2"; return 0; }

    log "rung 3: re-authorize a stalled MT7612U (the -110 failure)"
    rebind_stalled_wifi
    probe_default && { log "RECOVERED after rung 3"; return 0; }

    log "rung 4: bring up a saved WiFi profile on wlan1"
    bring_up_wifi
    run "$PI5CONNECT"
    sleep 5
    probe_default && { log "RECOVERED after rung 4"; return 0; }

    log "rung 5: connect any wired adapter with carrier but no address"
    connect_wired
    run "$PI5CONNECT"
    sleep 5
    probe_default && { log "RECOVERED after rung 5"; return 0; }

    log "rung 6: force pi5connect to take any candidate"
    PI5_FORCE=1 run "$PI5CONNECT"
    sleep 10
    probe_default && { log "RECOVERED after rung 6"; return 0; }

    log "LADDER EXHAUSTED -- the RV still has no internet."
    log "  br0, eth0, wlan0 and hostapd were not touched; SSH over br0 should work."
    log "  Snapshot of the last known-good state: $SNAPSHOT"
    if [[ "${WAN_REVERT_REBOOT:-0}" == "1" ]]; then
        log "  WAN_REVERT_REBOOT=1 -- rebooting in 10s"
        run bash -c "sleep 10; systemctl reboot" &
    fi
    return 1
}

# --- snapshot ----------------------------------------------------------------

take_snapshot() {
    mkdir -p "$STATE_DIR"
    {
        echo "# wan-revert snapshot taken $(date)"
        echo "# This is the state that was working before the rewire."
        echo
        echo "== pi5connect WAN =="
        cat /run/pi5connect-wan 2>/dev/null || echo "(no state file)"
        echo
        echo "== default route =="
        ip route show default
        echo
        echo "== addresses =="
        ip -4 -br addr
        echo
        echo "== NM active =="
        nmcli -t -f NAME,DEVICE,STATE connection show --active 2>/dev/null
        echo
        echo "== USB devices =="
        lsusb 2>/dev/null
        echo
        echo "== USB tree =="
        lsusb -t 2>/dev/null
        echo
        echo "== netdev -> USB path =="
        for n in /sys/class/net/*; do
            n="$(basename "$n")"
            p="$(readlink -f "/sys/class/net/$n/device" 2>/dev/null)"
            [[ "$p" == *usb* ]] && echo "$n ${p#/sys/devices/}"
        done
        echo
        echo "== hub sockets =="
        curl -s --max-time 5 "$HUB_API/api/sockets" 2>/dev/null \
            | python3 -I -m json.tool 2>/dev/null \
            || echo "(hub API unreachable or returned non-JSON)"
        echo
    } > "$SNAPSHOT"
    log "snapshot written to $SNAPSHOT"
}

# --- the watchdog loop -------------------------------------------------------

watch_loop() {
    local minutes="${1:-90}"
    local deadline=$(( $(date +%s) + minutes * 60 ))
    local fails=0 was_up=1

    log "WATCHDOG armed for ${minutes}m (grace ${GRACE}s, ${FAIL_THRESHOLD} failed"
    log "  checks of ${CHECK_INTERVAL}s before acting, dryrun=$DRYRUN)"
    sleep "$GRACE"

    while [[ "$(date +%s)" -lt "$deadline" ]]; do
        if probe_default; then
            [[ "$was_up" == "0" ]] && log "internet is back"
            was_up=1
            fails=0
        else
            was_up=0
            fails=$((fails + 1))
            log "no internet (failed check $fails/$FAIL_THRESHOLD)"
            log "  WAN=$(cat /run/pi5connect-wan 2>/dev/null || echo none)" \
                "route=$(ip route show default | tr '\n' ';' | sed 's/;$//' || true)"
            log "  up with IPv4: $(ip -4 -br addr | awk '$2=="UP"{print $1}' | tr '\n' ' ')"
            log "  uplink netdevs: $(ls /sys/class/net | grep -E '^(eth|wlan|usb)' | tr '\n' ' ')"
            if [[ "$fails" -ge "$FAIL_THRESHOLD" ]]; then
                revert_ladder
                fails=0
                sleep "$RECOVER_SETTLE"
            fi
        fi
        sleep "$CHECK_INTERVAL"
    done

    if probe_default; then
        log "WATCHDOG disarming after ${minutes}m: internet is up. Done."
    else
        log "WATCHDOG deadline reached with no internet; one last ladder run"
        revert_ladder
        log "WATCHDOG disarming after ${minutes}m."
    fi
}

# --- commands ----------------------------------------------------------------

case "${1:-}" in
  arm)
    need_root arm
    MINUTES="${2:-90}"
    if ! [[ "$MINUTES" =~ ^[0-9]+$ ]] || [[ "$MINUTES" -lt 1 ]]; then
        echo "Error: MINUTES must be a positive integer." >&2; exit 2
    fi
    if systemctl is-active --quiet "$UNIT" 2>/dev/null; then
        echo "Already armed. 'disarm' first, or 'status' to see it." >&2; exit 1
    fi
    if ! probe_default; then
        echo "Refusing to arm: there is no internet right now, so the watchdog" >&2
        echo "cannot tell a rewiring mistake from the state it started in." >&2
        echo "Fix the uplink first, or run '$0 revert' by hand." >&2
        exit 1
    fi
    take_snapshot
    systemd-run --unit="$UNIT" --collect --service-type=simple \
        --setenv=WAN_REVERT_DRYRUN="$DRYRUN" \
        --setenv=WAN_REVERT_REBOOT="${WAN_REVERT_REBOOT:-0}" \
        --setenv=WAN_REVERT_GRACE="$GRACE" \
        --setenv=WAN_REVERT_FAILS="$FAIL_THRESHOLD" \
        "$SELF" watch "$MINUTES" >/dev/null || {
            echo "Error: systemd-run failed; nothing is armed." >&2; exit 1; }
    echo "Armed for ${MINUTES} minutes as unit '$UNIT'."
    echo "  watch:  journalctl -u $UNIT -f   (or tail -f $LOGFILE)"
    echo "  stop:   sudo $0 disarm"
    ;;

  disarm)
    need_root disarm
    systemctl stop "$UNIT" 2>/dev/null
    systemctl reset-failed "$UNIT" 2>/dev/null
    log "WATCHDOG disarmed by hand"
    echo "Disarmed."
    ;;

  status)
    if systemctl is-active --quiet "$UNIT" 2>/dev/null; then
        echo "ARMED (unit $UNIT)"
        systemctl show -p ExecMainStartTimestamp --value "$UNIT"
    else
        echo "not armed"
    fi
    echo
    echo "--- internet now ---"
    if probe_default; then echo "UP"; else echo "DOWN"; fi
    echo "WAN=$(cat /run/pi5connect-wan 2>/dev/null || echo none)"
    ip route show default
    echo
    if [[ -r "$SNAPSHOT" ]]; then
        echo "--- snapshot ($SNAPSHOT) ---"
        sed -n '1,12p' "$SNAPSHOT"
        echo "    [...] full file: $SNAPSHOT"
    else
        echo "no snapshot yet (run 'arm')"
    fi
    ;;

  check)
    if probe_default; then echo "UP"; exit 0; else echo "DOWN"; exit 1; fi
    ;;

  revert)
    need_root revert
    revert_ladder
    ;;

  watch)
    need_root watch
    watch_loop "${2:-90}"
    ;;

  *)
    sed -n '3,30p' "$SELF"
    exit 2
    ;;
esac
