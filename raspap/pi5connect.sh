#!/bin/bash
#
# pi5connect.sh - selects the RV's WAN uplink and configures NAT for the bridge.
# Triggered by /etc/NetworkManager/dispatcher.d/99-pi5connect on interface
# up/down/connectivity-change, and by setup-bridge.sh at boot (no args).
#
# v2.2 changes (2026-10-19):
#   1. A "down" event now PROMOTES A REPLACEMENT. Up to v2.1 it removed the
#      rules and exited, so the RV sat with no WAN until some other interface
#      happened to fire its own up/dhcp4-change -- which an already-up
#      interface never does. Each candidate is tried by re-running this script
#      with "up", so all the probe/commit/rollback logic applies unchanged.
#   2. iface_has_ip no longer requires operstate "UP". A cdc_ether cellular
#      modem sits at "state UNKNOWN" while working, so eth1 was invisible as a
#      candidate AND the incumbent-health guard thought the live WAN was dead.
#   3. probe_iface installs a temporary /32 route to each probe endpoint via
#      the candidate's gateway. Without it a standby candidate is unprobeable:
#      it has no default route of its own (this script deletes all but one) and
#      SO_BINDTODEVICE confines lookup to routes on the device, so the probe
#      failed for every healthy standby. Found by a live failover test.
#   4. A WAN PREFERENCE ORDER (wired > wifi > starlink > cellular). A healthy
#      incumbent is displaced only by a strictly more preferred candidate, so
#      wired reclaims the route when it returns instead of leaving the RV on
#      metered cellular. Roles come from the hub socket map, not interface
#      names, which drift. Failover tries candidates in this order too, and
#      hands off to wan_scan.sh when no POWERED candidate works, since a
#      gated socket has no interface for the loop to find.
#      Verified live 2026-10-19: forced onto cellular, then a wired "up"
#      logged "Promoting eth2 (wired) over healthy eth1 (cell)" and switched
#      in ~2s; cellular and wifi each offering themselves against healthy
#      wired were both refused as "not preferred".
#      CAVEAT: promotion only fires for a candidate whose socket is POWERED,
#      because an unpowered socket has no interface to raise an event. With
#      one-WAN-at-a-time power that is the minority of cases -- see the
#      scan-on-demand design discussion.
#   5. is_ap_side excludes virtual interfaces by shape (br-*, veth*, can*,
#      tun*, any bridge), not just by the five hardcoded names. The broader
#      failover search would otherwise probe docker's per-network bridges.
#
# v2.1 changes (2026-10-17) - see Results_WiFi_testing.md / WifitoHostBridge:
#   1. A candidate WAN is PROBED before it is committed. v2.0 accepted any
#      interface with a gateway, deleted every default route and pointed NAT at
#      it. On 2026-10-06 and 2026-10-13 that silently handed the RV's WAN to a
#      192.168.0.0/24 network while the house LAN was 192.168.2.0/24.
#   2. A working incumbent WAN is no longer preempted by an untested candidate.
#      Set PI5_FORCE=1 to override.
#   3. Rollback: if the commit somehow ends with no internet, the previous
#      default route and rules are restored instead of leaving the RV dark.
#   4. The guessed-gateway path is kept but can no longer take effect unproven,
#      because the probe runs against the candidate device before committing.
#
# Overrides (so a travel device is never un-fixable):
#   PI5_FORCE=1       switch to the candidate even if the incumbent is healthy
#   PI5_SKIP_PROBE=1  accept the candidate without probing (use when a network
#                     blocks both ICMP and HTTP to the probe endpoints)
#
# Probe note: ping -I <dev> uses SO_BINDTODEVICE, so route lookup is restricted
# to routes on that device. A candidate whose gateway was guessed has no default
# route on its device and therefore fails the probe, which is the intent.
# Known limitation: a captive portal answers the probe and still looks healthy.

SCRIPT_VERSION="2.4"   # 2.4: flock around the whole invocation (see LOCK_FILE)
LOGFILE="/var/log/pi5connect.log"
exec >> $LOGFILE 2>&1
echo "[$(date)] pi5connect.sh triggered: iface=${1:-unset} status=${2:-unset}"

LAN_IFACE="br0"
STATE_FILE="/run/pi5connect-wan"

# Probe settings
PROBE_TARGETS=("1.1.1.1" "8.8.8.8")
# IP literals on purpose: a hostname probe fails when DNS is broken, which is
# exactly the case a misconfigured WAN produces. RaspAP adblock also blocks
# connectivity-check.gstatic.com on this host, so that target never resolved.
# Any HTTP response (even 400) proves the TCP path works.
PROBE_URLS=("http://1.1.1.1/" "http://204.79.197.200/")
# The same endpoints as bare addresses. probe_iface installs a /32 route
# to each via the candidate's gateway for the duration of the probe.
PROBE_HOSTS=("1.1.1.1" "8.8.8.8" "204.79.197.200")
PROBE_COUNT=2
PROBE_WAIT=2
PROBE_HTTP_TIMEOUT=6

# Interfaces that are never WAN
AP_SIDE=("lo" "eth0" "wlan0" "br0" "docker0")

# --- Constants shared with wan_scan.sh -------------------------------------
# WAN_PREFERENCE, MANUAL_GRACE, MANUAL_FILE and SOCKET_MAP live in ONE file so
# they cannot drift between the two scripts, and so MANUAL_GRACE can be derived
# from the modem timings rather than restated as a literal. See wan-common.sh
# for the reasoning behind each value.
#
# Sourced defensively, in the same spirit as the `[[ -x "$WAN_SCAN" ]]` guards
# below: this runs from a NetworkManager dispatcher, so dying because a
# constants file is absent would leave the RV with no uplink -- far worse than
# a stale constant. The mirror below is a last resort and says so in the log;
# check_wan_constants.sh asserts it still matches wan-common.sh.
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

# The WAN role of an interface, resolved through the hub socket its device is
# plugged into. Deliberately NOT keyed on the interface name: names here are
# driver-dependent and drift -- the wired adapter was eth1 and then eth2 inside
# one day, and cellular took over eth1.
#
# Falls back to the socket's display NAME when it has no role, because socket 1
# (the WiFi adapter) is named "Wifi" but deliberately carries no WAN role: a
# role would put it in the exclusive group and a WAN switch would cut it. For
# ranking the name is the right answer; for switching, the absent role is.
iface_role() {
    local iface="$1" devdir dev hub port
    devdir="$(readlink -f "/sys/class/net/$iface/device" 2>/dev/null)"
    [[ -z "$devdir" ]] && return 0
    dev="${devdir##*/}"               # 1-2.3.2:1.0
    dev="${dev%%:*}"                  # 1-2.3.2
    [[ "$dev" == *.* ]] || return 0    # on a root port, so not on the hub
    hub="${dev%.*}"                   # 1-2.3
    port="${dev##*.}"                 # 2
    [[ -r "$SOCKET_MAP" ]] || return 0
    python3 -I -c '
import json, sys
path, hub, port = sys.argv[1], sys.argv[2], int(sys.argv[3])
try:
    data = json.load(open(path))
except Exception:
    sys.exit(0)
roles = data.get("wan") or {}
names = data.get("names") or {}
for label, ids in (data.get("sockets") or {}).items():
    for h, p in ids:
        if h == hub and int(p) == port:
            print((roles.get(label) or names.get(label) or "").lower())
            sys.exit(0)
' "$SOCKET_MAP" "$hub" "$port"
}

# Role spellings differ between the socket map and ordinary speech: the map
# says "cell", the preference list says "cellular". Normalise before ranking.
# Found on the first test of this code -- "cell" matched nothing and cellular
# silently fell to unknown-rank, which only LOOKED correct because unknown
# sorts last anyway. A second unclassified uplink would have exposed it.
normalise_role() {
    # Lowercase first. Socket display names are human-written -- the map holds
    # "Wifi" -- and a case-sensitive match silently dropped socket 1 out of the
    # scan entirely on the first run of wan_scan.sh.
    local r="${1,,}"
    case "$r" in
        cell|cellular|lte|4g|5g)      echo cellular ;;
        wired|ethernet|eth|lan)       echo wired ;;
        wifi|wlan|wireless)           echo wifi ;;
        starlink|sat|satellite)       echo starlink ;;
        *)                            echo "$r" ;;
    esac
}

# The deliberate choice, if one is in force, else "".
#
# Inside the grace window the choice stands unconditionally, because the uplink
# it names may still be coming up -- a cold modem needs ~90s. After that it
# stands only while it IS the WAN, so a choice that never came up cannot pin
# the ranking forever and leave the RV on nothing.
manual_role() {
    local role stamp now cur
    [[ -r "$MANUAL_FILE" ]] || return 0
    read -r role stamp < "$MANUAL_FILE" || return 0
    role="$(normalise_role "${role:-}")"
    [[ -n "$role" ]] || return 0
    now="$(date +%s)"
    if [[ -n "${stamp:-}" ]] && (( now - stamp < MANUAL_GRACE )); then
        echo "$role"
        return 0
    fi
    cur="$(cut -d" " -f1 "$STATE_FILE" 2>/dev/null)"
    [[ -n "$cur" ]] && [[ "$(normalise_role "$(iface_role "$cur")")" == "$role" ]] \
        && echo "$role"
    return 0
}

# Rank of a role; lower is better. An unknown role ranks worst, so an
# unclassified interface can never displace a classified one.
iface_rank() {
    local role i=0 p
    role="$(normalise_role "$1")"
    # A deliberate choice outranks the whole preference list, which is the
    # point: without this, picking cellular while wired is plugged in is
    # reverted, because wired ranks better and a healthy better-ranked
    # candidate is exactly what this script promotes.
    if [[ -n "$MANUAL_ROLE" && "$role" == "$MANUAL_ROLE" ]]; then
        echo -1
        return 0
    fi
    for p in "${WAN_PREFERENCE[@]}"; do
        [[ "$role" == "$p" ]] && { echo "$i"; return 0; }
        i=$((i + 1))
    done
    echo 99
}

# Interfaces from $* reordered best-preference first. A stable sort, so
# same-rank interfaces keep the order they came in.
rank_sort() {
    local i
    for i in "$@"; do
        [[ -n "$i" ]] && echo "$(iface_rank "$(iface_role "$i")") $i"
    done | sort -k1,1n -s | awk '{print $2}'
}

is_ap_side() {
    local iface="$1"
    for ap in "${AP_SIDE[@]}"; do
        [[ "$iface" == "$ap" ]] && return 0
    done
    # Never-WAN by shape, not by name: docker's per-network bridges
    # (br-<hex>), veth pairs, CAN buses, tunnels. v2.1 never saw these because
    # its boot scan required a default route; v2.2's failover search is
    # broader, and br-3275f2636efe duly turned up as a candidate on
    # 2026-10-19. It would have been rejected by the probe, but its guessed
    # gateway (its own address) passes the reachability check first, so it
    # wastes a probe cycle on every failover and is a latent hazard.
    case "$iface" in
        br-*|veth*|docker*|can*|tun*|tap*|wg*|dummy*) return 0 ;;
    esac
    # Any bridge at all is LAN-side by construction
    [[ -d "/sys/class/net/$iface/bridge" ]] && return 0
    # Also skip anything enslaved to br0
    ip link show "$iface" 2>/dev/null | grep -q "master br0" && return 0
    return 1
}

remove_wan_rules() {
    local wan="$1"
    [[ -z "$wan" ]] && return
    echo "[$(date)] Removing rules for old WAN=$wan"
    iptables -D FORWARD -i "$LAN_IFACE" -o "$wan" -j ACCEPT 2>/dev/null
    iptables -D FORWARD -i "$wan" -o "$LAN_IFACE" -m state --state RELATED,ESTABLISHED -j ACCEPT 2>/dev/null
    iptables -t nat -D POSTROUTING -o "$wan" -j MASQUERADE 2>/dev/null
}

add_wan_rules() {
    local wan="$1"
    echo "[$(date)] Adding rules for new WAN=$wan"
    iptables -C FORWARD -i "$LAN_IFACE" -o "$wan" -j ACCEPT 2>/dev/null || \
        iptables -A FORWARD -i "$LAN_IFACE" -o "$wan" -j ACCEPT
    iptables -C FORWARD -i "$wan" -o "$LAN_IFACE" -m state --state RELATED,ESTABLISHED -j ACCEPT 2>/dev/null || \
        iptables -A FORWARD -i "$wan" -o "$LAN_IFACE" -m state --state RELATED,ESTABLISHED -j ACCEPT
    iptables -t nat -C POSTROUTING -o "$wan" -j MASQUERADE 2>/dev/null || \
        iptables -t nat -A POSTROUTING -o "$wan" -j MASQUERADE
}

ensure_dns_input() {
    iptables -C INPUT -i "$LAN_IFACE" -p udp --dport 53 -j ACCEPT 2>/dev/null || \
        iptables -A INPUT -i "$LAN_IFACE" -p udp --dport 53 -j ACCEPT
    iptables -C INPUT -i "$LAN_IFACE" -p tcp --dport 53 -j ACCEPT 2>/dev/null || \
        iptables -A INPUT -i "$LAN_IFACE" -p tcp --dport 53 -j ACCEPT
}

# Leave only the WAN we committed drawing power.
#
# This script decides the WAN but, until 2026-10-23, never touched hub power,
# and only wan_scan.sh did. So a gated socket powered up by a failover stayed
# powered until the next scan: measured that day, a failover down to cellular
# followed by WiFi coming back left the ~1 W modem on, with the next scheduled
# scan not due until 2 AM. wan_scan already knows how to settle power and owns
# every hub call, so this hands the job back to it rather than re-deriving the
# socket map here. --enforce-gating only switches sockets OFF -- it never
# powers one on, never probes and never touches the routing table.
WAN_SCAN="/usr/local/sbin/wan_scan.sh"
SCAN_LOCK="/run/wan-scan-in-progress"
enforce_gating() {
    [[ -x "$WAN_SCAN" ]] || return 0
    # A walk in flight has deliberately powered a socket up to test it. Cutting
    # it mid-test is a real race, not a theoretical one: the usbhub README
    # records the dashboard's exclusivity switch killing the modem mid-DHCP.
    if [[ -e "$SCAN_LOCK" ]]; then
        echo "[$(date)] Gating: wan_scan is walking; leaving socket power alone"
        return 0
    fi
    # Bounded, and deliberately placed AFTER the route is committed and the
    # state file written, so a slow hub call can never delay connectivity.
    if ! timeout 30 "$WAN_SCAN" --enforce-gating; then
        echo "[$(date)] Gating: $WAN_SCAN --enforce-gating failed (rc=$?); see /var/log/wan-scan.log"
    fi
}

# Does $1 have carrier and an IPv4 address?
iface_has_ip() {
    local iface="$1"
    [[ -z "$iface" ]] && return 1
    local flags
    flags="$(ip link show "$iface" 2>/dev/null | head -1)"
    [[ -z "$flags" ]] && return 1
    # Admin-up is read from the FLAG list, not from operstate. A cdc_ether
    # cellular modem reports "state UNKNOWN" while working perfectly: on
    # 2026-10-19 eth1 held 192.168.0.118 and had been the live WAN, yet
    # `state UP` did not match -- so it was invisible to the candidate search,
    # and worse, the incumbent-health guard concluded the live WAN was dead
    # and would have let an untested candidate preempt it.
    grep -qE '[<,]UP[,>]' <<< "$flags" || return 1
    # Admin-up with no carrier is not a WAN (docker0 looks like this).
    grep -q 'NO-CARRIER' <<< "$flags" && return 1
    ip -4 addr show "$iface" 2>/dev/null | grep -q "inet " || return 1
    return 0
}

# Can we reach the internet OUT OF a specific device? (pre-commit safe)
# ICMP first, then TCP/HTTP - some campground and hotel gateways drop ICMP to
# public resolvers while passing TCP, and rejecting such a WAN would leave the
# RV with no internet at all. Both must fail before a candidate is rejected.
probe_iface() {
    local iface="$1" gw="${2:-}"
    local rc=1 target url host
    local added=()

    # v2.2: a standby candidate has NO default route of its own, because this
    # script deletes every default route except the chosen one. Both ping -I
    # and curl --interface use SO_BINDTODEVICE, which restricts route lookup to
    # routes on that device -- so with nothing else done, the probe can only
    # ever succeed for a candidate that has just taken a DHCP lease, and any
    # long-standing standby is unprobeable by construction.
    #
    # Measured 2026-10-19 by taking the live eth2 down: BOTH eth1 and wlan1
    # were rejected as "gateway reachable but no internet beyond it", purely
    # for this reason. Their links were fine -- each could ping its own gateway
    # -- so the failover had two healthy uplinks and refused both.
    #
    # Fix: install a /32 route to each probe endpoint via the candidate's
    # gateway for the duration of the probe. A /32 is more specific than any
    # default route, so it steers only the probe traffic and never disturbs the
    # incumbent's default route -- the pre-commit-safe property this function
    # is supposed to have. Removed again on every exit path below.
    if [[ -n "$gw" ]]; then
        for host in "${PROBE_HOSTS[@]}"; do
            if ip route add "$host/32" via "$gw" dev "$iface" 2>/dev/null; then
                added+=("$host")
            fi
        done
        [[ ${#added[@]} -gt 0 ]] && \
            echo "[$(date)] Probe: temporary routes via $gw on $iface for ${added[*]}"
    fi

    for target in "${PROBE_TARGETS[@]}"; do
        if ping -c "$PROBE_COUNT" -W "$PROBE_WAIT" -I "$iface" "$target" >/dev/null 2>&1; then
            echo "[$(date)] Probe OK (icmp): $iface reached $target"
            rc=0
            break
        fi
    done

    if [[ "$rc" != "0" ]]; then
        echo "[$(date)] ICMP probe failed on $iface; trying TCP"
        for url in "${PROBE_URLS[@]}"; do
            if curl -4 --interface "$iface" -s -o /dev/null --max-time "$PROBE_HTTP_TIMEOUT" "$url" 2>/dev/null; then
                echo "[$(date)] Probe OK (tcp): $iface reached $url"
                rc=0
                break
            fi
        done
    fi

    for host in "${added[@]:-}"; do
        [[ -n "$host" ]] && ip route del "$host/32" via "$gw" dev "$iface" 2>/dev/null
    done

    if [[ "$rc" != "0" ]]; then
        echo "[$(date)] Probe FAILED: $iface could not reach ${PROBE_TARGETS[*]} or ${PROBE_URLS[*]}"
    fi
    return "$rc"
}

# Non-AP interfaces that are UP with an IPv4 address, excluding $1.
# Ordered: those that already carry a default route of their own first, then
# the rest. A DHCP-supplied default route is a good signal, but it cannot be
# required -- this script deletes every default route except the chosen one,
# so a perfectly healthy standby (wlan1, routinely) has none.
candidate_ifaces() {
    local skip="$1" iface
    local routed="" plain=""
    for iface in $(ip -o link show up | awk -F': ' '{print $2}' | cut -d@ -f1); do
        [[ "$iface" == "$skip" ]] && continue
        is_ap_side "$iface" && continue
        iface_has_ip "$iface" || continue
        if ip route show dev "$iface" 2>/dev/null | grep -q "^default"; then
            routed="$routed $iface"
        else
            plain="$plain $iface"
        fi
    done
    # Preference order within each group, so a failover reaches for wired
    # before cellular rather than taking whatever enumerated first.
    echo $(rank_sort $routed) $(rank_sort $plain)
}

# Can we reach the internet via the current default route? (post-commit check)
probe_default() {
    for target in "${PROBE_TARGETS[@]}"; do
        ping -c "$PROBE_COUNT" -W "$PROBE_WAIT" "$target" >/dev/null 2>&1 && return 0
    done
    for url in "${PROBE_URLS[@]}"; do
        curl -4 -s -o /dev/null --max-time "$PROBE_HTTP_TIMEOUT" "$url" 2>/dev/null && return 0
    done
    return 1
}

# --- Determine active interface ---
TRIGGERED_IFACE="$1"
TRIGGERED_STATUS="${2:-up}"

# --- Serialize the whole invocation -----------------------------------------
# The NetworkManager dispatcher fires SEVERAL instances of this script for one
# event -- six log entries for the 2026-10-26 boot, three within the same
# second for one eth2 up on 2026-10-23. Every rule guard here is check-then-act
# (`iptables -C ... || iptables -A ...`), which is not atomic, so instances
# raced each other into duplicate rules: four identical br0 DNS accepts where
# there should be two, stale per-WAN FORWARD rules, and a duplicated
# MASQUERADE. Confirmed as the cause on 2026-10-26 after a reboot ruled out
# netfilter-persistent restoring them.
#
# With the lock, the first instance does the work and the others find every
# guard already satisfied, which is what makes them cheap no-ops rather than
# duplicate-rule generators.
#
# PI5_LOCK_HELD is exported for the recursive failover child ("$0" "$cand" up).
# That child must NOT wait for a lock its own parent holds -- that would
# deadlock the failover path, which is precisely the path that matters when
# the RV has no WAN.
#
# On timeout we proceed ANYWAY rather than exit. Getting duplicate rules is
# cosmetic; skipping the work because another instance looked busy could leave
# the RV with no uplink if that instance is wedged. Connectivity wins, and the
# log line makes the race visible.
LOCK_FILE="/run/pi5connect.lock"
LOCK_WAIT=30
if [[ "${PI5_LOCK_HELD:-0}" != "1" ]]; then
    if exec {LOCK_FD}>"$LOCK_FILE" 2>/dev/null; then
        if flock -w "$LOCK_WAIT" "$LOCK_FD"; then
            export PI5_LOCK_HELD=1
        else
            echo "[$(date)] Lock: waited ${LOCK_WAIT}s for $LOCK_FILE, proceeding without it (duplicate rules possible)"
        fi
    else
        echo "[$(date)] Lock: could not open $LOCK_FILE, proceeding without it"
    fi
fi

MANUAL_ROLE="$(manual_role)"
if [[ -n "$MANUAL_ROLE" ]]; then
    echo "[$(date)] Manual choice in force: $MANUAL_ROLE (outranks the preference list)"
fi

if [[ -n "$TRIGGERED_IFACE" ]] && ! is_ap_side "$TRIGGERED_IFACE"; then
    ACTIVE_IFACE="$TRIGGERED_IFACE"
else
    # Boot-time scan: find any UP non-AP interface with a default route
    ACTIVE_IFACE=""
    for iface in $(ip -o link show up | awk -F': ' '{print $2}' | cut -d@ -f1); do
        is_ap_side "$iface" && continue
        ip route show dev "$iface" | grep -q "^default" && ACTIVE_IFACE="$iface" && break
    done
fi

# --- Handle down event ---
if [[ "$TRIGGERED_STATUS" == "down" ]]; then
    remove_wan_rules "$TRIGGERED_IFACE"
    WAS_WAN=0
    if [[ "$(cut -d' ' -f1 $STATE_FILE 2>/dev/null)" == "$TRIGGERED_IFACE" ]]; then
        WAS_WAN=1
        rm -f "$STATE_FILE"
    fi
    ensure_dns_input
    echo "[$(date)] Interface $TRIGGERED_IFACE went down; rules removed."

    # v2.2: promote a replacement instead of just exiting.
    #
    # Up to v2.1 this path removed the rules and stopped, so the RV had no WAN
    # until some OTHER interface happened to fire its own up/dhcp4-change event
    # -- which an interface that is already up never does. Observed 2026-10-18:
    # the Alfa's driver failed, wlan1 went down, and nothing promoted the
    # healthy eth1 sitting right there. Recovery only came ~90s later because
    # eth1 independently re-leased.
    #
    # Each candidate is tried by re-running this script with "up", so the
    # existing gateway detection, pre-commit probe, commit and rollback all
    # apply unchanged. No recursion: the child runs the "up" path.
    if [[ "$WAS_WAN" == "1" || -z "$(ip route show default)" ]]; then
        FAILOVER_CANDIDATES="$(candidate_ifaces "$TRIGGERED_IFACE")"
        if [[ -z "${FAILOVER_CANDIDATES// /}" ]]; then
            # NO early exit here. Zero powered candidates is precisely the
            # case gating creates -- the gated modem has no interface to find
            # -- and it is the case that needs wan_scan most. An "exit 0" here
            # skipped the handoff below and left the RV dark: measured
            # 2026-10-20, wired powered off with WiFi disconnected produced
            # "Failover: no other interface is up with an address" and nothing
            # further for 150s.
            echo "[$(date)] Failover: no other interface is up with an address."
        else
            echo "[$(date)] Failover: candidates after $TRIGGERED_IFACE:$FAILOVER_CANDIDATES"
            for cand in $FAILOVER_CANDIDATES; do
                echo "[$(date)] Failover: trying $cand"
                if PI5_FAILOVER=1 "$0" "$cand" up; then
                    echo "[$(date)] Failover: $cand accepted as WAN"
                    exit 0
                fi
                echo "[$(date)] Failover: $cand rejected"
            done
            echo "[$(date)] Failover: no powered candidate passed."
        fi
        # Gated sockets have NO interface while powered down, so the loop
        # above cannot have tried them -- it only ever sees what is already
        # enumerated. Since cellular is gated (0.4W adapters stay powered,
        # the ~1W modem does not), an automatic failover would otherwise be
        # unable to reach the one uplink that is almost always available.
        # wan_scan powers each role in turn and tests it. No recursion: it
        # calls this script with "up", which never reaches this block.
        if [[ -x /usr/local/sbin/wan_scan.sh ]]; then
            echo "[$(date)] Failover: handing off to wan_scan --on-loss (it can power gated sockets)"
            /usr/local/sbin/wan_scan.sh --on-loss
            echo "[$(date)] Failover: wan_scan finished, WAN=$(cut -d' ' -f1 "$STATE_FILE" 2>/dev/null || echo none)"
        else
            echo "[$(date)] Failover: no wan_scan.sh, so gated sockets cannot be reached. The RV has no WAN."
        fi
    else
        echo "[$(date)] $TRIGGERED_IFACE was not the WAN; nothing to promote."
    fi
    exit 0
fi

# --- Handle up / boot ---
if [[ -z "$ACTIVE_IFACE" ]]; then
    echo "[$(date)] No active WAN interface found."
    ensure_dns_input
    exit 1
fi

# State file format: "<iface> <gateway>" (v2.0 wrote just "<iface>")
PREV_WAN="$(cut -d' ' -f1 $STATE_FILE 2>/dev/null)"
PREV_GW="$(cut -d' ' -f2 $STATE_FILE 2>/dev/null)"
# Prefer the live default route for rollback - it is what we are about to destroy
LIVE_GW=$(ip route show default | awk '/^default via/ {print $3; exit}')
LIVE_DEV=$(ip route show default | awk '/^default via/ {print $5; exit}')
[[ -n "$LIVE_GW" ]] && PREV_GW="$LIVE_GW"
[[ -n "$LIVE_DEV" ]] && PREV_WAN="${PREV_WAN:-$LIVE_DEV}"

# --- Guard: do not preempt a working incumbent with an untested candidate ---
if [[ -n "$PREV_WAN" && "$PREV_WAN" != "$ACTIVE_IFACE" && "$PI5_FORCE" != "1" ]]; then
    if iface_has_ip "$PREV_WAN" && probe_default; then
        CAND_ROLE="$(iface_role "$ACTIVE_IFACE")"
        PREV_ROLE="$(iface_role "$PREV_WAN")"
        CAND_RANK="$(iface_rank "$CAND_ROLE")"
        PREV_RANK="$(iface_rank "$PREV_ROLE")"
        if (( CAND_RANK < PREV_RANK )); then
            # Promotion. The candidate still has to pass its own pre-commit
            # probe below, and the commit still rolls back on failure, so a
            # flaky preferred uplink cannot ping-pong the default route.
            echo "[$(date)] Promoting $ACTIVE_IFACE (${CAND_ROLE:-unknown}) over healthy $PREV_WAN (${PREV_ROLE:-unknown})"
        else
            echo "[$(date)] Keeping WAN=$PREV_WAN (healthy, ${PREV_ROLE:-unknown}); ignoring $ACTIVE_IFACE (${CAND_ROLE:-unknown}, not preferred)."
            echo "[$(date)] Set PI5_FORCE=1 to switch deliberately."
            ensure_dns_input
            exit 0
        fi
    else
        echo "[$(date)] Incumbent WAN=$PREV_WAN is not healthy; evaluating $ACTIVE_IFACE."
    fi
fi

echo "[$(date)] Evaluating $ACTIVE_IFACE as WAN."

# --- Gateway detection ---
GATEWAY_IP=$(ip route show dev "$ACTIVE_IFACE" | awk '/default via/ {print $3; exit}')
if [[ -z "$GATEWAY_IP" ]]; then
    GATEWAY_IP=$(nmcli -g IP4.GATEWAY con show "$ACTIVE_IFACE" 2>/dev/null)
fi
GUESSED=0
if [[ -z "$GATEWAY_IP" ]]; then
    UPLINK_IP=$(ip -4 addr show "$ACTIVE_IFACE" | grep -oP '(?<=inet\s)\d+(\.\d+){3}' | head -n1)
    if [[ -n "$UPLINK_IP" ]]; then
        GATEWAY_IP=$(echo "$UPLINK_IP" | awk -F. '{print $1"."$2"."$3".1"}')
        GUESSED=1
        echo "[$(date)] Warning: guessing gateway $GATEWAY_IP for $ACTIVE_IFACE (must still pass probe)"
    fi
fi

if [[ -z "$GATEWAY_IP" ]]; then
    echo "[$(date)] Error: cannot determine gateway for $ACTIVE_IFACE."
    ensure_dns_input
    exit 1
fi

# --- Validate BEFORE touching the default route ---
if [[ "$PI5_SKIP_PROBE" == "1" ]]; then
    echo "[$(date)] PI5_SKIP_PROBE=1: accepting $ACTIVE_IFACE without probing."
elif ! ping -c 1 -W "$PROBE_WAIT" -I "$ACTIVE_IFACE" "$GATEWAY_IP" >/dev/null 2>&1; then
    echo "[$(date)] Reject $ACTIVE_IFACE: gateway $GATEWAY_IP is not reachable on that device."
    [[ "$GUESSED" == "1" ]] && echo "[$(date)] (gateway was a guess, so this is expected)"
    ensure_dns_input
    exit 1
elif ! probe_iface "$ACTIVE_IFACE" "$GATEWAY_IP"; then
    echo "[$(date)] Reject $ACTIVE_IFACE: gateway reachable but no internet beyond it."
    echo "[$(date)] Leaving WAN=${PREV_WAN:-none} untouched."
    echo "[$(date)] If this network blocks ICMP and HTTP probes, re-run with PI5_SKIP_PROBE=1."
    ensure_dns_input
    exit 1
fi

# --- Commit ---
if [[ -n "$PREV_WAN" && "$PREV_WAN" != "$ACTIVE_IFACE" ]]; then
    remove_wan_rules "$PREV_WAN"
fi

echo "[$(date)] Setting default route via $GATEWAY_IP on $ACTIVE_IFACE"
while ip route del default 2>/dev/null; do :; done
ip route add default via "$GATEWAY_IP" dev "$ACTIVE_IFACE"

sysctl -w net.ipv4.ip_forward=1 > /dev/null

add_wan_rules "$ACTIVE_IFACE"
ensure_dns_input

# --- Post-commit verification, with rollback ---
if [[ "$PI5_SKIP_PROBE" != "1" ]] && ! probe_default; then
    echo "[$(date)] ERROR: no internet after committing $ACTIVE_IFACE."
    if [[ -n "$PREV_GW" && -n "$PREV_WAN" && "$PREV_WAN" != "$ACTIVE_IFACE" ]]; then
        echo "[$(date)] Rolling back to WAN=$PREV_WAN GW=$PREV_GW"
        remove_wan_rules "$ACTIVE_IFACE"
        while ip route del default 2>/dev/null; do :; done
        ip route add default via "$PREV_GW" dev "$PREV_WAN" 2>/dev/null
        add_wan_rules "$PREV_WAN"
        echo "$PREV_WAN $PREV_GW" > "$STATE_FILE"
        ensure_dns_input
        enforce_gating
        echo "[$(date)] pi5connect.sh rolled back v$SCRIPT_VERSION WAN=$PREV_WAN GW=$PREV_GW"
        exit 1
    fi
    echo "[$(date)] No previous WAN to roll back to; leaving $ACTIVE_IFACE in place."
fi

echo "$ACTIVE_IFACE $GATEWAY_IP" > "$STATE_FILE"
enforce_gating
echo "[$(date)] pi5connect.sh complete v$SCRIPT_VERSION WAN=$ACTIVE_IFACE GW=$GATEWAY_IP"
