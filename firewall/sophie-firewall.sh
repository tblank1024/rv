#!/bin/bash
# Sophie host firewall: default-deny inbound/forward on every interface except the RV LAN side.
# Usage: sophie-firewall.sh apply | docker | revert | status
# See plan_firewall.md. Rules live in our own chains (SOPHIE-IN, SOPHIE-FWD); this script
# never runs `iptables -F`, so Docker's and pi5connect.sh's rules are left alone.
set -uo pipefail

TRUSTED=(lo br0 docker0 "br-+")          # everything else (eth1, eth2, wlan1, wwan0, ...) is untrusted

# The ONE inbound exception, added 2026-10-26 on the owner's decision. It
# reverses "no inbound allow-list" in plan_firewall.md, so the reasoning is
# here rather than in the commit alone.
#
# Purpose: the laptop's Workers window attaches to the rv-manager tmux session
# over SSH. On Sophie's own WiFi that already worked, because br0 is trusted;
# this is for when BOTH are on the home LAN and the packet arrives on an
# uplink.
#
# Why MAC and not a source subnet: a source match of 192.168.2.0/24 would also
# match at any campground using that subnet -- one of the most common there is
# -- silently exposing port 22 to every other guest. `-m mac` matches the
# source MAC of the arriving FRAME, so it can only ever match a directly
# attached neighbour: a packet routed from the internet carries the gateway's
# MAC and can never match, and no campground device carries these MACs. So the
# road posture is unchanged.
#
# Why no -i pin: the uplink's interface name swaps between eth1 and eth2 across
# boots (see TODO.md), and the MAC match already confines this to the local
# segment, which is what an interface pin would have been for.
#
# Residual risk, accepted: someone already on the home LAN who knows these MACs
# could spoof one. Key-only auth is what stands behind it -- see
# /etc/ssh/sshd_config.d/10-sophie-hardening.conf.
SSH_MACS=(
    28:d0:ea:d4:f7:47      # laptop Wi-Fi, Intel AX201 (vendor MAC, not randomized)
    08:3a:88:55:27:80      # laptop wired, Lenovo USB Ethernet dongle
)

chain() { "$1" -N "$2" 2>/dev/null || "$1" -F "$2"; }
hook()  { "$1" -C "$2" -j "$3" 2>/dev/null || "$1" -I "$2" 1 -j "$3"; }
unhook(){ while "$1" -D "$2" -j "$3" 2>/dev/null; do :; done; }

build_in() {   # $1 = iptables | ip6tables
    local T=$1
    chain $T SOPHIE-IN
    for i in "${TRUSTED[@]}"; do $T -A SOPHIE-IN -i "$i" -j ACCEPT; done
    $T -A SOPHIE-IN -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
    # SSH from the laptop only. IPv4 and IPv6 both, since the home LAN hands
    # out a ULA and ssh may pick either family.
    for m in "${SSH_MACS[@]}"; do
        $T -A SOPHIE-IN -p tcp --dport 22 -m mac --mac-source "$m" -j ACCEPT
    done
    if [ "$T" = ip6tables ]; then
        for t in 133 134 135 136; do              # RS, RA, NS, NA: needed for IPv6 to work at all
            $T -A SOPHIE-IN -p ipv6-icmp --icmpv6-type $t -j ACCEPT
        done
        $T -A SOPHIE-IN -p udp -s fe80::/10 --dport 546 -j ACCEPT   # DHCPv6 replies
    fi
    $T -A SOPHIE-IN -m limit --limit 6/min -j LOG --log-prefix "SOPHIE-IN drop: "
    $T -A SOPHIE-IN -j DROP
    hook $T INPUT SOPHIE-IN
}

build_fwd() {
    local T=$1
    chain $T SOPHIE-FWD
    $T -A SOPHIE-FWD -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
    $T -A SOPHIE-FWD -i br0 -j ACCEPT                 # RV LAN -> internet, and br0<->br0 bridged traffic
    $T -A SOPHIE-FWD -i docker0 -j RETURN             # container traffic: Docker's own rules decide
    $T -A SOPHIE-FWD -i br-+ -j RETURN
    $T -A SOPHIE-FWD -m limit --limit 6/min -j LOG --log-prefix "SOPHIE-FWD drop: "
    $T -A SOPHIE-FWD -j DROP                          # new connections arriving from an untrusted interface
    hook $T FORWARD SOPHIE-FWD
    $T -P FORWARD DROP
}

verify() {   # the hooks, not the chains. A chain can exist with nothing jumping to it.
    local T rc=0
    for T in iptables ip6tables; do
        $T -C INPUT -j SOPHIE-IN 2>/dev/null   || { echo "$T: INPUT not hooked to SOPHIE-IN" >&2; rc=1; }
        $T -C FORWARD -j SOPHIE-FWD 2>/dev/null || { echo "$T: FORWARD not hooked to SOPHIE-FWD" >&2; rc=1; }
    done
    return $rc
}

case "${1:-}" in
  apply)
    for T in iptables ip6tables; do build_in $T; build_fwd $T; done
    # Exit non-zero if a rule did not land, so systemd shows a failed unit. Without
    # this the script exits 0 regardless (no `set -e`), which is how Sophie booted
    # unprotected on 2026-10-21: netfilter-persistent's restore deleted SOPHIE-IN
    # mid-build and nothing said so. See README.md "Traps".
    verify || { echo "apply failed: firewall is NOT armed" >&2; exit 1; } ;;
  docker)   # run after dockerd (re)starts: make sure Docker's first-evaluated chain sends us the traffic
    for T in iptables ip6tables; do
        $T -L DOCKER-USER -n >/dev/null 2>&1 && $T -L SOPHIE-FWD -n >/dev/null 2>&1 && hook $T DOCKER-USER SOPHIE-FWD
    done ;;
  revert)   # back to the previous behavior (everything open)
    for T in iptables ip6tables; do
        unhook $T INPUT SOPHIE-IN; unhook $T FORWARD SOPHIE-FWD; unhook $T DOCKER-USER SOPHIE-FWD
        $T -F SOPHIE-IN 2>/dev/null; $T -X SOPHIE-IN 2>/dev/null
        $T -F SOPHIE-FWD 2>/dev/null; $T -X SOPHIE-FWD 2>/dev/null
    done
    iptables -P FORWARD ACCEPT ;;     # previous rules.v4 state; Docker may set DROP again on restart
  status)
    for T in iptables ip6tables; do echo "== $T"; $T -S INPUT | head -3; $T -S FORWARD | head -4
        $T -S DOCKER-USER 2>/dev/null | head -3; $T -L SOPHIE-IN -v -n 2>/dev/null; $T -L SOPHIE-FWD -v -n 2>/dev/null; done
    if verify; then echo "== ARMED"; else echo "== NOT ARMED"; exit 1; fi ;;
  *) echo "usage: $0 apply|docker|revert|status" >&2; exit 2 ;;
esac
