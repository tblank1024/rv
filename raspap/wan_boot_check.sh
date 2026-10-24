#!/bin/bash
#
# wan_boot_check.sh - after a boot, make sure the RV has an uplink, and apply
# socket gating.
#
# WHY THIS EXISTS
# Two gaps, both only visible once gating was switched on:
#
#  1. wan_revert.sh arms a TRANSIENT systemd unit, so it dies with the reboot.
#     Nothing protected the RV across a restart: if the chosen WAN failed to
#     come up, pi5connect would log it and stop, and the box would sit dark
#     until someone noticed.
#  2. Hub sockets default to POWERED at boot, so gating is not in force until
#     something applies it. Harmless for connectivity -- more powered means
#     more options -- but the gated modem would quietly draw its ~1W forever.
#     (Measured 2026-10-23: ~1 W powered, 0 W switched off, at the socket. The
#     hub really does cut VBUS, so this is a real saving, not a hopeful one.)
#
# Both are handled by one pass of wan_scan, which picks the best working
# uplink and settles the gated ones off.
#
set -u
LOGFILE="${LOGFILE:-/var/log/wan-boot-check.log}"
exec >> "$LOGFILE" 2>&1

SCAN="/usr/local/sbin/wan_scan.sh"
TARGETS=("1.1.1.1" "8.8.8.8")
URLS=("http://1.1.1.1/" "http://204.79.197.200/")

log() { echo "[$(date)] $*"; }

have_internet() {
    local t u
    for t in "${TARGETS[@]}"; do
        ping -c 2 -W 2 "$t" >/dev/null 2>&1 && return 0
    done
    for u in "${URLS[@]}"; do
        curl -4 -s -o /dev/null --max-time 6 "$u" >/dev/null 2>&1 && return 0
    done
    return 1
}

log "===== boot check (uptime $(cut -d. -f1 /proc/uptime)s) ====="
log "WAN=$(cat /run/pi5connect-wan 2>/dev/null || echo none)"

if [[ ! -x "$SCAN" ]]; then
    log "ERROR: $SCAN missing; cannot check or enforce anything"
    exit 1
fi

if have_internet; then
    # Plain mode: keeps the current uplink unless something better turns up,
    # and enforces gating against it either way.
    log "internet is up; running a scan to enforce gating"
    "$SCAN"
else
    # No uplink. Walk every role, powering gated sockets as needed.
    log "NO internet after boot; running wan_scan --on-loss"
    "$SCAN" --on-loss
    if have_internet; then
        log "recovered: WAN=$(cat /run/pi5connect-wan 2>/dev/null)"
    else
        log "STILL no internet after a full scan. br0 and SSH are unaffected."
    fi
fi
log "===== boot check done, WAN=$(cat /run/pi5connect-wan 2>/dev/null || echo none) ====="
