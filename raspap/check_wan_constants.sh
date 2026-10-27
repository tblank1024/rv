#!/bin/bash
# Assert that the WAN scripts' shared constants have not drifted.
#
# Run it after editing wan-common.sh, pi5connect.sh or wan_scan.sh, and after
# installing any of them to /usr/local/sbin. Exit 0 = consistent.
#
#   ./check_wan_constants.sh              # check the repo copies
#   ./check_wan_constants.sh /usr/local/sbin   # check what is installed
#
# --- what it checks and why ------------------------------------------------
#
# 1. MANUAL_GRACE is the sum of the three modem waits. This is the coupling
#    that had nothing holding it: the value 120 was written out as a literal in
#    two files, and was ALSO, silently, IFACE_WAIT + CARRIER_WAIT + DHCP_WAIT.
#    Shorten a timeout and the grace is too long; lengthen one and the scan
#    stops honouring a deliberate choice while the uplink it selected is still
#    legitimately coming up -- which is the exact bug the manual choice exists
#    to fix, reintroduced by editing an unrelated-looking number.
#
# 2. The inline fallback mirrors inside the two scripts still match
#    wan-common.sh. Those mirrors exist so that a missing constants file cannot
#    leave the RV with no uplink; the cost is that they are copies, so they
#    need something that notices when they stop agreeing. This is that thing.
#
# 3. WAN_PREFERENCE is identical everywhere. The two scripts rank candidates
#    independently, so a disagreement means pi5connect and wan_scan would fight
#    over which uplink wins.
set -u

DIR="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
COMMON="$DIR/wan-common.sh"
SCRIPTS=("$DIR/pi5connect.sh" "$DIR/wan_scan.sh")

fails=0
fail() { printf 'FAIL: %s\n' "$*"; fails=$((fails + 1)); }
ok()   { printf 'ok:   %s\n' "$*"; }

for f in "$COMMON" "${SCRIPTS[@]}"; do
    [[ -r "$f" ]] || { fail "$f is missing or unreadable"; }
done
(( fails )) && exit 1

# The canonical values, read by sourcing the real file rather than by grepping
# it -- a grep would not see the arithmetic that derives MANUAL_GRACE.
# shellcheck source=wan-common.sh
. "$COMMON"
want_grace="$MANUAL_GRACE"
want_pref="${WAN_PREFERENCE[*]}"
want_waits="$IFACE_WAIT $CARRIER_WAIT $DHCP_WAIT"

# 1. The derivation.
sum=$(( IFACE_WAIT + CARRIER_WAIT + DHCP_WAIT ))
if [[ "$want_grace" == "$sum" ]]; then
    ok "MANUAL_GRACE=$want_grace == IFACE_WAIT+CARRIER_WAIT+DHCP_WAIT ($want_waits)"
else
    fail "MANUAL_GRACE=$want_grace but IFACE_WAIT+CARRIER_WAIT+DHCP_WAIT=$sum ($want_waits).
      The grace must outlast the slowest cold start, or a deliberate uplink
      choice stops being honoured while that uplink is still coming up."
fi

# 2 and 3. Each script's fallback mirror, extracted by running the else branch
# in isolation: the mirror is the only thing between `else` and `fi` in the
# script's constants block, so it can be sourced on its own with the shared
# file deliberately absent. Cleaner than parsing, and it exercises the real
# code path rather than a reading of it.
for script in "${SCRIPTS[@]}"; do
    name="$(basename "$script")"
    mirror="$(sed -n '/^WAN_COMMON=/,/^fi$/p' "$script" | sed -n '/^else$/,/^fi$/p' \
              | sed '1d;$d' | grep -v '^[[:space:]]*echo')"
    if [[ -z "$mirror" ]]; then
        fail "$name: could not find an inline fallback mirror to check"
        continue
    fi
    # Run it with nothing preset, so the mirror's own values are what we read
    # back -- not values inherited from this shell or from wan-common.sh above.
    # One value per line, because WAN_PREFERENCE joins on spaces and would
    # otherwise be indistinguishable from a field separator.
    mapfile -t got < <(
        env -i bash -c "
            set -u
            $mirror
            echo \"\$MANUAL_GRACE\"
            echo \"\${WAN_PREFERENCE[*]}\"
        " 2>/dev/null
    )
    if (( ${#got[@]} < 2 )); then
        fail "$name: inline mirror failed to execute"
        continue
    fi
    got_grace="${got[0]}"
    got_pref="${got[1]}"

    if [[ "$got_grace" == "$want_grace" ]]; then
        ok "$name: fallback MANUAL_GRACE=$got_grace matches wan-common.sh"
    else
        fail "$name: fallback MANUAL_GRACE=$got_grace but wan-common.sh says $want_grace"
    fi
    if [[ "$got_pref" == "$want_pref" ]]; then
        ok "$name: fallback WAN_PREFERENCE=($got_pref) matches wan-common.sh"
    else
        fail "$name: fallback WAN_PREFERENCE=($got_pref) but wan-common.sh says ($want_pref)"
    fi
done

echo
if (( fails )); then
    echo "$fails check(s) failed in $DIR"
    exit 1
fi
echo "All WAN constants consistent in $DIR"
