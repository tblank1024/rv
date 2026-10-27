#!/bin/bash
#
# wan_scan.sh - find a working uplink, powering sockets only while testing.
#
# WHY THIS EXISTS
# pi5connect.sh reconsiders the WAN when NetworkManager raises an interface
# event. That only happens for a device that is POWERED -- an unpowered hub
# socket has no interface and raises nothing. So with one WAN powered at a
# time (the power-saving goal), a better uplink coming back is invisible, and
# a failover has nothing to fail over to.
#
# This script closes that gap without paying standby power: it walks the WAN
# roles in preference order, powering each socket only for as long as it takes
# to test it, and hands the winner to pi5connect.sh to commit.
#
# MEASURED COST OF GATING A SOCKET (why the cheap rejections below matter)
# A powered, already-leased candidate probes in ~3s (2026-10-19 failover test).
# From cold, measured on this hardware the same day by cycling socket 3:
#   +1s   socket powered
#   +17s  USB enumeration (the modem boots firmware and mode-switches)
#   +22s  netdev and carrier
#   +52s  DHCP lease (one clean run). A second attempt was still waiting at
#         +33s when an unrelated exclusivity switch from the dashboard cut the
#         socket, so +52s is the only solid figure -- not evidence of worse.
# So a cold CELLULAR candidate costs roughly 60-90s to test. Wired and WiFi are
# far cheaper: no modem boot, and carrier appears with the netdev.
#
# That is the real price of gating a socket, and it is worse than the 37s the
# 2026-10-17 note records. Carrier is therefore checked before DHCP: carrier==0
# means nothing is on the other end, rejecting an unplugged cable or a
# powered-off Starlink dish in ~10s instead of waiting out the DHCP timeout.
#
# Usage:
#   wan_scan.sh                 look for an uplink BETTER than the current one
#   wan_scan.sh --on-loss       consider every role (use when there is no WAN)
#   wan_scan.sh --cheap         like the default, but only wired and WiFi are
#                               considered: never powers Starlink or cellular.
#                               This is what the 2AM timer runs, so a RV that
#                               travels on cellular moves to a free uplink on
#                               arriving home without ever waking the dish.
#   wan_scan.sh --enforce-gating
#                               no walk and no probing: power OFF every gated
#                               socket that is not carrying the current WAN.
#                               This is the steady state the rest of the script
#                               settles into; pi5connect.sh calls it after it
#                               commits a WAN change, because its own switch
#                               path has no power management of its own.
#   wan_scan.sh --dry-run       log the walk, change nothing
#
# SAFETY
#   - A candidate is powered ALONGSIDE the incumbent, never instead of it, so
#     a working uplink is not dropped to test a speculative one. Exclusivity is
#     the steady state, not an invariant during a scan.
#   - Only sockets with a real WAN role are ever switched. A socket that merely
#     has a display NAME (socket 1, "Wifi") is tested if its interface is
#     already up and otherwise skipped -- never powered off. That is the whole
#     point of keeping names and roles separate.
#   - An EXIT trap powers off every socket this run turned on and did not
#     settle on, and re-powers the incumbent if it somehow ended up off.
#   - pi5connect.sh makes the commit decision, so its gateway detection,
#     pre-commit probe, preference guard and rollback all still apply. This
#     script never touches the routing table itself.
#
set -u

LOGFILE="${LOGFILE:-/var/log/wan-scan.log}"
exec >> "$LOGFILE" 2>&1

HUB_API="${HUB_API:-http://127.0.0.1:12347}"
PI5CONNECT="/usr/local/sbin/pi5connect.sh"
STATE_FILE="/run/pi5connect-wan"
RESULT_FILE="/run/wan-scan-result"
# Set while a WALK is in flight, so pi5connect does not cut a socket that this
# script has deliberately powered up to test. The usbhub README records the
# same race from the dashboard's exclusivity switch killing a modem mid-DHCP.
SCAN_LOCK="/run/wan-scan-in-progress"

# A deliberate choice from the dashboard, written by /api/internet/select as
# "<role> <epoch>".
#
# This exists because choosing a LESS preferred uplink used to be undone within
# 19 seconds. Measured 2026-10-26: selecting cellular powered socket 2 off,
# pi5connect read that as uplink loss, handed off to --on-loss, and this walk
# then tested roles in preference order -- so it powered WIRED back on, won on
# it, and switched the modem's socket off again. The modem was never tested at
# all, because wired outranks it and the walk stops at a winner.
#
# "In force" means: inside MANUAL_GRACE, while the chosen uplink is still
# coming up (a cold modem needs 17s to enumerate, 22s for carrier, 52s for
# DHCP -- see IFACE_WAIT/CARRIER_WAIT/DHCP_WAIT in wan-common.sh), or after
# that only while the choice IS the current WAN. So a choice that never came up
# cannot pin the scan forever: that is the half of this that stops a deliberate
# choice stranding the RV.

# --- Constants shared with pi5connect.sh -----------------------------------
# The modem timeouts, WAN_PREFERENCE and MANUAL_GRACE all live in ONE file now.
# MANUAL_GRACE used to be the literal 120 here and in pi5connect.sh, with no
# statement anywhere that 120 was IFACE_WAIT + CARRIER_WAIT + DHCP_WAIT -- so
# shortening a timeout silently left the grace too long and lengthening one
# left it too short. It is computed from them in wan-common.sh instead.
#
# Sourced defensively; the mirror below is a last resort and says so in the
# log. check_wan_constants.sh asserts it still matches wan-common.sh.
WAN_COMMON="${WAN_COMMON:-/usr/local/sbin/wan-common.sh}"
if [[ -r "$WAN_COMMON" ]]; then
    # shellcheck source=wan-common.sh
    . "$WAN_COMMON"
else
    echo "[$(date)] WARNING: $WAN_COMMON missing; using the inline mirror of the shared constants"
    IFACE_WAIT=35; CARRIER_WAIT=10; DHCP_WAIT=75
    WAN_COLD_START=$(( IFACE_WAIT + CARRIER_WAIT + DHCP_WAIT ))
    MANUAL_GRACE="${MANUAL_GRACE:-$WAN_COLD_START}"
    MANUAL_FILE="${MANUAL_FILE:-/run/wan-manual-choice}"
    MANUAL_FALLBACK="${MANUAL_FALLBACK:-/run/wan-manual-fallback}"
    WAN_PREFERENCE=("wired" "wifi" "starlink" "cellular")
    SOCKET_MAP="${SOCKET_MAP:-/etc/usbhub/sockets.json}"
fi
MANUAL_ROLE=""
SETTLE="${SETTLE:-2}"

MODE="better"
DRYRUN=0
CHEAP=0
for arg in "$@"; do
    case "$arg" in
        --on-loss) MODE="all" ;;
        --enforce-gating) MODE="enforce" ;;
        --cheap) CHEAP=1 ;;
        --dry-run) DRYRUN=1 ;;
        -h|--help) sed -n '3,40p' "$0"; exit 0 ;;
        *) echo "[$(date)] unknown argument: $arg"; exit 2 ;;
    esac
done

log() { echo "[$(date)] $*"; }

if [[ "$(id -u)" -ne 0 ]]; then
    log "ERROR: must run as root"
    exit 1
fi

normalise_role() {
    # Lowercase first. Socket display names are human-written -- the map holds
    # "Wifi" -- and a case-sensitive match silently dropped socket 1 out of the
    # scan entirely on the first run of wan_scan.sh.
    local r="${1,,}"
    case "$r" in
        cell|cellular|lte|4g|5g)  echo cellular ;;
        wired|ethernet|eth|lan)   echo wired ;;
        wifi|wlan|wireless)       echo wifi ;;
        starlink|sat|satellite)   echo starlink ;;
        *)                        echo "$r" ;;
    esac
}

rank_of() {
    local role i=0 p
    role="$(normalise_role "$1")"
    for p in "${WAN_PREFERENCE[@]}"; do
        [[ "$role" == "$p" ]] && { echo "$i"; return 0; }
        i=$((i + 1))
    done
    echo 99
}

# The deliberate choice, if one is in force. Needs CUR_ROLE, so it is only
# called once that is known. Echoes "" when there is no choice to honour.
manual_role() {
    local role stamp now
    [[ -r "$MANUAL_FILE" ]] || return 0
    read -r role stamp < "$MANUAL_FILE" || return 0
    role="$(normalise_role "${role:-}")"
    [[ -n "$role" ]] || return 0
    now="$(date +%s)"
    if [[ -n "${stamp:-}" ]] && (( now - stamp < MANUAL_GRACE )); then
        echo "$role"
        return 0
    fi
    [[ "$role" == "$CUR_ROLE" ]] && echo "$role"
    return 0
}

# "label|role|name|gated|hub:port,hub:port" for every socket.
#
# Pipe-separated, not tab. Tab is an IFS *whitespace* character, so bash
# collapses runs of it and drops empty fields: socket 1 has no role, and
# "1<tab><tab>Wifi<tab>1-2.3:3" read back as role=Wifi, name=1-2.3:3,
# idents=empty. The socket then looked like it had no adapter and was skipped.
socket_table() {
    python3 -I -c '
import json, sys
try:
    data = json.load(open(sys.argv[1]))
except Exception as exc:
    sys.stderr.write("socket map unreadable: %s\n" % exc)
    sys.exit(1)
roles = data.get("wan") or {}
names = data.get("names") or {}
for label, ids in sorted((data.get("sockets") or {}).items()):
    ident = ",".join("%s:%s" % (h, p) for h, p in ids)
    print("|".join([label, roles.get(label, ""), names.get(label, ""),
                     "1" if (data.get("gated") or {}).get(label) else "", ident]))
' "$SOCKET_MAP"
}

port_dir() {
    local hub="$1" port="$2"
    if [[ "$hub" == usb* ]]; then
        echo "/sys/bus/usb/devices/$hub/${hub#usb}-0:1.0/$hub-port$port"
    else
        echo "/sys/bus/usb/devices/$hub/$hub:1.0/$hub-port$port"
    fi
}

# Is every identity of this socket enabled?
socket_is_on() {
    local idents="$1" id hub port dir
    for id in ${idents//,/ }; do
        hub="${id%:*}"; port="${id##*:}"
        dir="$(port_dir "$hub" "$port")"
        [[ "$(cat "$dir/disable" 2>/dev/null)" == "1" ]] && return 1
    done
    return 0
}

# Does any identity of this socket have a device on it?
socket_has_device() {
    local idents="$1" id hub port
    for id in ${idents//,/ }; do
        hub="${id%:*}"; port="${id##*:}"
        [[ -d "/sys/bus/usb/devices/$hub.$port" ]] && return 0
    done
    return 1
}

# Power a socket. Hub API first so its cache is invalidated and the change is
# logged there; direct sysfs as a fallback, because the API being down is
# exactly the situation in which a scan matters.
socket_power() {
    local label="$1" on="$2" idents="$3" id hub port dir
    if [[ "$DRYRUN" == "1" ]]; then
        log "  DRYRUN would power socket $label ${on}"
        return 0
    fi
    if curl -s --max-time 3 -o /dev/null "$HUB_API/api/health" 2>/dev/null; then
        local body='{"socket": "'"$label"'", "on": '"$([[ "$on" == on ]] && echo true || echo false)"'}'
        if curl -s --fail --max-time 15 -X POST "$HUB_API/api/socket" \
                -H 'Content-Type: application/json' -d "$body" >/dev/null 2>&1; then
            log "  socket $label -> $on (hub API)"
            return 0
        fi
        log "  socket $label: hub API refused; falling back to sysfs"
    fi
    local wrote=0
    for id in ${idents//,/ }; do
        hub="${id%:*}"; port="${id##*:}"
        dir="$(port_dir "$hub" "$port")"
        [[ -w "$dir/disable" ]] || continue
        echo "$([[ "$on" == on ]] && echo 0 || echo 1)" > "$dir/disable" 2>/dev/null && wrote=1
    done
    [[ "$wrote" == "1" ]] && log "  socket $label -> $on (sysfs)" || log "  socket $label: could not switch"
}

# Which interface belongs to this socket, by resolving each netdev's USB path.
socket_iface() {
    local idents="$1" n devdir dev hub port id
    for n in /sys/class/net/*; do
        n="$(basename "$n")"
        devdir="$(readlink -f "/sys/class/net/$n/device" 2>/dev/null)" || continue
        [[ -z "$devdir" ]] && continue
        dev="${devdir##*/}"; dev="${dev%%:*}"
        [[ "$dev" == *.* ]] || continue
        hub="${dev%.*}"; port="${dev##*.}"
        for id in ${idents//,/ }; do
            [[ "$id" == "$hub:$port" ]] && { echo "$n"; return 0; }
        done
    done
    return 1
}

CUR_IFACE="$(cut -d' ' -f1 "$STATE_FILE" 2>/dev/null)"
CUR_ROLE=""
CUR_RANK=99
CUR_LABEL=""

# --- restore on any exit --------------------------------------------------
TURNED_ON=()
WINNER=""
WINNER_LABEL=""
cleanup() {
    local label
    rm -f "$SCAN_LOCK"
    for label in "${TURNED_ON[@]:-}"; do
        [[ -z "$label" ]] && continue
        [[ "$label" == "$WINNER_LABEL" ]] && continue
        log "cleanup: powering socket $label back off (tested, not chosen)"
        socket_power "$label" off "${IDENTS[$label]}"
    done
}
trap cleanup EXIT

# Only a walk powers sockets ON, so only a walk needs the interlock. --enforce-gating
# switches things off and never probes, so it does not take it (and must not: it is
# called from pi5connect, which would then skip itself).
[[ "$MODE" != "enforce" ]] && : > "$SCAN_LOCK"

log "===== wan_scan start (mode=$MODE cheap=$CHEAP dryrun=$DRYRUN current=${CUR_IFACE:-none}) ====="

if [[ ! -r "$SOCKET_MAP" ]]; then
    log "ERROR: no socket map at $SOCKET_MAP; nothing to scan"
    echo "error no_socket_map" > "$RESULT_FILE"
    exit 1
fi

declare -A ROLES NAMES IDENTS GATED
CANDIDATES=()
while IFS='|' read -r label role name gated idents; do
    [[ -z "$label" ]] && continue
    ROLES[$label]="$role"; NAMES[$label]="$name"; IDENTS[$label]="$idents"
    GATED[$label]="$gated"
    # A socket counts as a WAN candidate if its role OR its display name
    # places it in the preference list. The name fallback is what lets socket
    # 1 ("Wifi", no role) be considered without making it switchable.
    local_role="${role:-$name}"
    [[ "$(rank_of "$local_role")" == "99" ]] && continue
    CANDIDATES+=("$label")
done < <(socket_table) || { log "ERROR: could not read socket map"; exit 1; }

if [[ ${#CANDIDATES[@]} -eq 0 ]]; then
    log "ERROR: no socket has a WAN role or a recognised WAN name"
    echo "error no_candidates" > "$RESULT_FILE"
    exit 1
fi

# Power off every gated WAN socket except $1. The three skips are the policy:
#   - the socket we are keeping
#   - name-only sockets (socket 1, "Wifi"): a role would put them in the
#     exclusive group and a WAN switch would cut them
#   - sockets that are not gated: cheap ones stay powered on purpose, because a
#     powered adapter raises its own up-event and gets promoted with no scan
# Used by all three paths that settle power, so there is one implementation.
power_off_gated_except() {
    local keep="$1" reason="$2" label role
    for label in "${CANDIDATES[@]}"; do
        [[ "$label" == "$keep" ]] && continue
        [[ -z "${ROLES[$label]}" ]] && continue
        [[ -z "${GATED[$label]:-}" ]] && continue
        # Never cut the socket the user deliberately chose while that choice is
        # in force. This is the exact revert the override exists to stop -- the
        # same class of race as the scan interlock, but caused by preference
        # rather than by timing.
        role="$(normalise_role "${ROLES[$label]}")"
        if [[ -n "$MANUAL_ROLE" && "$role" == "$MANUAL_ROLE" ]]; then
            log "$reason: socket $label ($role) left powered -- manual choice in force"
            continue
        fi
        socket_is_on "${IDENTS[$label]}" || continue
        log "$reason: socket $label off (gated, keeping socket $keep)"
        socket_power "$label" off "${IDENTS[$label]}"
    done
}

if [[ -n "$CUR_IFACE" ]]; then
    for label in "${CANDIDATES[@]}"; do
        if [[ "$(socket_iface "${IDENTS[$label]}" 2>/dev/null)" == "$CUR_IFACE" ]]; then
            CUR_ROLE="$(normalise_role "${ROLES[$label]:-${NAMES[$label]}}")"
            CUR_RANK="$(rank_of "$CUR_ROLE")"
            CUR_LABEL="$label"
            break
        fi
    done
fi
log "current WAN ${CUR_IFACE:-none} role=${CUR_ROLE:-unknown} rank=$CUR_RANK"

MANUAL_ROLE="$(manual_role)"
if [[ -n "$MANUAL_ROLE" ]]; then
    log "manual choice in force: $MANUAL_ROLE -- tested first, never powered off"
fi

# --enforce-gating stops here: make the steady state true and nothing else. It
# never powers a socket ON, never probes and never touches the routing table,
# which is what makes it safe to call from pi5connect's commit path.
#
# Both refusals below are deliberate. "Power off everything that is not the
# current WAN" is only safe when we are sure which socket the current WAN is
# on; if we are not, the socket we would cut could be the one carrying traffic.
# Leaving a modem powered costs about 1 W. Getting this wrong costs the uplink.
if [[ "$MODE" == "enforce" ]]; then
    if [[ -z "$CUR_IFACE" ]]; then
        log "enforce: no current WAN in $STATE_FILE; refusing to power anything off"
        echo "skipped no_wan $(date +%s)" > "$RESULT_FILE"
        exit 0
    fi
    if [[ -z "$CUR_LABEL" ]]; then
        log "enforce: WAN $CUR_IFACE is not on a mapped hub socket; refusing to power anything off"
        echo "skipped unmapped_wan $(date +%s)" > "$RESULT_FILE"
        exit 0
    fi
    power_off_gated_except "$CUR_LABEL" "enforce"
    echo "enforced $CUR_IFACE $CUR_LABEL $(date +%s)" > "$RESULT_FILE"
    log "===== wan_scan done: gating enforced, WAN=$CUR_IFACE socket=$CUR_LABEL ====="
    exit 0
fi

# Preference order, with any deliberate choice promoted to the front so
# --on-loss tests what the user asked for before what the list prefers.
# Deduplicated, or the chosen role would be walked twice.
ORDERED=()
_ordered_seen=" "
for want in ${MANUAL_ROLE:+$MANUAL_ROLE} "${WAN_PREFERENCE[@]}"; do
    for label in "${CANDIDATES[@]}"; do
        [[ "$(normalise_role "${ROLES[$label]:-${NAMES[$label]}}")" == "$want" ]] || continue
        [[ "$_ordered_seen" == *" $label "* ]] && continue
        ORDERED+=("$label")
        _ordered_seen+="$label "
    done
done

for label in "${ORDERED[@]}"; do
    role="$(normalise_role "${ROLES[$label]:-${NAMES[$label]}}")"
    rank="$(rank_of "$role")"
    idents="${IDENTS[$label]}"
    switchable=0
    [[ -n "${ROLES[$label]}" ]] && switchable=1

    # --cheap: wired and WiFi only. Checked before anything is powered, so a
    # skipped role costs nothing (no dish wake-up, no modem boot).
    if [[ "$CHEAP" == "1" && "$role" != "wired" && "$role" != "wifi" ]]; then
        log "socket $label ($role): skipped (--cheap considers only wired and wifi)"
        continue
    fi

    if [[ "$MODE" == "better" ]] && (( rank >= CUR_RANK )); then
        log "socket $label ($role): not better than current ($CUR_ROLE); stopping here"
        break
    fi

    # "No device on this socket" and "this socket is powered off" look
    # IDENTICAL in sysfs -- an unpowered port has no child device either way.
    # So this check is only meaningful while the socket is ON. Treating an off
    # socket as empty made the scan skip every gated socket, which defeats the
    # entire feature: the live test on 2026-10-19 powered the wired socket off
    # and the scan reported "socket 2 (wired): no adapter installed, skipped"
    # and settled for WiFi instead. An off socket has to be powered to find out.
    if socket_is_on "$idents" && ! socket_has_device "$idents"; then
        log "socket $label ($role): powered but nothing plugged in, skipped"
        continue
    fi

    was_on=0
    socket_is_on "$idents" && was_on=1
    if [[ "$was_on" == "0" ]]; then
        if [[ "$switchable" == "0" ]]; then
            log "socket $label ($role): off and not switchable (name only, no role), skipped"
            continue
        fi
        log "socket $label ($role): powering on to test"
        socket_power "$label" on "$idents"
        TURNED_ON+=("$label")
        [[ "$DRYRUN" == "1" ]] && { log "  DRYRUN stops here for $label"; continue; }
        sleep "$SETTLE"
    else
        log "socket $label ($role): already powered"
    fi

    # interface
    iface=""
    for _ in $(seq 1 "$IFACE_WAIT"); do
        iface="$(socket_iface "$idents" 2>/dev/null)" && [[ -n "$iface" ]] && break
        sleep 1
    done
    if [[ -z "$iface" ]]; then
        log "  no interface within ${IFACE_WAIT}s -- socket is empty or the device failed to bind"
        continue
    fi
    log "  interface $iface"

    # carrier -- the cheap rejection
    carrier=0
    for _ in $(seq 1 "$CARRIER_WAIT"); do
        [[ "$(cat "/sys/class/net/$iface/carrier" 2>/dev/null)" == "1" ]] && { carrier=1; break; }
        sleep 1
    done
    if [[ "$carrier" != "1" ]]; then
        log "  no carrier on $iface after ${CARRIER_WAIT}s -- nothing on the other end"
        continue
    fi

    # address
    got_ip=0
    for _ in $(seq 1 "$DHCP_WAIT"); do
        ip -4 addr show "$iface" 2>/dev/null | grep -q 'inet ' && { got_ip=1; break; }
        sleep 1
    done
    if [[ "$got_ip" != "1" ]]; then
        log "  no IPv4 on $iface after ${DHCP_WAIT}s"
        continue
    fi
    log "  $iface has $(ip -4 -br addr show "$iface" | awk '{print $3}')"

    # Hand the decision to pi5connect: it probes before committing, refuses a
    # less-preferred candidate, and rolls back if the commit loses internet.
    if [[ "$DRYRUN" == "1" ]]; then
        # An already-powered socket reaches here without the dry-run check
        # above, so guard the one call that changes the routing table.
        log "  DRYRUN would hand $iface to pi5connect"
        continue
    fi
    log "  handing $iface to pi5connect"
    "$PI5CONNECT" "$iface" up
    sleep "$SETTLE"
    now="$(cut -d' ' -f1 "$STATE_FILE" 2>/dev/null)"
    if [[ "$now" == "$iface" ]]; then
        log "WINNER: socket $label ($role) on $iface"
        WINNER="$iface"; WINNER_LABEL="$label"
        break
    fi
    log "  pi5connect did not take $iface (WAN is ${now:-none}); continuing"
done

if [[ -n "$WINNER" ]]; then
    # Settle. Only GATED losers are powered off -- not every losing role.
    #
    # Measured with a USB meter 2026-10-19: the WiFi adapter is 0.4 W and the
    # cellular modem ~1 W. Powering down a 0.4 W adapter saves 0.8 Ah/day at
    # 12 V, less than a fifth of what the Pi's own rails draw, and it throws
    # away free detection: left powered, carrier or association appears by
    # itself and pi5connect promotes it with no scan and no button. So cheap
    # sockets stay on and only the expensive ones are gated. An earlier
    # version powered off every loser, which was optimising the wrong thing.
    power_off_gated_except "$WINNER_LABEL" "settling"
    # A choice that lost is a choice that could not be honoured. Clear it and
    # record why, so a stale override cannot skew the next walk and so the
    # dashboard can say what happened instead of silently showing the wrong
    # option as active.
    if [[ -n "$MANUAL_ROLE" && "$role" != "$MANUAL_ROLE" ]]; then
        log "manual choice $MANUAL_ROLE could not be honoured; fell back to $role"
        echo "$MANUAL_ROLE $role $(date +%s)" > "$MANUAL_FALLBACK"
        rm -f "$MANUAL_FILE"
    elif [[ -n "$MANUAL_ROLE" ]]; then
        rm -f "$MANUAL_FALLBACK"
    fi
    echo "ok $WINNER $WINNER_LABEL $(date +%s)" > "$RESULT_FILE"
    log "===== wan_scan done: WAN=$WINNER socket=$WINNER_LABEL ====="
    exit 0
fi

# Enforce gating even when nothing changed. In "better" mode the walk stops
# at the first role that is not an improvement, which when the WAN is already
# the best uplink means the settle step below is never reached -- so a gated
# socket powered up by an earlier failover stayed powered indefinitely.
# Measured 2026-10-20: after a failover down to cellular and back to wired,
# the modem was still drawing power because the next scan short-circuited.
if [[ -n "$CUR_LABEL" ]]; then
    power_off_gated_except "$CUR_LABEL" "enforcing gating"
fi

log "no better uplink found; leaving WAN=${CUR_IFACE:-none} as it was"
echo "nochange ${CUR_IFACE:-none} - $(date +%s)" > "$RESULT_FILE"
log "===== wan_scan done: no change ====="
exit 0
