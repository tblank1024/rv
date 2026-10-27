# Shared constants for the WAN scripts. SOURCED, not executed -- no shebang,
# no `set -e`, nothing with a side effect, because pi5connect.sh sources this
# from a NetworkManager dispatcher context where an unexpected exit means the
# RV never gets an uplink.
#
# Install to /usr/local/sbin/wan-common.sh alongside pi5connect.sh and
# wan_scan.sh.
#
# --- why this file exists ---------------------------------------------------
#
# MANUAL_GRACE and WAN_PREFERENCE were each written out twice, once in
# pi5connect.sh and once in wan_scan.sh, with a comment in both saying "keep
# them in step". A comment is a request, not a mechanism. Worse, MANUAL_GRACE
# had a THIRD, unwritten dependency: its value was the sum of the modem
# timeouts in wan_scan.sh, so changing a timeout silently invalidated a
# constant in a different file with nothing to say so.
#
# Both halves are fixed here: one definition for the shared constants, and
# MANUAL_GRACE is now COMPUTED from the timings instead of restated. Change a
# timeout and the grace follows.
#
# raspap/check_wan_constants.sh asserts that the fallback mirrors inside the
# two scripts still agree with this file. Run it after editing any of them.

# --- Modem cold-start timings ----------------------------------------------
#
# MEASURED on this hardware 2026-10-19, not guessed. Powering the cellular
# socket from cold: USB enumeration +17s (the modem boots its own firmware and
# mode-switches from QCOM 05c6:f000 to TCL 1bbb:0646), netdev and carrier +22s,
# DHCP +52s. My first guesses were 12/6/40, which would have abandoned the
# modem five seconds before it even appeared on the bus. The values below are
# the measurements with headroom.
IFACE_WAIT=35        # seconds for a powered socket to present an interface
CARRIER_WAIT=10      # then for carrier -- 0 means nothing on the other end
DHCP_WAIT=75         # then for an IPv4 address
SETTLE=2

# Worst case for a cold uplink to become usable: the three waits are
# sequential, so the scan can spend their sum on one candidate before giving up
# on it.
WAN_COLD_START=$(( IFACE_WAIT + CARRIER_WAIT + DHCP_WAIT ))

# --- The manual-choice grace period ----------------------------------------
#
# A deliberate choice from the dashboard ("<role> <epoch>" in MANUAL_FILE,
# written by /api/internet/select). While it is in force the chosen role
# outranks everything, so failover tries it first and a "more preferred" uplink
# cannot preempt it.
#
# It is DERIVED, not chosen: the grace has to outlast the slowest cold start,
# or the scan would stop honouring a choice while the uplink it selected was
# still legitimately coming up -- which is precisely the bug the manual choice
# exists to fix. Equal to WAN_COLD_START, which is 120s as of 2026-10-27.
#
# wan_scan.sh owns clearing MANUAL_FILE when the choice cannot be honoured, and
# carries the longer note on what "in force" means after the grace expires.
MANUAL_GRACE="${MANUAL_GRACE:-$WAN_COLD_START}"
MANUAL_FILE="${MANUAL_FILE:-/run/wan-manual-choice}"
MANUAL_FALLBACK="${MANUAL_FALLBACK:-/run/wan-manual-fallback}"

# --- WAN preference, best first --------------------------------------------
#
# A healthy incumbent is displaced only by a candidate that ranks STRICTLY
# higher. Without this, "never preempt a healthy incumbent" meant a transient
# wired glitch stranded the RV on metered cellular indefinitely: the 2026-10-19
# failover test switched to cellular in 3s and then kept it after wired came
# back -- exactly as designed, and exactly wrong for the bill.
#
# The order is also the power order, and that is not a coincidence: the two
# cheapest uplinks to leave running are the two most preferred.
WAN_PREFERENCE=("wired" "wifi" "starlink" "cellular")

SOCKET_MAP="${SOCKET_MAP:-/etc/usbhub/sockets.json}"
