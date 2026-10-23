# firewall/ — Sophie's host firewall

Default-deny inbound and forward on every interface except the RV LAN side, so that
Sophie herself is not reachable from a campground/park network, a home LAN, Starlink or
the cellular modem. Design, rationale and the per-uplink test matrix live in
`../plan_firewall.md`; this file is the operator's view.

## What's here

| File | Goes to | Purpose |
|---|---|---|
| `sophie-firewall.sh` | `/usr/local/sbin/` | the rules: `apply \| docker \| revert \| status` |
| `sophie-firewall.service` | `/etc/systemd/system/` | runs `apply` at boot, before any interface is up |
| `sophie-firewall-docker.service` | `/etc/systemd/system/` | re-hooks `DOCKER-USER` whenever Docker (re)starts |
| `install.sh` | — | copies the above, `daemon-reload`, `enable` (does not start) |
| `setup-passwordless-sudo.sh` | `/etc/sudoers.d/sophie-firewall` | optional: `sudo sophie-firewall.sh status` without a password |

## The model

Trust is by **interface**, never by uplink name or subnet — uplink interface names vary
(`eth1`, `eth2`, `wlan1`, `wwan0`, ...) and a park network can hand out the same subnet as
home.

- **Trusted:** `lo`, `br0` (the RV LAN: onboard WiFi AP + `eth0`), `docker0`, `br-+`
- **Untrusted:** everything else, i.e. whichever uplink is live

| Chain | Trusted | Untrusted |
|---|---|---|
| `SOPHIE-IN` (from INPUT) | accept | conntrack ESTABLISHED,RELATED only |
| `SOPHIE-FWD` (from FORWARD **and** DOCKER-USER) | `br0` accept; Docker bridges RETURN | replies only; new connections dropped |

IPv6 gets the same treatment plus the ICMPv6 types (133-136) and DHCPv6 replies that IPv6
needs to function at all. Rate-limited `LOG` lines (`SOPHIE-IN drop:` / `SOPHIE-FWD drop:`)
sit in front of each DROP; the journal is volatile, so they cost no SD writes.

There is **no inbound allow-list** — no "SSH from the home subnet" exception, deliberately
(see `plan_firewall.md` §"Things that will break"). Reach Sophie from outside the RV LAN via
Raspberry Pi Connect, or put the laptop on Sophie's own WiFi.

## Install

```bash
sudo ./install.sh                      # copy + enable, does not start
./setup-passwordless-sudo.sh           # optional, as tblank, not root
sudo systemd-run --unit=fw-autorevert --on-active=10min /usr/local/sbin/sophie-firewall.sh revert
sudo /usr/local/sbin/sophie-firewall.sh apply && sudo /usr/local/sbin/sophie-firewall.sh docker
# verify (below); if good:
sudo systemctl stop fw-autorevert.timer
```

Always arm the auto-revert first. A wrong rule locks you out of the RV LAN side too, and the
only recovery is then a keyboard on the Pi.

## Verify

```bash
sudo sophie-firewall.sh status
```

A healthy IPv4 and IPv6 ruleset has **all five** of:

1. `-A INPUT -j SOPHIE-IN` present, at position 1
2. `-A FORWARD -j SOPHIE-FWD` present
3. `-A DOCKER-USER -j SOPHIE-FWD` present
4. `-P FORWARD DROP`
5. packet counters climbing on the `SOPHIE-*` ACCEPT rules

Checking 1-4 is the whole point: the chains can exist, and `systemctl status` can be green,
while nothing is hooked to them (see the trap below). The dashboard's Debug page has a
**Host Firewall** card that evaluates exactly these, which is the easiest way to look.

The outside test, per uplink, from a device on that same network (not on Sophie's WiFi):

```bash
nmap -Pn -p- <Sophie's uplink IPv4>          # expect: all filtered
nmap -6 -Pn -p 22,80,1883,5900,8000,9001 <addr>   # if a global v6 address exists
```

"Filtered" alone does not prove the firewall did it -- a scan of a dead address reads the same. Confirm from
on-box that the packets actually arrived and were dropped: watch `SOPHIE-IN`'s drop counter climb, and check
the arrival interface in the log, which is the part that is easy to get wrong:

```bash
sudo journalctl -k --since -5min | grep "SOPHIE-IN drop" | grep "SRC=<scanner IP>"
```

The `IN=` field must name the uplink you aimed at. A plain `journalctl -k` as a non-root user exits 0 and
prints nothing, so use `sudo`.

If two of Sophie's interfaces hold addresses on the same subnet -- routine at home, where the Realtek is in
the house LAN and the Alfa is on the house WiFi -- ARP flux will send your scan in through whichever NIC
answered, and you will test the wrong interface without noticing. `raspap/90-arp-multihome.conf`
(`arp_ignore=1`, `arp_announce=2`) prevents that; verify from the scanning host that the two addresses resolve
to two *different* MACs before trusting a per-interface result.

## Traps

**`netfilter-persistent` races this at boot and wins.** Its `iptables-restore` flushes the
whole filter table, deleting our chains and their hooks. On 2026-10-21 both units started in
the same second and the INPUT side lost: `SOPHIE-IN` was deleted mid-build (journal:
`Chain 'SOPHIE-IN' does not exist`), the INPUT hook never landed, and Sophie sat fully exposed
on `eth1`/`wlan1` — while `sophie-firewall.service` reported success, because the script runs
`set -uo pipefail` without `-e` and exits 0 regardless. `SOPHIE-FWD`, built a moment later,
survived, so the forward side looked fine. Fixed by ordering `sophie-firewall.service`
`After=netfilter-persistent.service`. `/etc/iptables/rules.v4` is otherwise dead weight —
`pi5connect.sh` installs the MASQUERADE rule itself on every WAN change — so disabling
`netfilter-persistent` outright is the cleaner end state.

**A green unit is not a working firewall.** `apply` exits 0 even when individual `iptables`
calls fail. Check the hooks, not the unit.

**Anything that rewrites the filter table drops our hooks.** `pi5connect.sh` only appends
under `-C` guards and is safe, but a future `iptables -F`/`iptables-restore` from any script
would silently disarm this. Re-run `apply` after one.

**Don't mix in native `nft` rules.** Host and Docker both use the `nf_tables` backend through
`iptables-nft`; a hand-written `nft` chain in the same tables confuses both.
