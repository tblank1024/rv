# plan_firewall.md — Host firewall for Sophie (all uplinks)

STATUS: Armed on Sophie as of 2026-10-23 (INPUT hook at position 1 for IPv4 and IPv6, FORWARD and DOCKER-USER
hooked, `FORWARD` policy DROP; dashboard, MQTT, client internet and all 9 containers healthy).
Operator's view: `firewall/README.md`.

**Proven at boot 2026-10-23 11:44.** The `After=netfilter-persistent.service` fix works: the journal shows
`netfilter-persistent` *finished* at 11:44:35 before `sophie-firewall` *started*, with none of the
`Chain 'SOPHIE-IN' does not exist` errors from the failed attempt, and `status` reports `== ARMED` with the
INPUT hook at position 1 for both families. Item 4 is closed.

The 2026-10-21 reboot test **failed and the failure was silent** -- see item 4 below. `netfilter-persistent`
raced this plan's unit at boot, its `iptables-restore` deleted `SOPHIE-IN` mid-build, the INPUT hook never
landed, and Sophie sat fully exposed on `eth1`/`wlan1` for two days while `systemctl status` stayed green
(`apply` had no `set -e` and exited 0 anyway). Fixed in commit e7c4d06: `After=netfilter-persistent.service`
ordering, a `verify()` that checks the hooks and fails the unit, and a Host Firewall card on the dashboard's
Debug page so this is visible without reading chains by hand.

Still to do: **outside `nmap` from a home-WiFi device** (the one check that cannot be done from on-box), disable `netfilter-persistent`, review
`SOPHIE-IN drop:` logs over a few days parked at home, phase 2 hardening.
Supersedes issue 12 in `plan_new_WAN_WiFi.md`.

Written 2026-10-12, when the uplink was the Zero 2W bridge. **The Zero was physically disconnected on
2026-10-18 and the WiFi radio is now the Alfa on Sophie's own `wlan1`** (`plan_new_WAN_WiFi.md`). The Sophie
half of this plan still applies as written — `wlan1` was already in its untrusted list. The "Zero 2W bridge"
section does not: there is no `usb0` and no `10.10.0.x`. Keep it only for the case where the Zero is revived.

Intended executor: a Claude Code agent on Sophie, with the user confirming the steps marked **[USER]**.

## Problem

Sophie (RP5) has two sides:

- **Trusted:** `br0` (the RV LAN: onboard WiFi AP + `eth0`), `lo`, and Docker's own bridges.
- **Untrusted:** whichever uplink is active: the Alfa USB WiFi adapter (`wlan1`, live since 2026-10-18, on a
  direct RP5 port), plus Starlink, direct Ethernet and the cellular modem on the Plugable USB hub. Names vary
  (`eth1`, `eth2`, `wwan0`, `wlan1`, ...). Historically also the Zero 2W bridge on `usb0` (`10.10.0.x`), now
  disconnected. Note `enx*` never appears on this host — see `WifitoHostBridge/CLAUDE.md`.

NAT (MASQUERADE from `raspap/pi5connect.sh`) protects the **RV LAN devices**, but not **Sophie herself**: a
connection to Sophie's uplink address is delivered to her own services. Today nothing filters that:

- `/etc/iptables/rules.v4` from `buildRP5RaspAP/install_raspap_bridge.sh` has `INPUT ACCEPT` and
  `FORWARD ACCEPT` policies, and every rule in it is an ACCEPT.
- No `ip6tables` rules anywhere in the repo.
- Every container is `network_mode: host`, and services bind all interfaces:
  - webserver/dashboard, `0.0.0.0:8000`: no auth, privileged, can reboot Sophie, control Docker and USB hub power
  - mosquitto `1883`: auth required
  - mosquitto `9001` (websocket): anonymous read-only, which leaks all RV telemetry
  - SSH 22, wayvnc 5900, RaspAP web UI 80, dnsmasq 53, mDNS 5353

Exposure by uplink:

| Uplink | IPv4 inbound to Sophie | IPv6 inbound to Sophie |
|---|---|---|
| Starlink | blocked by carrier-grade NAT (accidental protection) | Starlink hands out global IPv6: possibly exposed to the internet |
| Cellular | usually CGNAT / modem NAT | often global IPv6; carrier filtering not guaranteed |
| Zero bridge | Zero's NAT shields from the park LAN | probably not forwarded |
| Direct park Ethernet | **exposed to every device on the park LAN** | exposed if the park offers v6 |
| Alfa `wlan1` (coming) | **exposed to every device on the park WiFi** | exposed if the park offers v6 |

Also, with `FORWARD ACCEPT`, a host on the same park subnet can route `10.0.0.0/24` via Sophie and reach RV LAN
devices directly. NAT doesn't stop that.

## Design

**Default-deny by interface, not by uplink name.** Trust a short list of LAN-side interfaces and treat
*everything else* as untrusted. New uplinks (Alfa, a different modem, a renamed `enx*`) are then protected
automatically, with no tracking of which uplink is active.

| Chain | Trusted interfaces (`lo`, `br0`, `docker0`, `br-+`) | Untrusted (everything else) |
|---|---|---|
| INPUT (to Sophie) | accept | only replies to connections Sophie started (conntrack ESTABLISHED,RELATED) |
| FORWARD (through Sophie) | `br0` → anywhere accept; Docker bridges: let Docker's rules decide | only replies; new connections dropped |
| IPv6 | same, plus the ICMPv6 needed for neighbor discovery / RA / DHCPv6 replies | same |

Notes:
- Interface-based rules avoid subnet confusion (the repo has both `10.0.0.1/24` and `10.3.141.1/24` for `br0`).
- `br-+` matches Docker user bridges (`br-<id>`), not `br0`.
- Docker loads `br_netfilter`, so WiFi↔`eth0` traffic inside `br0` also traverses FORWARD (`-i br0 -o br0`). The
  `-i br0` accept covers it.
- Docker inserts its own jumps at the top of FORWARD on every (re)start. The documented place for user rules that
  Docker must not bypass is the `DOCKER-USER` chain, which Docker always evaluates first. So the forward chain is
  hooked from both FORWARD (works without Docker) and DOCKER-USER (works with it). All containers are host-network
  today, so published ports are moot, but this keeps it correct if that changes.
- Rules live in our own chains (`SOPHIE-IN`, `SOPHIE-FWD`). The script only flushes its own chains; it never runs
  `iptables -F` (which would wipe Docker's and `pi5connect.sh`'s rules).
- INPUT/FORWARD policies: FORWARD → DROP (Docker sets this anyway). INPUT policy stays ACCEPT. `SOPHIE-IN` is at
  position 1 and decides every packet, so a botched hook removal fails open instead of locking everyone out.
- `pi5connect.sh` keeps doing NAT/default route. Its FORWARD/INPUT accept rules become redundant but harmless.
- Rate-limited LOG before each DROP, to find anything legitimate that breaks. Journald is volatile now, so there are
  no SD writes. Remove the LOG lines after the first weeks if noisy.

## The script — `firewall/sophie-firewall.sh`

```bash
#!/bin/bash
# Sophie host firewall: default-deny inbound/forward on every interface except the RV LAN side.
# Usage: sophie-firewall.sh apply | docker | revert | status
set -uo pipefail

TRUSTED=(lo br0 docker0 "br-+")          # everything else (eth1, eth2, wlan1, usb0, wwan0, enx*, ...) is untrusted

chain() { "$1" -N "$2" 2>/dev/null || "$1" -F "$2"; }
hook()  { "$1" -C "$2" -j "$3" 2>/dev/null || "$1" -I "$2" 1 -j "$3"; }
unhook(){ while "$1" -D "$2" -j "$3" 2>/dev/null; do :; done; }

build_in() {   # $1 = iptables | ip6tables
    local T=$1
    chain $T SOPHIE-IN
    for i in "${TRUSTED[@]}"; do $T -A SOPHIE-IN -i "$i" -j ACCEPT; done
    $T -A SOPHIE-IN -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
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

case "${1:-}" in
  apply)
    for T in iptables ip6tables; do build_in $T; build_fwd $T; done ;;
  docker)   # run after dockerd (re)starts: make sure Docker's first-evaluated chain sends us the traffic
    for T in iptables ip6tables; do
        $T -L DOCKER-USER -n >/dev/null 2>&1 && $T -L SOPHIE-FWD -n >/dev/null 2>&1 && hook $T DOCKER-USER SOPHIE-FWD
    done ;;
  revert)   # back to today's behavior (everything open)
    for T in iptables ip6tables; do
        unhook $T INPUT SOPHIE-IN; unhook $T FORWARD SOPHIE-FWD; unhook $T DOCKER-USER SOPHIE-FWD
        $T -F SOPHIE-IN 2>/dev/null; $T -X SOPHIE-IN 2>/dev/null
        $T -F SOPHIE-FWD 2>/dev/null; $T -X SOPHIE-FWD 2>/dev/null
    done
    iptables -P FORWARD ACCEPT ;;     # previous rules.v4 state; Docker may set DROP again on restart
  status)
    for T in iptables ip6tables; do echo "== $T"; $T -S INPUT | head -3; $T -S FORWARD | head -4
        $T -S DOCKER-USER 2>/dev/null | head -3; $T -L SOPHIE-IN -v -n 2>/dev/null; $T -L SOPHIE-FWD -v -n 2>/dev/null; done ;;
  *) echo "usage: $0 apply|docker|revert|status" >&2; exit 2 ;;
esac
```

Check before deploying: `iptables -V` shows `nf_tables` (Bookworm default) and Docker uses the same backend.
Don't mix in native `nft` rules.

## systemd units — `firewall/`

`sophie-firewall.service`: early, before any interface comes up (closes the boot window):
```ini
[Unit]
Description=Sophie host firewall (default-deny on uplinks)
DefaultDependencies=no
After=local-fs.target
Before=network-pre.target
Wants=network-pre.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/local/sbin/sophie-firewall.sh apply

[Install]
WantedBy=multi-user.target
```

`sophie-firewall-docker.service`: re-hooks DOCKER-USER whenever Docker (re)starts:
```ini
[Unit]
Description=Sophie firewall hook into DOCKER-USER
After=docker.service sophie-firewall.service
PartOf=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/local/sbin/sophie-firewall.sh docker

[Install]
WantedBy=docker.service
```

`firewall/install.sh`: copies the script to `/usr/local/sbin/`, the units to `/etc/systemd/system/`, then runs
`daemon-reload` and `enable` (not `--now`, see rollout). Add the matching entries to the passwordless-sudo drop-in,
following `sdcard-writes/setup-passwordless-sudo.sh`.

## Things that will break unless handled

1. **SSH/VNC to Sophie through an uplink.** README/CLAUDE.md mention reaching Sophie at `192.168.2.196` from home.
   That address is on the home network via an uplink, so it will be blocked. **Decision (2026-10-12): no
   exceptions.** There is no inbound allow-list (e.g., SSH from the home subnet), because a park network can use
   the same subnet. Instead:
   - At home: Raspberry Pi Connect (dials out; has both a remote shell and screen sharing), or put the laptop on
     Sophie's WiFi (trusted `br0`; direct SSH and VNC work).
   - On the road: same. Later, Tailscale/WireGuard for remote access (dials out, works through CGNAT, no open ports).
   - Update README/CLAUDE.md's `192.168.2.196` SSH instructions accordingly once deployed.
2. **Home automation talking to Sophie.** If HA (192.168.2.11) or anything at home connects *to* Sophie (MQTT
   bridge, API polling) while parked at home, it will be dropped. Check the `SOPHIE-IN drop:` log lines at home,
   and decide per case. Prefer making the connection go outward from Sophie (e.g., Sophie
   publishes to HA's MQTT) over adding an inbound exception.
3. ~~**The Zero 2W link (`10.10.0.x`) is untrusted.**~~ Moot since 2026-10-18: no `usb0`, and TCP:12345 was
   retired with the socket path. The WiFi API is now `127.0.0.1:12346` on Sophie herself, reached over `lo`,
   which is in `TRUSTED`. Keep it off `br0`: a root API reachable there lets any RV guest reconfigure the uplink.
4. **`netfilter-persistent` races this unit at boot and wins.** *(Corrected 2026-10-23; this item previously
   said "harmless (our chains decide)", which was wrong and cost two days of exposure.)* Its `iptables-restore`
   **flushes the entire filter table**, deleting our chains and their hooks -- it does not merely add permissive
   rules alongside them. On 2026-10-21 both units started in the same second; `SOPHIE-IN` was deleted while
   `build_in` was still appending to it (journal: `Chain 'SOPHIE-IN' does not exist`, both families) and the
   INPUT hook was lost. `SOPHIE-FWD`, built a moment later once the restore had finished, survived, so the
   forward half looked healthy and hid the problem.
   Fixed by `After=netfilter-persistent.service` on `sophie-firewall.service`, which holds whether or not
   `netfilter-persistent` is enabled. `pi5connect.sh` installs the MASQUERADE rule itself on every WAN change
   (confirmed: `nat POSTROUTING` carries `-o eth1 -j MASQUERADE` with no help from `rules.v4`), so
   `systemctl disable netfilter-persistent` is the clean end state and `/etc/iptables/rules.v4` is dead weight.
   The same hazard applies to anything else that rewrites the filter table: re-run `apply` after one.
5. **IPv6 outbound keeps working** (replies are allowed). If preferred, also disable v6 per uplink profile
   (`nmcli con modify <profile> ipv6.method disabled`), as `plan_new_WAN_WiFi.md` suggests for `wlan1`.

## Rollout (on Sophie)

1. Snapshot the current state:
   `sudo iptables-save > ~/fw-before.v4; sudo ip6tables-save > ~/fw-before.v6; sudo ss -tulpn > ~/fw-listen.txt`.
2. Create `firewall/` (script, units, `install.sh`, README) from this plan; commit.
3. **[USER]** confirm Pi Connect (remote shell + screen sharing) works *before* applying, since it's the remote
   path once the WAN side is closed.
4. Install the script only (units not enabled yet), arm an automatic revert, then apply by hand:
   ```bash
   sudo install -m 755 firewall/sophie-firewall.sh /usr/local/sbin/
   sudo systemd-run --unit=fw-autorevert --on-active=10min /usr/local/sbin/sophie-firewall.sh revert
   sudo /usr/local/sbin/sophie-firewall.sh apply && sudo /usr/local/sbin/sophie-firewall.sh docker
   ```
5. Functional checks (all must pass within the 10 minutes):
   - From the RV LAN: dashboard loads, live MQTT data updates (9001), SSH and VNC to `br0` address work.
   - Roku / a LAN device reaches the internet.
   - On Sophie: `docker ps` all healthy, the containers' MQTT connections OK (watcher, battery, tirelinc, ...),
     `curl -s http://10.10.0.1:12346/api/status` (Zero API) works, Pi Connect still connected, `apt update` works.
   - `sudo sophie-firewall.sh status` shows packet counters moving on the ACCEPT rules.
6. If good: `sudo systemctl stop fw-autorevert.timer`, then `firewall/install.sh` (enable the units). Reboot once
   and repeat step 5; also `sudo systemctl restart docker` and confirm `iptables -S DOCKER-USER` still jumps to
   `SOPHIE-FWD`.
   **After the reboot, check the hooks, not the unit.** `sophie-firewall.sh status` now ends in `ARMED` or
   `NOT ARMED`, and the dashboard's Debug page has a Host Firewall card; a green `systemctl status` on its own
   means nothing (item 4). Specifically confirm `-A INPUT -j SOPHIE-IN` exists **at position 1** for both
   families -- that is the rule that went missing in the first attempt.
7. If bad: wait for the auto-revert or run `revert`, then capture `journalctl -k | grep SOPHIE-` and fix.

## Verification per uplink

Repeat whenever a new uplink type is first used:

| Uplink | How to test from the outside |
|---|---|
| Direct park Ethernet / park WiFi (Alfa) / home LAN | From a laptop on that same network (not on Sophie's WiFi): `nmap -Pn -p- <Sophie uplink IPv4>` → all filtered; if Sophie has a global v6 address: `nmap -6 -Pn -p 22,80,1883,5900,8000,9001 <addr>` |
| Starlink | `ip -6 addr show <uplink>`: if there's a global address, scan it from outside (e.g., phone hotspot with IPv6, or an online IPv6 port scanner) → filtered |
| Cellular | same as Starlink |
| ~~Zero bridge~~ | n/a since 2026-10-18 (disconnected). If revived: from the Zero, `nc -vz -w 5 10.10.0.17 8000` → times out |

And always: the RV LAN functional checks from rollout step 5.

## Zero 2W bridge (`RP2W`) — historical, do not deploy

**Skip this section.** The Zero was physically disconnected from Sophie on 2026-10-18 and its radio is replaced
by the Alfa on `wlan1`. Everything below assumes a live `usb0`/`10.10.0.0/24` and an SSH path to the Zero, none
of which exist. It is kept because nothing else records the Zero's firewall design, and reviving the Zero would
need it (see `WifitoHostBridge/zero-system/README.md`).

The Zero sits on the untrusted network itself (its `wlan0` joins the park/home WiFi), so it needs its own firewall.
Facts from `WiFitoHostBridge/zero-system/README.md`:
- `usb0` = USB link to Sophie, static `10.10.0.1/24`, unmanaged by NM.
- Sophie gets `10.10.0.17` from the Zero's `dhcpd` on `usb0`.
- `netfilter-persistent` loads `/etc/iptables/rules.v4`/`rules.v6`, which hold the `MASQUERADE` out `wlan0`. The
  current contents were never captured.

**Baseline scan (2026-10-12)** from the laptop on the same WiFi as the Zero (`RP2W`, 192.168.1.212):
`nmap -Pn -p-` → `22/tcp open ssh`, the other 65534 ports **closed** (not filtered). So no firewall; only SSH is
exposed. The WiFi APIs (12345/12346) are correctly bound to `10.10.0.1` only. Sophie is not visible from that
network (she's behind the Zero's NAT).

### Rules

The Zero has no Docker, so plain `netfilter-persistent` files are enough, and they load at boot before networking.
Trust `lo` and `usb0`; on `wlan0` allow only replies. Forward only Sophie → internet.

`/etc/iptables/rules.v4` (merge with whatever is there now; keep any existing NAT lines):
```
*nat
:PREROUTING ACCEPT [0:0]
:INPUT ACCEPT [0:0]
:OUTPUT ACCEPT [0:0]
:POSTROUTING ACCEPT [0:0]
-A POSTROUTING -o wlan0 -j MASQUERADE
COMMIT
*filter
:INPUT DROP [0:0]
:FORWARD DROP [0:0]
:OUTPUT ACCEPT [0:0]
-A INPUT -i lo -j ACCEPT
-A INPUT -i usb0 -j ACCEPT
-A INPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
-A INPUT -m limit --limit 6/min -j LOG --log-prefix "ZERO-IN drop: "
-A FORWARD -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
-A FORWARD -i usb0 -o wlan0 -j ACCEPT
-A FORWARD -m limit --limit 6/min -j LOG --log-prefix "ZERO-FWD drop: "
COMMIT
```

`/etc/iptables/rules.v6`:
```
*filter
:INPUT DROP [0:0]
:FORWARD DROP [0:0]
:OUTPUT ACCEPT [0:0]
-A INPUT -i lo -j ACCEPT
-A INPUT -i usb0 -j ACCEPT
-A INPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
-A INPUT -p ipv6-icmp --icmpv6-type 133 -j ACCEPT
-A INPUT -p ipv6-icmp --icmpv6-type 134 -j ACCEPT
-A INPUT -p ipv6-icmp --icmpv6-type 135 -j ACCEPT
-A INPUT -p ipv6-icmp --icmpv6-type 136 -j ACCEPT
-A INPUT -p udp -s fe80::/10 --dport 546 -j ACCEPT
COMMIT
```

Notes:
- Policies are DROP here, unlike Sophie: there's no Docker re-ordering chains, and `usb0` (the only control path)
  is explicitly trusted. A typo in `usb0` would lock out control, hence the auto-revert below.
- `dhcpd` on `usb0` (Sophie's lease) and the WiFi APIs on `10.10.0.1` are covered by the `usb0` accept.
- The Zero's journal may be on the SD card. The LOG lines are rate-limited (6/min); drop them once things are
  stable if SD writes matter.

### SSH on the Zero
- Key-only: `/etc/ssh/sshd_config.d/10-keys-only.conf` → `PasswordAuthentication no`. First confirm that Sophie →
  Zero key login works (`ssh -o BatchMode=yes pi@10.10.0.1 true`) and that the laptop has a key on the Zero, or
  always goes through Sophie.
- The firewall already hides SSH from `wlan0`. Don't add `ListenAddress 10.10.0.1`: sshd would fail to start if
  `usb0` isn't up yet, and the firewall makes it unnecessary.

### Rollout (agent on Sophie, over `ssh pi@10.10.0.1`)
The agent's own internet goes through the Zero's FORWARD chain, so arm the revert *on the Zero* first. If the
session dies, the Zero restores itself.
1. Capture: `sudo iptables-save > /root/fw-before.v4; sudo ip6tables-save > /root/fw-before.v6;
   sudo cp /etc/iptables/rules.v4 /etc/iptables/rules.v6 /root/`. Copy both into
   `WiFitoHostBridge/zero-system/` (the README notes they were never captured).
2. Write the new files to `/tmp/rules.v4.new`, `/tmp/rules.v6.new`; test-parse them with
   `sudo iptables-restore --test /tmp/rules.v4.new` and `sudo ip6tables-restore --test /tmp/rules.v6.new`.
3. Arm and apply (atomic restore, not saved yet):
   ```bash
   sudo systemd-run --unit=fw-autorevert --on-active=5min        sh -c 'iptables-restore < /root/fw-before.v4; ip6tables-restore < /root/fw-before.v6'
   sudo iptables-restore < /tmp/rules.v4.new && sudo ip6tables-restore < /tmp/rules.v6.new
   ```
4. Check from Sophie: `ssh pi@10.10.0.1 true`, `curl -s http://10.10.0.1:12346/api/status`, Sophie's internet
   (`curl -sI https://deb.debian.org`), Claude session still alive.
5. If good: `sudo systemctl stop fw-autorevert.timer`, then
   `sudo cp /tmp/rules.v4.new /etc/iptables/rules.v4; sudo cp /tmp/rules.v6.new /etc/iptables/rules.v6`. Reboot the
   Zero **[USER]** (drops the agent's internet for a minute) and repeat step 4.
6. **[USER]** From a laptop on the same WiFi as the Zero: `nmap -Pn -p- <Zero wlan0 IP>`. Expect all ports
   **filtered** (baseline: 22 open, rest closed).
7. Commit the new `rules.v4`/`rules.v6` into `WiFitoHostBridge/zero-system/` and update its README table.

## Phase 2 hardening (after the firewall is in)

Defense in depth. Each item still protects Sophie if a firewall rule is ever wrong.

1. **SSH key-only:** `PasswordAuthentication no` in `/etc/ssh/sshd_config.d/`. Confirm key login works first.
2. **Bind LAN-only services to the LAN address** where practical: uvicorn `host="0.0.0.0"` (`server.py:2387`) →
   `10.0.0.1` (check whether anything on Sophie uses `localhost:8000`; bind both or use a list). Mosquitto
   `listener 9001 10.0.0.1` (check `docker/mqtt/config/mosquitto.conf`). The 1883 listener needs localhost for the
   host-network containers.
3. **mDNS:** `/etc/avahi/avahi-daemon.conf` → `allow-interfaces=br0`.
4. **Dashboard auth:** at least for destructive endpoints (reboot, restart containers, hub power, WiFi
   connect/forget), since anyone on Sophie's WiFi can call them today.
5. **Least privilege for the webserver container:** `privileged`, `pid: host`, Docker socket. Already flagged in
   `docker-compose.yml` as "Phase 4 hardening".
6. **Updates:** periodic `apt full-upgrade` and image rebuilds.
7. **Remote access:** Tailscale/WireGuard instead of any inbound exception.
8. Aside: the (inactive) `raspap` compose profile sets `RASPAP_COUNTRY=GB`. Set it to `US` if it's ever enabled
   (regulatory domain, see `plan_new_WAN_WiFi.md` issue 8).

## Afterwards

- Update `buildRP5RaspAP/install_raspap_bridge.sh` so a rebuild doesn't recreate the permissive `rules.v4`. **Open.**
- ~~Add a "Firewall" line to `rv/CLAUDE.md`~~ done (`rv/CLAUDE.md`, "Host firewall").
- ~~Mark this plan deployed (STATUS line).~~ done 2026-10-23.
- `/etc/sudoers.d/sophie-firewall` grants NOPASSWD for the `status` verb only, via
  `firewall/setup-passwordless-sudo.sh`. Never widen it to the bare script path: `revert` must stay
  password-gated, or turning the firewall off becomes a passwordless one-liner.
