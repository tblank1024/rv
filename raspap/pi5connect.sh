#!/bin/bash
#
# pi5connect.sh - selects the RV's WAN uplink and configures NAT for the bridge.
# Triggered by /etc/NetworkManager/dispatcher.d/99-pi5connect on interface
# up/down/connectivity-change, and by setup-bridge.sh at boot (no args).
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
PROBE_COUNT=2
PROBE_WAIT=2
PROBE_HTTP_TIMEOUT=6

# Interfaces that are never WAN
AP_SIDE=("lo" "eth0" "wlan0" "br0" "docker0")

is_ap_side() {
    local iface="$1"
    for ap in "${AP_SIDE[@]}"; do
        [[ "$iface" == "$ap" ]] && return 0
    done
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

# Does $1 have carrier and an IPv4 address?
iface_has_ip() {
    local iface="$1"
    [[ -z "$iface" ]] && return 1
    ip link show "$iface" 2>/dev/null | grep -q "state UP" || return 1
    ip -4 addr show "$iface" 2>/dev/null | grep -q "inet " || return 1
    return 0
}

# Can we reach the internet OUT OF a specific device? (pre-commit safe)
# ICMP first, then TCP/HTTP - some campground and hotel gateways drop ICMP to
# public resolvers while passing TCP, and rejecting such a WAN would leave the
# RV with no internet at all. Both must fail before a candidate is rejected.
probe_iface() {
    local iface="$1"
    for target in "${PROBE_TARGETS[@]}"; do
        if ping -c "$PROBE_COUNT" -W "$PROBE_WAIT" -I "$iface" "$target" >/dev/null 2>&1; then
            echo "[$(date)] Probe OK (icmp): $iface reached $target"
            return 0
        fi
    done
    echo "[$(date)] ICMP probe failed on $iface; trying TCP"
    for url in "${PROBE_URLS[@]}"; do
        if curl -4 --interface "$iface" -s -o /dev/null --max-time "$PROBE_HTTP_TIMEOUT" "$url" 2>/dev/null; then
            echo "[$(date)] Probe OK (tcp): $iface reached $url"
            return 0
        fi
    done
    echo "[$(date)] Probe FAILED: $iface could not reach ${PROBE_TARGETS[*]} or ${PROBE_URLS[*]}"
    return 1
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
    [[ "$(cut -d' ' -f1 $STATE_FILE 2>/dev/null)" == "$TRIGGERED_IFACE" ]] && rm -f "$STATE_FILE"
    ensure_dns_input
    echo "[$(date)] Interface $TRIGGERED_IFACE went down; rules removed."
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
        echo "[$(date)] Keeping WAN=$PREV_WAN (healthy); ignoring candidate $ACTIVE_IFACE."
        echo "[$(date)] Set PI5_FORCE=1 to switch deliberately."
        ensure_dns_input
        exit 0
    fi
    echo "[$(date)] Incumbent WAN=$PREV_WAN is not healthy; evaluating $ACTIVE_IFACE."
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
elif ! probe_iface "$ACTIVE_IFACE"; then
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
        echo "[$(date)] pi5connect.sh rolled back v2.1 WAN=$PREV_WAN GW=$PREV_GW"
        exit 1
    fi
    echo "[$(date)] No previous WAN to roll back to; leaving $ACTIVE_IFACE in place."
fi

echo "$ACTIVE_IFACE $GATEWAY_IP" > "$STATE_FILE"
echo "[$(date)] pi5connect.sh complete v2.1 WAN=$ACTIVE_IFACE GW=$GATEWAY_IP"
