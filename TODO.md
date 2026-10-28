# TODO — Sophie (RV1-PI5)

Opened 2026-10-23 out of the firewall deployment (`plan_firewall.md`,
`firewall/README.md`). The sections below are grouped by the work they came out of and
carry the reasoning and the test evidence; **this index is the priority order.**
Reconciled 2026-10-27 against the live box, which closed five items that were already
done and merged three pairs of duplicates.

## Open work, most urgent first

Status as of 2026-10-27: items 1–4 and 6 are done (2 was already built in task C
on 10-26 and is now cross-linked); 5 is decided (leave on `0.0.0.0`) and 8 (remote
access / Tailscale) is dropped by owner decision. **The one open high-priority item is
7, `sophie-hostd`** — planned below, and it wants its own session.

| # | Item | State | Why it is here |
|---|---|---|---|
| 1 | RaspAP `:80` / `wayvnc` `:5900` default-or-empty passwords | **Done** | Both enforce auth, neither is empty, VNC is PAM-backed; owner confirmed the RaspAP admin password is non-default. |
| 2 | Alert when `sophie-firewall` reads NOT ARMED | **Done** (task C, 10-26) | Already built: `RVC/RV_Health/1` `firewall_armed` → watcher bounds → `SYS_ERRORS` → dashboard + MQTT. Verified live. On-box by the owner's choice. |
| 3 | Review the `SOPHIE-IN drop:` logs | **Done** | 23 h reviewed: zero TCP drops from the home LAN, nothing aimed at Sophie's service ports. Nothing legitimate dropped. |
| 4 | Turn on unattended security upgrades | **Done** | Installed, security-only, no auto-reboot; 60-package security backlog applied. |
| 5 | Bind the dashboard `:8000` off the uplink | **Decided: leave on `0.0.0.0`** | Firewall already confines it and now self-alerts; the clean fix is a two-socket refactor with a `br0` startup race. Same trade as mosquitto 1883. |
| 6 | mDNS `allow-interfaces=br0` | **Done** | avahi was announcing on both uplinks; now br0 only. |
| 7 | `sophie-hostd` on `127.0.0.1` | **DONE 2026-10-28** — webserver fully de-privileged | Removed `privileged`/`pid:host`/`docker.sock` and `/sys/bus/usb`; ALL host ops (incl. modem rebind) go through sophie-hostd. Fallback code deleted. No privileged path left. |

Blocked on being somewhere else, not on effort:

| Item | Needs |
|---|---|
| Scan the cellular v6 address from outside | A laptop with global IPv6. Home ISP has none. |
| Starlink path of the Internet selector | A trip — no sky in the garage. |
| Stale rules for a dead WAN | A real uplink change while the `pi5connect` lock is in force. |
| A true cold boot | Someone at the RV, hub fully de-energised. |
| Install the `wan-*` `.link` files | A boot where the WAN renames itself; check NM profiles first. |

## Check at the next reboot

```bash
sudo /usr/local/sbin/sophie-firewall.sh status | tail -1   # expect: == ARMED
/usr/sbin/sysctl net.ipv4.conf.all.arp_ignore \
                 net.ipv4.conf.all.arp_announce            # expect: 1 and 2
arp -a | grep -E '192\.168\.2\.(197|107)'                 # from the laptop: two DIFFERENT MACs
```

Full paths on purpose. A `systemd --user` unit does not inherit a login shell's `PATH`, so
in the RV-Manager session started by `rv-manager.service` a bare `sysctl`, `iptables` or
`nft` is "command not found" -- that is how this was found, answering the stage-1 checks on
2026-10-23. The unit's `Environment=PATH=` now includes `/usr/sbin:/sbin`, effective from
the *next* boot, but the full paths work either way.

**Passed 2026-10-23 16:08 (stage 1, both uplinks still connected).** Boot 16:08:52;
`netfilter-persistent` *finished* 16:08:55 before `sophie-firewall` *started*, no
`Chain 'SOPHIE-IN' does not exist`, `== ARMED`, `-A INPUT -j SOPHIE-IN` at position 1 for
both families, `arp_ignore`/`arp_announce` 1/2 from `/etc/sysctl.d/`, and the laptop saw two
distinct MACs with 7/7 ports filtered on both addresses. `rv-manager.service` went active
7 s after boot and resumed the right conversation.

Still **not** exercised across a USB-uplink switch (Starlink or cellular in place of the
current pair) -- stage 2. First time one comes up, re-run the three checks above and the
per-uplink `nmap` below, and check two things that only a WAN change can break: that
`SOPHIE-IN` still holds the `INPUT` hook after `pi5connect` rewrites the NAT/FORWARD rules
for the new WAN, and that the new cellular interface is closed with **no new rule** -- it
should be untrusted by default rather than by name. Note the modem does *not* appear as
`wwan0`: it is a `cdc_ether` dongle (TCL 1bbb:0646) and enumerates as a plain `eth*`,
`eth2` on 2026-10-23, which is exactly why nothing keys policy on interface names.

**Passed 2026-10-23 18:04 (stage 2, cellular).** A first run at 16:27-16:35 proved the
switch itself but not a sustained session -- the Alfa re-associated at 16:34:46 and
pi5connect preferred it, as designed. The second run, with the Alfa *physically unplugged*,
held. Timeline from `/var/log/pi5connect.log` and `/var/log/wan-scan.log`:

| 18:04:00 | `wlan1` down; old WAN rules removed; "no other interface is up with an address" |
| 18:04:00 | handed off to `wan_scan --on-loss`, the only component that may power a gated socket |
| 18:04:10 | socket 2 (wired) rejected, no carrier after 10 s; socket 1 (wifi) powered but nothing plugged in |
| 18:04:11 | socket 3 (cellular) powered on |
| 18:04:31 | `eth2` enumerated, +20 s |
| 18:04:47 | lease `192.168.0.178/24`, +36 s |
| 18:04:56 | default route via `192.168.0.1` dev `eth2`; NAT/FORWARD rewritten |
| 18:05:00 | `wan_scan` commits socket 3. **Total outage ~60 s.** |

All four hooks survived the rewrite, `== ARMED`, `-A INPUT -j SOPHIE-IN` at position 1 in
both families, and `eth2` is in **no** INPUT rule -- untrusted by default rather than by
name, which was the point. 25 `SOPHIE-IN drop` lines with `IN=eth2` across both families
confirm the drop path on the new interface.

Three things this run taught that the home-LAN tests could not:

- **Over cellular Sophie has a globally routable IPv6 address and no v6 NAT.** `eth2` held
  `2607:fb91:15d5:cf08::3d5/128` and a `/64` SLAAC address, and `curl -6 ifconfig.me`
  returned the interface address itself. On v4 it is double NAT (private on the interface,
  `172.56.105.86` public) and unreachable; on v6 the box is directly addressable from the
  internet and `ip6tables` `SOPHIE-IN` is the only thing in the way. The v6 default-deny is
  not theoretical -- it is load-bearing the moment cellular comes up. Any future outside
  scan should target the v6 address, which is where the real attack surface is.
- **`pi5connect`'s per-WAN `FORWARD` accepts are dead code.** Tested with a real RV-LAN
  client (a veth into `br0` in its own netns at `10.0.0.250`): it reached the internet and
  resolved DNS, while `br0 -> eth2` and `eth2 -> br0` stayed at **0 packets**. `SOPHIE-FWD`
  runs first and its `-i br0 -j ACCEPT` plus `RELATED,ESTABLISHED` already carry the whole
  path. Harmless, but `pi5connect` maintains rules that never match.
- **A fresh cellular lease is not usable for ~10 s,** which reads at first like a policy
  block. `pi5connect` logged `ICMP probe failed on eth2; trying TCP` and fell back, so the
  first conclusion recorded here was "the dongle blocks outbound ICMP". **That was wrong.**
  On the 19:06 boot the ICMP probe succeeded on the first try, and a later `ping` gave
  0% loss on both families (37-56 ms v4, 42-44 ms v6). The failures were at +6 s and +9 s
  after the lease: the modem's data path simply was not ready yet. Worth having straight,
  because "ICMP is blocked" would send a future debugging session looking for a filter that
  does not exist. The TCP fallback is what papers over the warm-up, and it earns its keep.

The gating interlock added in `f5cc58a` was exercised for real: `pi5connect` logged
`Gating: wan_scan is walking; leaving socket power alone` three times, declining to touch
socket power while `wan_scan` held `/run/wan-scan-in-progress`.

Clean on cellular as well: 5 MB over **both** v6 and v4 at ~1.27 MB/s, so there is no
PMTUD black hole -- a dropped ICMPv6 *packet too big* would stall large v6 transfers while
small ones worked, and the `RELATED,ESTABLISHED` rule ahead of the ICMPv6 allows catches
those errors. All 9 containers up, dashboard 200 on `10.0.0.1:8000`, MQTT 1883 open.

### The one gap in the cellular run: UNREACHABLE, not passed

- [ ] **Scan the cellular v6 address from outside.** Not done, and *not* skipped: the
      laptop cannot reach internet IPv6 at all. The home ISP has no native v6, the laptop
      holds only ULA `fd69:…` addresses, and `ping -6 2606:4700:4700::1111` returns
      "General failure" -- no route. So the v6-over-cellular exposure above rests on a
      **reading of the rules, not on a packet from outside.** Given that the home-LAN test
      already taught us "filtered" is indistinguishable from "unreachable" unless you
      corroborate on-box, this gap deserves to stay open and visible.
      Options next time cellular is up: tether the laptop to a phone hotspot with global
      v6 and run `nmap -6 -Pn -p- <addr>`, or use an online v6 port scanner -- the latter
      sends Sophie's address to a third party, so it is the user's call, not a default.
      Whichever is used, corroborate from on-box: get the scanner's source v6 address and
      confirm `SOPHIE-IN drop` lines with that `SRC=` and `IN=eth2`.

## Check after the cellular-only boot (2026-10-23 ~19:00)

Rebooted deliberately with the Alfa and wired **unplugged**, so cellular was the only
uplink. The earlier claim that a gated socket "boots unpowered" was wrong --
`wan-boot-check.service` states the opposite in its own header: *hub sockets default to
POWERED at boot, so gating is not in force until something applies it.* So what this
actually tests is the inverse and more dangerous case: at +75 s `wan-boot-check.service`
runs a plain `wan_scan` while **the current WAN is itself a gated socket**, something that
had never happened at boot. If the "keep" logic were wrong, Sophie would power off her own
only modem and go dark unattended.

Read the code before rebooting into it, and it is safe by construction: a walk only powers
sockets **on**, `cleanup()` powers back off only what it turned on and never the winner,
and the closing `power_off_gated_except "$CUR_LABEL"` is guarded by `-n "$CUR_LABEL"`, so
an empty `/run/pi5connect-wan` skips the enforce rather than guessing. Confirm:

**PASSED, boot 2026-10-23 19:06:28.** Uplink committed **6 s** after boot, no manual
nudge anywhere:

| 19:06:28 | boot |
| 19:06:33 | dispatcher `eth1 dhcp4-change` -- the modem was *already powered and leased*; the hub kept its socket energised across the Pi's reboot, so none of the 36 s cold cost was paid |
| 19:06:33 | `rv-manager.service` `ExecMainStart`; **active 5 s after boot**, resuming transcript `3978c097` |
| 19:06:34 | ICMP probe OK **first try**; default route via `192.168.0.1` dev `eth1` |
| 19:06:35 | `pi5connect` v2.3 complete, then `wan_scan --enforce-gating`: `role=cellular rank=3 socket=3` -- **kept** |
| 19:10:10 | `wan-boot-check` at +222 s: internet up, plain scan, 11 s, WAN unchanged |

`== ARMED`, `-A INPUT -j SOPHIE-IN` at position 1 in both families, `FORWARD` and
`DOCKER-USER` hooked, the cellular interface in **no** INPUT rule either family, 9/9
containers up, v4 and v6 both reaching the internet. `socket 3 off` lines in
`wan-scan.log`: **22, unchanged from the pre-boot baseline** -- the boot-time plain scan
did not power off its own only uplink, which was the one real risk in this test.

`arp_ignore`/`arp_announce` = 1/2, and read with a **bare** `sysctl`: the
`rv-manager.service` `PATH` fix adding `/usr/sbin:/sbin` is now in force (`$PATH` in the
autostarted session ends `…:/usr/sbin:/sbin`, and bare `iptables` and `nft` resolve too).
That item is closed.

### Power gating: measured, and the switch-back proved the other direction

- [x] ~~**Measure socket 3's draw**~~ Done 2026-10-23 with a meter at the socket:
      **~1 W powered and idle, 0 W switched off.** So the Plugable really does cut VBUS
      and `ppps` was not just a capability claim -- the assumption underneath `f5cc58a`
      is closed, and `usbhub/README.md`'s five-day-old "Untested" note is retired.
      Sized honestly: 24 Wh/day, ~2 Ah at 12 V. Noise with solar and daily use; it earns
      its keep over long unattended storage (~2.2 kWh, ~170 Ah over three months).

**The switch back to wired, 19:36, exercised gating in the direction that had only ever
been triggered by hand.** Five seconds end to end, on a real plug event:

```
19:36:10  eth2 up
19:36:11  Promoting eth2 (wired) over healthy eth1 (cell)
19:36:13  default route via 192.168.2.1 dev eth2
19:36:14  enforce: socket 3 off (gated, keeping socket 2)
19:36:15  socket 3 -> off (hub API)
```

Modem gone from `lsusb`, `eth1` ceased to exist, `== ARMED` with all four hooks intact.
And the naming inverted a **second** time: wired came up as `eth2`, where it has always
been `eth1` on the home LAN, twenty minutes after cellular had been `eth1`. The same two
names meant opposite things within the hour. Nothing broke, because nothing keys on them.

### The finding this boot produced: the modem came up as `eth1`

Not `eth2`. It was the only USB-ethernet device present, so it took the first free name --
**the same name the wired uplink uses on the home LAN.** Anything keying on the interface
name would have called this "wired", ranked it 0 (best), stopped looking, and treated it as
non-gated, leaving the modem powered indefinitely. Instead the log reads:

```
current WAN eth1 role=cellular rank=3
===== wan_scan done: gating enforced, WAN=eth1 socket=3 =====
```

Role came from the **hub socket**, not the name. This is exactly the trap `CLAUDE.md`
warns about -- *"the interface name does not identify the uplink type -- don't key policy
on it"* -- and it fired for real, by accident of enumeration order, within one reboot of
being written down. Nothing to fix; it is the design working. Two consequences though:

- [ ] **Pin the USB-ethernet adapters** with `.link` files, the way `11-wlan-wan.link`
      pins the Alfa. Policy does not need it, but every *document*, log grep and debugging
      session does -- `eth1` meaning "wired" in one boot and "cellular" in the next is a
      trap for humans even when the code is immune.

      **Status corrected 2026-10-27: this is already written and is NOT installed.** The
      repo has `raspap/20-wan-wired.link`, `21-wan-cell.link` and `22-wan-starlink.link`,
      naming the adapters `wan-wired` / `wan-cell` / `wan-starlink`. `/etc/systemd/network`
      holds only `10-wlan-ap`, `11-wlan-wan`, `12-eth-onboard`, `99-default` and
      `73-usb-net-by-mac.link` (a symlink to `/dev/null`, i.e. the deliberate mask of the
      distro's `enx*` policy that `usbhub/README.md` mentions).

      Two things checked before deciding to leave them alone:

      - **They match by `Path=`, not MAC**, deliberately: the role belongs to the hub
        socket and the adapter is interchangeable (an AX88179B was swapped for an RTL8152
        on 2026-10-19 and the socket kept its meaning). So the item's own title is wrong;
        by-MAC was reconsidered and rejected.
      - **The paths still match the live devices**, despite the hub having moved to a USB 2
        port. `eth1` is `platform-xhci-hcd.0-usb-0:2.3.2:1.0` and `20-wan-wired.link`
        matches `...usb-0:2.3.2*`; `21-wan-cell.link` wants `2.3.1` and `22` wants `2.3.4`,
        which are hub ports 1 and 4 -- sockets 3 (Cellular) and 4 (Starlink) in the map.
        All three are correct for the current cabling. `wlan1` sits at `2.3.3` (socket 1)
        and is correctly left to `11-wlan-wan.link`.

      So installing them is a three-file copy. The reason not to do it in passing: **`.link`
      files apply at device creation**, so nothing happens until the next boot or re-plug --
      and then the live WAN interface comes up as `wan-wired` instead of `eth1`, unattended.
      Before deploying, confirm no NetworkManager connection profile is bound to the name
      `eth1` (`nmcli -f connection.interface-name con show <name>`), since a profile pinned
      to a name that no longer exists is how this goes wrong at 2 AM with nobody in the RV.
      `pi5connect.sh` itself is immune -- it resolves roles through the hub socket.
- Anywhere these notes say `eth2` for the modem, read "whatever `eth*` it got this boot".
  The v6 address also changed across the reboot, `…::3d5` -> `…::5c5`, confirming it is
  dynamic and that any outside v6 scan has to be done against a freshly read address.

## Firewall — finish the deployment

- [x] ~~**Reboot and confirm `ARMED`.**~~ Done 2026-10-23 11:44. The ordering fix holds on
      the boot path: `netfilter-persistent` *finished* at 11:44:35 before `sophie-firewall`
      *started*, no `Chain 'SOPHIE-IN' does not exist` errors, `status` reports `== ARMED`,
      and both families have `-A INPUT -j SOPHIE-IN` at position 1 with `FORWARD` and
      `DOCKER-USER` hooked and policy DROP.
      Re-check after any reboot with `sudo sophie-firewall.sh status | tail -1`, or the
      dashboard's Host Firewall card.

- [x] ~~**Outside `nmap`**~~ PASSED 2026-10-23, home LAN, scanner `192.168.2.218`: all 65535
      TCP ports **filtered** on `192.168.2.197` (eth1), and `192.168.2.107` (wlan1) scanned
      the same way. Corroborated from on-box rather than taken on trust — `SOPHIE-IN` went
      from 971 to 401,126 v4 drops, with logged SYNs from the scanner to both addresses, so
      the packets arrived and were dropped (a scan of a dead address also reads "filtered").
      A v6 SYN to port 8000 against the eth1 ULA was dropped too.
      `wlan1` confirmed as an interface on the **second** pass, 2026-10-23 15:49, after
      `arp_ignore=1` closed the ARP flux: scanner `192.168.2.218` saw 7/7 ports filtered on
      `192.168.2.107`, and the SYN logged on-box was
      `IN=wlan1 ... MAC=00:c0:ca:be:29:62:08:3a:88:55:27:80:08:00 DST=192.168.2.107 DPT=5900`
      — dest MAC the Alfa, source MAC the laptop, so the frame was addressed to the Alfa,
      arrived on the Alfa and was dropped. No `IN=eth1 DST=192.168.2.107` lines since.
      (The first pass had the reverse: all 127 probes aimed at `wlan1`'s address landed
      `IN=eth1`, which is what made it ambiguous.)
      Still to repeat **per uplink type on first use** — Starlink and cellular have not been
      scanned. Table in `plan_firewall.md` §"Verification per uplink".
      ```bash
      nmap -Pn -p- <Sophie's uplink IPv4>     # expect: all filtered
      ```

- [x] ~~**Disable `netfilter-persistent`.**~~ Done 2026-10-26, and survived the reboot that
      evening (see §"Reboot test after disabling netfilter-persistent"). Re-confirmed
      2026-10-27: `systemctl is-enabled` = **disabled**, `is-active` = **inactive**. Its
      `iptables-restore` flushed the whole filter table and caused the 2026-10-21 exposure;
      `rules.v4` was dead weight because `pi5connect.sh` installs the MASQUERADE rule itself
      on every WAN change. Hazard removed rather than sequenced around.

- [x] ~~**Review `SOPHIE-IN drop:` logs** over a few days parked at home~~ Reviewed
      2026-10-27 over **23 h** parked at home (16,604 drops since the 2026-10-26 reboot).
      **Nothing legitimate of ours is being dropped inbound**; no inbound exception is
      warranted. Breakdown:

      - **Zero TCP drops from the home LAN**, and **zero hits on Sophie's own service ports**
        (22 / 1883 / 8000 / 9001) from any source. So nothing is making a deliberate
        connection to Sophie and being refused — the one thing this review was for.
      - Home automation at `192.168.2.11` appears only on `5353` (mDNS), `7000` (AirPlay
        discovery) and `1900` (SSDP) — all multicast/broadcast discovery, never a unicast
        connection to a service. It is not trying to reach Sophie; it is announcing itself.
      - The high-count sources are all benign UDP discovery: `.153 -> :55555` is a beacon to
        `255.255.255.255`, `.1 -> :10001` and `.168 -> :10001` are Ubiquiti device
        discovery, `.218 -> :57621` is Spotify Connect, and `:5353` from ~20 hosts is mDNS.
      - 8,307 of the total are IPv6, all to `ff0::/8` multicast — link-local discovery.
      - Only **four** WAN-side drops, and all four are out-of-state *reply* packets
        (`SPT=443` from remote servers, `DPT=` an ephemeral port on Sophie) that arrived
        just after their conntrack flow expired. Not inbound connection attempts.

      Re-run if the mix of devices at home changes; the standing preference is still to make
      any needed connection dial **outward** from Sophie rather than add an inbound rule.
      ```bash
      sudo journalctl -k | grep 'SOPHIE-IN drop' | grep PROTO=TCP | grep 'SRC=192.168.2' \
        | grep -oE 'DST=[0-9.]+.*DPT=[0-9]+' | sort | uniq -c | sort -rn   # expect empty
      ```

- [x] ~~**`buildRP5RaspAP/install_raspap_bridge.sh` still writes the permissive `rules.v4`**~~
      Done 2026-10-26 — see the fuller entry under §"From the HA security review". Verified
      2026-10-27: the only remaining `rules.v4` / `iptables-restore` / `iptables-persistent`
      strings in that script are **four comments** explaining that it no longer does any of
      it. Nothing executable touches netfilter.

## Phase 2 hardening

Defence in depth: each item still protects Sophie if a firewall rule is ever wrong.
Full list and rationale in `plan_firewall.md` §"Phase 2 hardening".

- [x] ~~**Dashboard auth**~~ Done 2026-10-26 — PIN gate with server-side enforcement, see
      `plan_pin_protection.md`. Verified still live 2026-10-27: `/api/auth/status` returns
      `configured: true`, and the privileged endpoints answer `pin_required`.
- [x] ~~**SSH key-only**~~ Done 2026-10-26 — `/etc/ssh/sshd_config.d/10-sophie-hardening.conf`.
      Verified 2026-10-27 from `sshd -T`, which is the effective config rather than the file:
      `passwordauthentication no`, `kbdinteractiveauthentication no`, `permitrootlogin no`.
- [x] ~~**Bind the dashboard (8000) to `10.0.0.1` *and* `127.0.0.1`.**~~ **Decided 2026-10-27:
      leave uvicorn on `0.0.0.0`.** The same deliberate trade the project already made for
      mosquitto's 1883 listener, for the same reasons:
      - The firewall already confines 8000 to the RV LAN (no `eth1` ACCEPT -> default DROP;
        verified on-box), and that firewall now *self-alerts* if it ever reads NOT ARMED
        (§"From the HA security review", the RV_Health item). So the "firewall silently
        dropped" scenario this item guarded against is itself now covered.
      - The clean fix is not a one-liner. `uvicorn.run(host=)` takes a single address, and
        the healthcheck needs `127.0.0.1` while clients need `10.0.0.1`, so it means a
        two-socket `Server.serve(sockets=[...])` refactor of the dashboard entry point.
      - The Docker-networking shortcut (`ports: "10.0.0.1:8000:8000"`) does **not** apply:
        the container is `network_mode: host`, where `ports:` is ignored and there is no
        proxy to bind. And binding a specific host IP coulples startup to `br0` being up --
        bind fails and the process dies if the dashboard starts before `br0`, exactly why
        1883 was left on `0.0.0.0` too.
      Net: marginal defence-in-depth, real startup-fragility and refactor cost. Reopen only
      if 8000 is ever deliberately exposed on the uplink, or as part of the health-hardening
      work if it ever adds a boot-ordering guard that removes the `br0` race.
- [x] ~~**mDNS**: `allow-interfaces=br0` in `/etc/avahi/avahi-daemon.conf`.~~ Done 2026-10-27.
      Set `allow-interfaces=br0` (was the commented `#allow-interfaces=eth0` example) and
      restarted `avahi-daemon`. This was doing real work: avahi's own log showed it had been
      joined on **eth1 and wlan1 (both uplinks)** plus br0, so Sophie was announcing her
      hostname and `192.168.2.197` onto the home/campground LAN. After the restart it joins
      **br0 only** (`New relevant interface br0.IPv4/IPv6`, and it *left* eth1/wlan1). The
      5353 socket still binds `0.0.0.0` — that is how avahi works; `allow-interfaces`
      governs which interfaces it answers on, not the bind. `rpi-connectd` also holds 5353
      and is left alone (Pi Connect's own discovery, a separate concern). Original saved to
      the scratchpad; the one-line change is easy to reproduce, so it is not versioned.
- [ ] **Least privilege for the webserver container.** Tracked in full under
      §"webserver container privileges" below — two of four steps are done, and the
      remaining work is the `sophie-hostd` project. Not repeated here.
- [x] ~~**Remote access**: Tailscale or WireGuard.~~ **Dropped 2026-10-27 by owner decision
      — not doing it.** Raspberry Pi Connect already covers remote shell and screen sharing
      (dials out, works through CGNAT, no inbound exception), and on Sophie's own WiFi
      `ssh tblank@10.0.0.1` works directly. A mesh VPN was judged not worth the added moving
      part. Revisit only if a need arises that Pi Connect cannot meet.
- [-] **Updates**: periodic `apt full-upgrade` and container image rebuilds. The
      **security** half is done (see "unattended security upgrades" under the HA review).
      Still open, and deliberately kept manual: a full `apt full-upgrade` (general stable
      point-release updates beyond security) and the container image rebuilds. Both can
      change behaviour, so they stay a deliberate on-a-trip action, not automatic.
- [ ] `raspap` compose profile (inactive) sets `RASPAP_COUNTRY=GB`; set `US` if ever
      enabled (regulatory domain, `plan_new_WAN_WiFi.md` issue 8).

## Consider

- [x] ~~**`net.ipv4.conf.all.arp_ignore=1` + `arp_announce=2`.**~~ Done 2026-10-23.
      Sophie has two uplink NICs on the same `192.168.2.0/24` at home (eth1 and wlan1), and
      with the defaults she answered ARP for either address on either NIC. That is ARP flux:
      peers cache whichever MAC replied first, traffic for the Alfa's address can arrive on
      the Realtek, and per-interface testing becomes impossible (it is why the first
      2026-10-23 scan never touched `wlan1`). Second motive: `pi5connect`'s `probe_iface()`
      binds with `SO_BINDTODEVICE`, which filters *inbound* packets by arrival device too, so
      a reply landing on the wrong NIC is discarded and a healthy uplink can be rejected as
      dead — reasoned from the mechanism, not yet measured.
      Applied live 15:48, persisted and loaded 15:54:
      `raspap/90-arp-multihome.conf` → `/etc/sysctl.d/90-arp-multihome.conf`, `sysctl --system`.
      Per-interface values stay 0; effective is `max(all, iface)`, so nothing overrides `all`.
      Verified after loading: both uplinks reach the gateway, internet up, a `br0` client
      answers, firewall `== ARMED`, `ip_forward` still 1.
      **Not yet proven across a reboot or a USB-uplink switch** — see
      §"Check at the next reboot" at the top of this file.

## Internet page redesign (2026-10-26) — what is still open

Done and verified: the Options selector, `POST /api/internet/select` (socket + mains in one
call), watts instead of mA, accessories card removed, the WiFi bridge card folded into one
line, Sophie filtered out, and the manual-choice override that stops a deliberate uplink
choice being reverted. See commits `7159cca` (rv) and `b1bf0ac` (WifitoHostBridge).

- [ ] **The Starlink path of the selector is UNTESTED.** Cellular was tested end to end on
      2026-10-26 and passed (held 180s, no outage, restored cleanly). Starlink was not:
      testing it means dropping the uplink again, and in the garage the dish cannot get a
      route anyway. What is unverified is specifically that selecting it switches Kasa
      outlet 6 on and powers socket 4 — the code path is shared with cellular, which is
      evidence but not proof. Do it on a trip.
- [ ] **The amplifier costs 16.9 W**, measured 2026-10-26 at the Kasa outlet, against ~1 W
      for the modem itself. Cellular + amp is therefore ~18 W all-in, roughly 430 Wh/day or
      36 Ah at 12 V. Worth a line in the UI, or at least worth knowing before leaving it on
      while boondocking.
- [ ] **The WiFi list is thin after a long idle gap** — 3 networks at 330s and 420s idle
      versus 13 when warm. That is the kernel ageing its scan out, not the old bug (which
      gave exactly 1, the network already joined). The strong neighbours are always
      present. Could be improved by lowering the thin-scan retry threshold above 1, but
      the retry costs 6s per attempt on the page load, so it is a trade rather than a fix.
- [x] **The alarm now has a healthcheck** (2026-10-26). It was the only container without one,
      because it publishes only on change and a freshness check would have failed while it
      was working — restarting the alarm in a loop now that autoheal is wired up. It now
      publishes `rv/alarm/heartbeat` every 30s from **inside its main loop**
      (`HEARTBEAT_INTERVAL` in `alarm/alarm.py`), not from a timer thread: a thread would keep
      beating while the loop was wedged on GPIO, which is the failure being detected. The
      payload carries `loop_count` so progress is visible, and the heartbeat is deliberately
      not retained — a retained one would look fresh forever after the process died.

      Verified: two consecutive beats advanced `loop_count` by exactly 100 over 30s, matching
      the 0.3s `LOOPDELAY`; the healthcheck returns 0 on the real topic, 1 on a dead topic and
      0 on bad credentials; Docker reports `healthy`; and the alarm came back disarmed as it
      went in. **All 8 containers now have a healthcheck and the autoheal label.**
- [x] ~~`webserver/client/src/page-debug/debug.jsx:612` still prints raw `bMaxPower` in mA
      in its socket list.~~ **Confirmed and fixed 2026-10-27: watts, with the mA kept in
      parentheses.** A socket line now reads e.g. `ASUS USB-BT500 — up to 2.5 W (500mA)`.
      Both readings, because the two arguments were both right: watts is the owner's rule,
      and the raw sysfs figure is what `lsusb -v` and the journal print, so it is what you
      compare against on a *diagnostic* page.

      The part worth noting is that the conversion was duplicated, not missing: it already
      existed as `maxWatts` inside `page-internet/Internet.jsx`. Adding a second copy to the
      debug page would have left "show all power in watts" with two implementations to keep
      in step. It now lives in `webserver/client/src/utils/power.js` as `maxWatts` plus a
      `maxWattsDetailed` wrapper for the diagnostic page, and `Internet.jsx` imports it
      instead of defining it.

      Still rendered as "up to", because `bMaxPower` is a declared ceiling, not a
      measurement — socket 3 drew ~1 W against a 500 mA (2.5 W) declaration. Checked against
      the live `/api/sockets` values: `100mA` -> `up to 0.5 W`, `500mA` -> `up to 2.5 W`, and
      an absent device yields an empty string rather than `up to 0.0 W`. `eslint` clean; the
      one warning left in `debug.jsx` is a pre-existing `controlSynology` dependency notice,
      untouched.

      **Deployed 2026-10-27.** `docker compose build webserver` then `up -d webserver` --
      the client build is baked into the image, not bind-mounted, so a rebuild is the only
      way this reaches the page. Confirmed the new bundle is the one being served: the page
      references `main.f080ac30.js`, the exact hash the build produced, and that bundle
      contains the `up to ... W` helper. Container `healthy`, 9/9 containers up, and the
      firewall came back intact after the restart (`-A INPUT -j SOPHIE-IN` at position 1,
      DNS and MASQUERADE counts still 2 and 1).

      The two dashboard endpoints that would show it (`/api/hub/sockets`,
      `/api/debug/firewall/status`) answer `pin_required`, as designed, so the rendered
      values were checked against the host API on `127.0.0.1:12347` instead -- the render is
      a pure function of `max_power`, and those were the real values it was tested on.
- [x] ~~`MANUAL_GRACE` is 120s in **three** places (`pi5connect.sh`, `wan_scan.sh`,
      and implicitly the modem timings they are derived from).~~ **Fixed 2026-10-27.** The
      third place was the real problem: nothing anywhere said that 120 *was*
      `IFACE_WAIT + CARRIER_WAIT + DHCP_WAIT` (35 + 10 + 75), so editing a modem timeout
      silently invalidated a constant in a different file. Shorten a wait and the grace is
      too long; lengthen one and the scan stops honouring a deliberate uplink choice while
      that uplink is still legitimately coming up — the exact bug the manual choice was
      added to fix, reintroduced by changing an unrelated-looking number.

      - **New `raspap/wan-common.sh`**, sourced by both scripts: one definition of
        `WAN_PREFERENCE`, `MANUAL_FILE`, `MANUAL_FALLBACK`, `SOCKET_MAP` and the modem
        timings, with `MANUAL_GRACE` **computed** as `WAN_COLD_START` rather than restated.
        Change a timeout and the grace follows. The value is unchanged at 120.
      - **Sourced defensively**, matching the `[[ -x "$WAN_SCAN" ]]` style already in
        `pi5connect.sh`: if the file is missing, each script logs a WARNING and falls back to
        an inline mirror. `pi5connect.sh` runs from a NetworkManager dispatcher, so dying
        because a constants file is absent would leave the RV with no uplink — much worse
        than a stale constant. It also means the three files can be deployed in any order.
      - **New `raspap/check_wan_constants.sh`** is the enforcement the item asked for. It
        asserts the derivation holds and that both inline mirrors still agree with
        `wan-common.sh`, and it reads the mirrors by *executing* them in a clean `env -i`
        shell rather than grepping, so it exercises the real fallback path instead of a
        reading of it.

      Verified rather than assumed, because a check that cannot fail is worth nothing. Five
      deliberately drifted copies, each one caught: a shortened `DHCP_WAIT` with the grace
      left alone; a drifted fallback in `pi5connect.sh`; a reordered `WAN_PREFERENCE` in
      `wan_scan.sh`'s fallback; the derivation replaced by a non-matching literal; and an
      untouched control, which passes. Both constants blocks were then run with the shared
      file present *and* deliberately absent, giving identical values on both paths
      (`grace=120 waits=35/10/75 pref=(wired wifi starlink cellular)`), the WARNING only on
      the fallback path, and the pre-existing environment override preserved —
      `MANUAL_GRACE=99` still wins, as `${MANUAL_GRACE:-120}` did before.

      - [x] ~~**Not deployed.**~~ **Installed 2026-10-27** into `/usr/local/sbin`:
            `wan-common.sh` 0644, `pi5connect.sh`, `wan_scan.sh` and
            `check_wan_constants.sh` 0755, all root-owned and all `diff` identical to the
            repo. The previous `pi5connect.sh`/`wan_scan.sh` were copied aside first, since
            this is the uplink path.

            `check_wan_constants.sh /usr/local/sbin` passes against the installed copies,
            not just the repo ones. Then both scripts were run for real as root:

            - `wan_scan.sh --dry-run`: `current WAN eth1 role=wired rank=0`, correctly found
              nothing better, `no change`.
            - `pi5connect.sh eth1 up` -- the live dispatcher path, re-committing the current
              WAN: probe OK on ICMP first try, route set, rules added, `complete v2.4`.

            **No `WARNING` line in either log, which is the point of the check**: the
            fallback mirror logs one, so its absence is positive evidence that
            `wan-common.sh` was found and sourced rather than silently mirrored. Afterwards
            the uplink is still `eth1` with the internet reachable, the firewall reads
            `== ARMED` with `-A INPUT -j SOPHIE-IN` at position 1 in both families, and the
            rule counts are unmoved at 2 DNS / 1 MASQUERADE / 2 per-WAN FORWARD.

## webserver container privileges (2026-10-27) -- two of four steps done

The webserver has **three independent routes to host root**, and that framing matters: each is
sufficient alone, so removing one changes nothing while the others stand.

1. `privileged: true` + `pid: host` -- PID 1 is host systemd, so `nsenter -t 1 -m -n` yields the
   host's mount and network namespaces. `server.py` does this in 24 places. Also exposes
   `/proc/<pid>/environ` for every host process, so any secret passed as an env var anywhere on
   the box is readable.
2. `/var/run/docker.sock` -- the Docker API is root-equivalent by design.
   `docker run --privileged -v /:/host` needs no exploit.
3. `/dev:/host-dev:rw` -- a live writable devtmpfs. `/host-dev/mmcblk0` is the SD card as a
   block device, so writing it rewrites the root filesystem, bypassing permissions entirely.

Consequence: any code-execution bug in the dashboard is root on Sophie, not container root. The
PIN gate narrowed who can deliberately invoke the dangerous endpoints; it does nothing for a bug
in a read path, since reads are open by design.

**Done 2026-10-27:**

- [x] **Removed `/dev:/host-dev:rw`** -- route 3 closed. It was unused: grepping the whole repo,
      "host-dev" appeared only in `docker-compose.yml`, on the mount line and in one comment
      referring to it. The original reason (a hotplugged device is only visible through a live
      devtmpfs bind) had lapsed, because the jobs needing hotplugged devices were already
      delegated to host daemons -- `usbhub-api` owns hub power, `wifi-api-rp5` owns the Alfa,
      and the modem goes through `/sys/bus/usb`.
- [x] **Removed `cap_add`** (`NET_ADMIN`, `NET_RAW`, `NET_BROADCAST`, `SYS_ADMIN`,
      `DAC_OVERRIDE`). It had no effect -- `privileged: true` already grants every capability --
      and was worse than harmless: it read like a considered minimal set, so if `privileged`
      were ever dropped that list would silently become the real grant with nobody having
      checked it is minimal. `SYS_ADMIN` alone is close to root. When `privileged` comes off,
      establish the capabilities empirically instead.

Verified after both: container healthy, `/host-dev` absent, `nsenter` still reaches the host
(iptables read, host file read), the Docker socket still lists 9 containers, `/sys/bus/usb` is
still writable for the modem rebind, all six dashboard endpoints 200, the health reporter still
publishing, 9/9 containers up, alarm state unchanged.

**Remaining, and this is a project rather than a tidy-up:**

- [x] ~~**A `sophie-hostd` on `127.0.0.1`**~~ **DONE 2026-10-28 — the webserver is
      de-privileged.** Drove the cutover live (user on Pi Connect): step 3 dual-path deployed,
      step 4 dropped `privileged`/`pid: host`/`docker.sock`, and it survived a reboot. Verified
      cold: `docker inspect` shows `Privileged=false`, `PidMode=""`, no docker.sock mount
      (only `/sys/devices:ro` remains); `RVC/RV_Health` publishes `firewall_armed=1 Status=OK`
      after boot, which only works if the webserver reads the firewall through sophie-hostd —
      so the daemon comes up before the webserver needs it. 9/9 containers healthy, firewall
      ARMED. The fallback path was also proven (dashboard stayed up with hostd stopped while
      still privileged). A dashboard bug is now container-confined, not host root.
      Dead-code cleanup (removing the `[hostd-fallback]` branches from `server.py`) was left as
      an optional later commit — the dual-path is the stable end state.
- [x] ~~**Step 1: hand the modem's `/sys/bus/usb` bind/unbind to a host daemon.**~~ **Done
      2026-10-28.** Put it in **`sophie-hostd`** rather than `usbhub-api` (deviation from the
      original note): the general host-root broker is the right home for "kill some host
      processes + rebind a USB device", and it keeps `usbhub-api` focused on hub power. New
      constrained `POST /api/modem/prepare` (only rebinds a device whose idVendor is a known
      cellular vendor, only kills the fixed MTP process names); `usb_modem_manager` calls it
      and its three privileged methods (`find_modem_usb_path`, `kill_mtp_processes`,
      `usb_rescan`) are deleted. **`/sys/bus/usb:rw` removed from the webserver.** With that,
      **the webserver has NO privileged path left** — `docker inspect` shows `Privileged=false`,
      `PidMode=""`, mounts are only `/dev/bus/usb` + read-only `/sys` binds. Verified: the
      "cellular test" path runs through hostd from the de-privileged container (returns "no
      modem found" cleanly, no modem on the bus to rebind).
- [x] **Step 2: delete the dead `[hostd-fallback]` code from `server.py`.** Done 2026-10-28.
      Every `_*_legacy` function and `except HostdUnavailable -> legacy()` branch removed; each
      wrapper now returns a clean error when hostd is unreachable instead of touching the host.
      `_flush_journal_to_disk`/`_nsenter_cmd` removed (orphaned). Audited: zero
      `nsenter`/`docker.sock`/`docker_sdk` references remain. Graceful degradation verified by
      stopping hostd — firewall reports unreachable, auth returns None, reboot returns a shell
      hint, dashboard stays up, no crashes.

### Plan: `sophie-hostd`

**Goal.** Drop `privileged: true`, `pid: host` and the `/var/run/docker.sock` mount from the
webserver, so a dashboard bug is container-confined instead of host-root. The webserver keeps
`network_mode: host` (that is **not** a root route — it shares the net namespace, not root or
pid; it is also what lets the webserver reach the host loopback daemons) and its GPIO device.
Every operation that today needs host root moves behind a small root daemon on loopback, the
exact pattern already proven by `usbhub-api` and `wifi-api-rp5`.

**Why a new daemon and not sudoers rules.** The operations are structured (JSON in/out,
allow-listed container names, bounded `systemctl` units), not single fixed commands. `usbhub_api.py`
already has the allow-list guard and the stdlib-only, loopback-only, root-systemd-unit shape to
copy. A pile of `tee`/`systemctl` sudoers entries would be broader and harder to audit.

**Full privileged surface, inventoried from `server.py` 2026-10-27** — the earlier shortlist
missed three, and a miss means `privileged` cannot actually come off:

| hostd endpoint | replaces in server.py | host action |
|---|---|---|
| `GET /firewall-status` | L2769 `nsenter … iptables/ip6tables -S` | read both chains (net ns) |
| `GET /container-states` | L2904 / L3318 docker SDK | `docker ps` + per-container State |
| `POST /containers/restart` | L3344 `c.restart()` | restart unhealthy/labeled |
| `POST /container/<name>/restart` | L3366 tirelinc restart | restart one allow-listed name |
| `POST /reboot` | L3216 journal flush + L3259 `systemctl reboot` | flush SD-saver journal, then reboot |
| `GET /dashboard-auth` / `PUT /dashboard-auth` | L342/L360 read+write `AUTH_FILE` | `/etc/rvdashboard/dashboard-auth.json`, mode 0600 |
| `GET /wan-manual` / `PUT /wan-manual` / `DELETE /wan-manual` | L2168/L2178/L2200 tee/rm/cat | `/run/wan-manual-choice`, `/run/wan-manual-fallback` |
| `POST /wan-scan` | L1653 `systemd-run wan-scan-ondemand` | trigger an on-demand scan |
| `GET /wan-scan/status` | L1679 `systemctl is-active` | poll that unit |
| `GET /wan-scan/result` | L1689 `cat /run/wan-scan-result` | read result |
| `GET /health-units` | L2934 `systemctl is-active <HEALTH_UNITS>` | host unit states for RV_Health |

Because `sophie-hostd` runs **on the host**, none of these need `nsenter` — it runs `systemctl`,
`iptables`, the file I/O and `docker` directly. The docker calls become hostd talking to the
socket as root; the webserver no longer mounts it.

**Not moving (verify each still works unprivileged, host-networked):**
- Reads of `/sys/class/net/<iface>` for the Internet page (L1821) — `/sys` is mounted read-only
  in any container; confirm it resolves without `privileged`.
- MQTT/`wifi-api`/`usbhub-api` on `127.0.0.1` — loopback works because the container stays
  host-networked.
- GPIO for the alarm import — a device mapping, not a privilege.

**What this does and does not buy.** It removes the *arbitrary*-root routes: no `docker run
--privileged`, no reading every process's `/proc/*/environ`, no writing the SD card as a block
device. What remains reachable from a compromised webserver is exactly the fixed, auditable list
above — including reboot and restart. So the win is "a bug can do these N specific host things"
instead of "a bug is root." State that honestly; it is a large reduction, not elimination.

**Sequencing — never leave reboot and restart both broken:**
1. **Modem `/sys/bus/usb` → `usbhub-api` first** (the second checkbox above). `usbhub-api` is
   already root and owns USB; add a bind/unbind endpoint with an allow-list, point the modem
   path at it, and drop the `/sys/bus/usb:rw` mount. Independent and low-risk; do it first so
   that mount is gone before the big change.
2. **Build `sophie-hostd`** — **DONE 2026-10-28.** In `rv/sophie-hostd/` (daemon, unit,
   `setup_sophie_hostd.sh`, README); installed to `/usr/local/sbin`, `127.0.0.1:12348`,
   `WatchdogSec=180` with the loopback self-check (verified pinging on its 60 s interval,
   `NRestarts=0`). Every endpoint curl-tested as root: firewall reads reachable and hooked
   (cross-checked against the live chains), the PIN store reads with the right four keys,
   units/containers/wan reads correct, `reboot` `dry_run` flushed the journal without
   rebooting, a `wan-fallback` write/read/delete round-trip (mode 0644) worked, and a real
   `autoheal` restart via the API came back healthy. The one path NOT exercised live is the
   `POST /api/wan-scan` trigger — it can change the WAN, so it was left for the at-RV
   session; its code is a thin `systemd-run` wrapper and the GET state path works. **Nothing
   is wired to it yet — the webserver still runs privileged, so this install is inert.**

   The at-RV cutover (steps 3–6) is driven by **`sophie-hostd/cutover.sh`**, runbook in
   **`sophie-hostd/CUTOVER.md`**: `sudo ./cutover.sh next` per step — it does the work,
   verifies, and stops; step 4 auto-rolls-back if the firewall read breaks after the drop.
   Steps 3 and 5 still need the server.py dual-path / cleanup code committed first (the script
   enforces this via markers `sophie-hostd dual-path` / `sophie-hostd cutover complete`);
   steps 4 and 6 are mechanical.
3. **Dual-path the webserver**: each call tries hostd, and *falls back to the current
   nsenter/docker path* while both privilege and hostd still exist. Deploy, exercise the
   dashboard end to end (reboot and restart especially, on a day you can be at the RV).
4. **Remove `privileged`, `pid: host`, `docker.sock`** from `docker-compose.yml`; recreate the
   container. Now the fallback paths are dead (no nsenter without pid:host) — confirm every
   endpoint still works via hostd, and that `/sys/class/net` reads and loopback APIs still work.
5. **Delete the dead nsenter/docker code** and the fallback branches. Re-test.
6. **Reboot test** — the only way to prove the host daemon is up before the webserver needs it,
   and that reboot/restart work from a cold start.

**Rough size:** ~150–250 lines for the daemon, ~13 webserver call sites touched. Could live as
`plan_sophie_hostd.md` if it grows past this sketch; kept here per the request to plan it in TODO.

## pi5connect lock (2026-10-26) -- fixes both duplicate-rule items

`pi5connect.sh` v2.4 takes an `flock` on `/run/pi5connect.lock` around the whole invocation.
Every rule guard in it is check-then-act (`iptables -C ... || iptables -A ...`), which is not
atomic, and the NetworkManager dispatcher fires several instances for one event -- six log
entries for the 2026-10-26 boot, three inside one second on 2026-10-23.

**The straightforward test was inconclusive and is worth recording as such.** Firing five
concurrent instances of the *unlocked* v2.3 did **not** duplicate anything: counts stayed at
2 DNS / 1 MASQUERADE / 1 FORWARD, same as the locked version. So that A/B proved nothing
either way. The reason is that each instance spends about two seconds probing before it
reaches `ensure_dns_input`, which staggers them enough to usually miss the window -- which is
also why the duplicates accumulate slowly in real life (four rules, not six, after many WAN
changes).

Tested the mechanism in isolation instead, on a throwaway `PI5LOCKTEST` chain, which does
settle it:

| concurrency | check-then-act, unlocked | serialized by flock |
|---|---|---|
| 5 | 4 rules | 1 |
| 10 | 3 rules | 1 |
| 20 | 3 rules | 1 |
| 40 | 8 rules | 1 |

Two behaviours that mattered more than the duplicate count, both verified:

- **The recursive failover child does not deadlock.** `PI5_LOCK_HELD=1` is exported for the
  `"$0" "$cand" up` child so it does not wait for a lock its own parent holds. Measured with
  the lock held externally: child with the flag returned in 3s, child without it waited the
  full 30s. A deadlock here would have hung the one path that matters when there is no WAN.
- **A timeout proceeds rather than exits.** Duplicate rules are cosmetic; skipping the work
  because another instance looked busy could leave the RV with no uplink if that instance is
  wedged. The log line makes the race visible when it happens.

Latency cost is negligible: with a dispatcher storm the first instance still commits the WAN
in ~2s and the rest are redundant no-ops behind it.

- [ ] Watch the rule counts over the next few WAN changes. They were deduped to 2/1/1 on
      2026-10-26; if they stay there through several uplink switches and a reboot, both
      duplicate-rule items below can be closed properly rather than on a mechanism argument.

      **Checkpoint 2026-10-27, and the honest reading is "partly".** Counted live through
      `nsenter -t 1 -m -n iptables`: **2** `br0` DNS INPUT rules, **1** WAN MASQUERADE
      (`-o eth1`, plus the two Docker ones), and exactly **2** per-WAN FORWARD rules, both
      for the current `eth1`, with no `wlan1` or `eth2` leftovers anywhere. So 2/1/1 holds
      a day later. The installed `pi5connect.sh` is v2.4 and `diff`s identical to the repo.

      What this does *not* yet prove: **there has been no WAN change since the lock went in.**
      The installed file is dated 16:37:42 on 2026-10-26 and the last real WAN event in
      `/var/log/pi5connect.log` is 16:39:51 the same day -- i.e. the deliberate concurrency
      tests of that session, not new evidence. The uplink has been `eth1` continuously since.
      Two things in that log are still worth having, though, because they were with the lock
      in force: a genuine **five-instance dispatcher storm** at 16:38:34, all five logging
      "Adding rules for new WAN=eth1" inside the same second, and one real
      `Lock: waited 30s ... proceeding without it (duplicate rules possible)` at 16:39:50.
      Neither produced a duplicate. The DNS item below is closeable on that; the stale-rule
      item is not, because it needs an interface to actually go away.

      One more pass added 2026-10-27 while installing the new scripts: a deliberate
      `pi5connect.sh eth1 up` logged `Adding rules for new WAN=eth1` and the counts stayed
      at 2 / 1 / 2. Still not a WAN *change*, so it does not close the stale-rule item, but
      it is a real rule-rewrite under the lock that added nothing.

## Reboot test after disabling netfilter-persistent (2026-10-26 16:18)

First boot since netfilter-persistent was disabled and `install_raspap_bridge.sh` was stopped
from writing `rules.v4`. **Passed.**

| Check | Before | After |
|---|---|---|
| `sophie-firewall.sh status` | `== ARMED` | `== ARMED` |
| `-A INPUT -j SOPHIE-IN` at position 1, v4 and v6 | yes | yes |
| `FORWARD` policy | DROP | DROP |
| `netfilter-persistent` | disabled but still active from the old boot | **inactive** |
| SSH MAC rules, v4/v6 | 2/2 | 2/2 |
| MASQUERADE rules | 6 | 4 |
| `br0` DNS INPUT rules | 4 | **4** (see the corrected item below) |
| uplink | wired `eth1` | wired `eth1`, internet up |
| containers | 9 running, 7 healthy + labelled | same |
| `RVC/RV_Health/1` | `Status=OK ... all clear` | same, publisher restarted cleanly |
| dashboard PIN | set | survived (`configured: true`) |

Nothing depended on `netfilter-persistent`: the firewall armed without it, NAT came back from
`pi5connect.sh` as designed, and the MASQUERADE duplicates dropped from six to four because
the saved ruleset no longer seeds them.

## WatchdogSec on the host daemons (2026-10-27)

`wifi-api-rp5` and `usbhub-api` now carry `WatchdogSec=180` via drop-ins, and both ping
systemd from their own source (`start_watchdog()`).

The design point: `Restart=always` was already set on both, so it already handled the process
*exiting*. The watchdog's entire added value is catching a **hang** -- so the ping had to prove
the HTTP loop still serves, not merely that a timer thread is alive. A bare timer would keep
pinging straight through a deadlocked `serve_forever()`, i.e. through exactly the failure it
exists to catch. Both therefore issue a real loopback request to their own `/api/health` and
ping only on success. That is not hypothetical for the WiFi bridge, which shells out to nmcli;
a wedged nmcli is the realistic way for it to stop answering while the process stays up.

Interval is `WatchdogSec/3` (60s), so three consecutive failed self-checks are needed before
systemd acts -- one slow nmcli does not restart the service.

Verified by systemd's own record rather than by inference: `WatchdogTimestamp` advanced
12:46:04 -> 12:47:04 for both, exactly the 60s interval, so the pings are genuinely landing.
Both APIs still answer through the dashboard afterwards (`ssid=Decher`, `active=wired`), and
`/api/health` returns 200 on 12346 and 12347.

Caught before deploying: the first version of the WiFi bridge's watchdog referenced
`_wifi_opener`, a name that exists in the webserver's `server.py` but **not** in that file. It
would have raised NameError inside the watchdog thread, so the self-check would always fail,
no ping would ever be sent, and systemd would have restarted the WiFi bridge every 180s --
the exact restart loop this work has been trying to avoid. Each service now builds its own
proxy-free opener.

- [ ] Not done: the same treatment for any future host daemon. `pi5connect.sh` cannot have it
      -- it is a NetworkManager dispatcher script, not a daemon -- and the `sophie-firewall`
      units are oneshots, where `WatchdogSec` is meaningless.

## From the HA security review (relayed 2026-10-26)

Reconciled against this repo the same day. Most of the review was already tracked; these are the
items that were **not**, so they would have been lost. Two had been completed and are marked so.

Already covered elsewhere, not repeated here: `netfilter-persistent` and `install_raspap_bridge.sh`
(below, and `plan_firewall.md`), `.link` files, the `privileged`/`pid: host`/docker-socket webserver,
the `pi5connect` lock and its dead per-WAN FORWARD rules, the cellular v6 outside scan, and the
Starlink scan on first use.

Done 2026-10-26, recorded for completeness:
- [x] **SSH key-only.** `/etc/ssh/sshd_config.d/10-sophie-hardening.conf` sets
      `PasswordAuthentication no`, `KbdInteractiveAuthentication no`, `PermitRootLogin no`. See
      `plan_firewall.md` item 1.
- [x] **Dashboard authentication.** PIN gate with server-side enforcement; see
      `plan_pin_protection.md`.

Not tracked anywhere before this, in the review's own priority order:

- [x] **`install_raspap_bridge.sh` no longer touches netfilter** (2026-10-26). It used to write a
      permissive `/etc/iptables/rules.v4` and `iptables-restore` it immediately, so re-running it on
      the live RV would have flushed `SOPHIE-IN`/`SOPHIE-FWD`, set INPUT and FORWARD back to ACCEPT,
      reopened 22/80/443/53 on **every** interface (undoing the MAC-restricted SSH rule added the
      same day), and re-enabled `netfilter-persistent`. STEP 7 now sets only `net.ipv4.ip_forward`
      via a `/etc/sysctl.d` drop-in -- the old append duplicated the line on every run -- and the
      script no longer installs `iptables-persistent` or enables the unit. NAT belongs to
      `pi5connect.sh` at runtime, the filter policy to `sophie-firewall.sh`.
- [x] ~~**Alert when `sophie-firewall` reads NOT ARMED.**~~ **Already built, and it is the
      "fold into health-hardening" the note asked for.** Done in task C on 2026-10-26
      (commits `b87e27c`, `7200355`); surfaced here 2026-10-27 because this item had been
      tracked separately and was not cross-linked. Verified live, not just in code:

      - The webserver's host-health publisher sends `RVC/RV_Health/1` every 60 s with a
        `firewall_armed` field (`webserver/server/server.py:2966`). Caught live 2026-10-27:
        `{"...","firewall_armed": 1, "Status": "OK", "detail": "all clear"}`.
      - The watcher declares that field's expected bounds as `(1, 1)`
        (`watcher/watcher.py:717`), so **any value other than armed goes through the same
        out-of-range machinery every other fault uses** and is published as a
        `RVC/SYS_ERRORS` entry — no second alert path to maintain, which is exactly the
        "doing it twice" the note wanted to avoid.
      - From there the dashboard `AlertsPanel` shows it and it is on MQTT. On-box only, by
        the owner's deliberate choice in task C (no phone push).

      So the 2026-10-21 failure mode — NOT ARMED behind a green `systemctl status` — now
      raises a visible fault. If a push channel off the RV is ever wanted, that is a new
      decision, not a reopen of this.
- [x] **`br0` can no longer pick up a USB adapter by name** (2026-10-26). Was
      `[Match] Name=eth0` in `raspap-br0-member-eth0.network`, and `br0` is the first ACCEPT
      in `SOPHIE-IN`, so anything landing on that name sat inside the trusted zone and
      bypassed the firewall entirely. Fixed in three places: the bridge-member file now
      matches `MACAddress=2c:cf:67:ab:1b:93`, a new `12-eth-onboard.link` pins that MAC to
      the name `eth0` (matching `10-wlan-ap.link`/`11-wlan-wan.link`), and
      `install_raspap_bridge.sh` writes both — reading the MAC from the live interface rather
      than hardcoding it — so a re-run cannot reintroduce the name match.

      Verified: `udevadm test-builtin net_setup_link` reports
      `ID_NET_LINK_FILE=/etc/systemd/network/12-eth-onboard.link` and `ID_NET_NAME=eth0`;
      after `networkctl reload`, `networkctl status eth0` shows the MAC-matched file in force
      with `br0` members unchanged (`eth0 wlan0`), `br0` still 10.0.0.1, hostapd and dnsmasq
      active and the dashboard answering on `br0`. Safe to apply live because `eth0` has no
      carrier. **The `.link` name pinning only takes effect at the next boot** — `.link`
      files apply at device creation — so re-check `networkctl status eth0` then; the
      security-relevant MAC match is already live either way.
- [x] ~~**Verify `br0` cannot pick up a USB adapter by name.**~~ (done above) Checked 2026-10-26 and the concern is
      real: `/etc/systemd/network/raspap-br0-member-eth0.network` matches `[Match] Name=eth0`, and
      `br0` is the first ACCEPT in `SOPHIE-IN`, so anything landing on that name sits inside the
      trusted zone and bypasses the firewall completely. Likelihood is low -- `eth0` is the SoC NIC
      (`driver macb`, platform path `1f00100000.ethernet`, MAC `2c:cf:67:ab:1b:93`) and enumerates
      before USB -- but the consequence is total bypass and the fix is five lines. Add a `.link`
      pinning that MAC to `eth0`, matching `10-wlan-ap.link`/`11-wlan-wan.link`, and preferably also
      change the bridge-member file to `[Match] MACAddress=` so the name stops mattering at all.
      Note RaspAP owns those files and may rewrite them.
- [x] **Mosquitto 9001 narrowed and taken off the uplink** (2026-10-27) -- rather than given a
      password, and the reasoning matters. A credential for 9001 would have to ship inside the
      React bundle, readable by anyone who can load the dashboard, and `:8000` already serves
      the same telemetry unauthenticated by deliberate decision. So a password there buys
      almost nothing. What did help:

      - **ACL narrowed from `read RVC/#` to `read RVC/SYS_ERRORS`.** Exactly one thing consumes
        this listener -- `AlertsPanel.jsx` -- and it subscribes to that one topic. Measured: an
        anonymous websocket client subscribing to `RVC/#`, `RVC/TANK_STATUS/#` and
        `RVC/BATTERY_STATUS/#` now receives **nothing** from them, while a control on the
        authenticated listener showed **724 messages across 28 topics** in a comparable
        window, 63 of them TANK_STATUS and 30 BATTERY_STATUS. That whole stream used to be
        readable by anyone on Sophie's WiFi.
      - **Bound to `127.0.0.1` and `10.0.0.1` only**, so the anonymous listener is not on the
        uplink at all. Verified: `192.168.2.197:9001` now refuses, `10.0.0.1:9001` works.
        Loopback is included because the dashboard is sometimes reached through an SSH tunnel.

      1883 deliberately left on `0.0.0.0`: it already requires a password, and binding it to
      `br0` would make the broker refuse to start if `br0` were not up yet -- on an unattended
      RV that trades a small exposure for no MQTT at all, meaning no alarm commands and no
      telemetry. Revisit only with a boot-ordering guarantee.
- [x] ~~**Require auth on Mosquitto 9001.**~~ (addressed above; say so if you still want a
      credential on it despite the bundle-readability problem) Measured 2026-10-26: `allow_anonymous true` with
      `acl_file` = `topic read RVC/#`. Read-only and confined to RV-C topics -- it cannot write, and
      cannot reach the alarm command topics -- but it does hand all RV telemetry to anyone on
      Sophie's WiFi. Low severity on its own; matters more while 9001 is still bound to every
      interface.
- [x] ~~**Check RaspAP's web UI (:80) and `wayvnc` (:5900) for default or empty passwords.**~~
      Investigated 2026-10-27. **Neither is empty; VNC is provably not default. One open
      question for the owner on the RaspAP password, which I did not test by guessing.**

      `wayvnc` (:5900) — **done, no action.** `/etc/wayvnc/config` has `enable_auth=true`,
      `enable_pam=true` and TLS (cert + key). There is no VNC password of its own to be
      empty or default: it delegates to PAM, so login is as strong as the `tblank` account
      password. The `vnc` service account is locked (`passwd -S vnc` = `L`), which is
      correct — CLAUDE-rv.md documents login as `tblank`, not `vnc`.

      RaspAP (:80) — **auth is enforced and the password is non-empty.** `/etc/raspap/raspap.auth`
      holds username `admin` and a `$2y$10$` bcrypt hash (so: not empty). Unauthenticated
      requests to `/` and to an ajax endpoint both return `302` to the login page — RaspAP
      does session auth in the PHP app, not via lighttpd `mod_auth` (which is all commented
      out, as shipped). So the UI is not open.

      - [x] ~~**Is the RaspAP admin password still the factory default `secret`?**~~ Owner
            confirmed 2026-10-27 it was deliberately changed from the default. So the one
            open question on this item is answered and the whole item is closed: both ports
            enforce auth, neither is empty, VNC is PAM-backed, and the admin password is
            non-default.

      **The bound on all of this: the firewall confines both ports to the RV LAN.** Verified
      on-box — `SOPHIE-IN` trusts `lo`/`br0`/`docker0`/`br-+` and drops everything else, and
      there is no `eth1`/uplink ACCEPT for 80 or 5900, so both fall through to the default
      DROP on the uplink. On `br0` (10.0.0.1) both answer, so the real residual exposure is
      to **anyone on Sophie's WiFi** — a guest, a phone — bounded only by these two
      passwords. That is exactly the "firewall gives no protection on the RV LAN side"
      caveat the item was raised under, which is why the default-password question matters
      even though the uplink is closed.
- [ ] **Bind the dashboard (8000) to `10.0.0.1` and `127.0.0.1`.** Same item as "Bind the
      dashboard (8000)" under §"Phase 2 hardening"; the 9001 half is already done.
- [x] ~~**Turn on unattended security upgrades.**~~ Done 2026-10-27. `unattended-upgrades`
      installed and enabled (`apt-daily-upgrade.timer` active), configured **security-only**
      and to **never reboot on its own** — the one setting that matters most on an
      unattended RV, since an auto-reboot could strand it with no uplink or mid-task.

      Config is versioned in `sdcard-writes/unattended-upgrades/` (two `apt.conf.d` files
      plus an `install.sh` in the repo's existing host-config style). Three deliberate
      choices, each with a reason in the files:
      - **Security origin only** (`...-security,label=Debian-Security`), and the installer
        also comments out the stock `50unattended-upgrades` main-archive line
        (`label=Debian`) as belt-and-braces, so future general point-release updates are not
        auto-applied — those stay in the manual "Updates" item above.
      - **`Automatic-Reboot "false"`**, plus `--force-confold` so a changed package conffile
        keeps the installed version rather than prompting (nobody is there to answer).
      - **Raspberry Pi firmware repo left out**, so kernel/firmware stays deliberate.

      Applied the backlog immediately while on free wired — **60 pending security updates**,
      every one a `deb12uN` build confirmed present in `bookworm-security` (the box had not
      been patched since the SD image was made): openssl/libssl3 `3.0.22-1~deb12u2`, perl,
      python3.11 `deb12u9`, bind9, nodejs `deb12u3`, php8.2, libmariadb3, imagemagick, and
      more. `All upgrades installed`, **no `reboot-required` flag**, 9/9 containers healthy,
      firewall `== ARMED`, uplink up afterward.

      - [ ] **A reboot would let host services pick up the new openssl/libssl.** Not
            required (no flag set) and not urgent; the next deliberate reboot covers it.
            Containers are unaffected — they carry their own libs in-image.
      - Note the one real tradeoff: if the daily timer fires while Sophie is on **metered
        cellular**, it will download security updates over that link. Security updates are
        usually small; there is no clean "unmetered-only" gate without wiring
        NetworkManager's metered flag into apt, which was judged not worth it. Revisit if a
        bill ever shows it.
- [x] ~~**Review the `SOPHIE-IN drop:` logs over a few days at home.**~~ Done 2026-10-27 —
      same item as under §"Firewall — finish the deployment", where the full 23 h result
      is recorded. Nothing legitimate dropped; home automation at `.11` only ever appears in
      multicast discovery, never a unicast connection to a Sophie service.
- [ ] **A true cold boot** (full power-off, not a reboot). The 2026-10-23 test rebooted with the hub
      still energised, so the modem never paid its ~36 s from a dead socket. Needs someone at the RV.

## Small / unrelated

Worked through 2026-10-27. **All closed except one.** The DNS rule count, the `usbhub`
socket map, the `.196` references, the `sudoers` permissions and the `usbhub_ports.py` drift
are done; the hub-on-USB-2 question found on the way was settled by the owner (it stays).

The one genuinely open item is **stale rules for a dead WAN**, and it is open for a reason
that no amount of session time fixes: it needs an interface to actually go away while the
lock is in force, which means dropping the uplink.

- [x] ~~`chmod 0440 /etc/sudoers.d/debian_frontend /etc/sudoers.d/usb-reset`~~ **Done
      2026-10-27**, after the owner ran `sudo -v` to cache the credential (`chmod` is not
      one of this user's NOPASSWD entries, so it needs the blanket `(ALL : ALL) ALL` rule).
      Both were `0644` where every other file in `/etc/sudoers.d` was `0440`; both are now
      `-r--r----- root root`.

      `visudo -c` went from two `bad permissions, should be mode 0440` lines to **every
      file parsed OK, no warnings**. Checked that the rules still load rather than assuming
      it: `sudo -l` still lists the `tee .../usb/{un,}bind` pair from `usb-reset` and
      `env_keep+=DEBIAN_FRONTEND` from `debian_frontend`.

- [x] ~~`iptables -S INPUT` carries **four** identical `br0` DNS accept rules~~ **Closed
      2026-10-27: the count is two.** One `udp --dport 53` and one `tcp --dport 53`, which
      is exactly what `ensure_dns_input`'s `-C` guard is supposed to leave.

      The root cause identified on 2026-10-26 was right and the fix landed: it was the TOCTOU
      race in `ensure_dns_input`, not `netfilter-persistent` restoring `/etc/iptables/rules.v4`.
      The count went 4 -> 2 at the 2026-10-26 16:18 reboot, which on its own proves only
      that nothing re-seeded them; what makes this closeable is that the v2.4 lock was
      installed at 16:37:42 and the five-instance dispatcher storm at 16:38:34 -- plus one
      lock *timeout* at 16:39:50 that proceeded anyway -- left the count at two, where it
      still is a day later.

      Kept for the record, because it cost two commits to get right: commits `b87e27c` and
      `186ed0c` claimed `rules.v4` explained the four rules, because that file does contain
      four such lines. The 2026-10-26 reboot disproved it -- `netfilter-persistent` was
      `inactive`, nothing restored that file, and the count came back as four anyway, as two
      exact `udp` pairs and two exact `tcp` pairs. The `rules.v4` claim in those two commit
      messages is wrong; the rest of what they say stands.

- [ ] **Stale rules for a dead WAN survive a switch.** After `wlan1` went away on
      2026-10-23, `FORWARD` still held `-i br0 -o wlan1 -j ACCEPT` and its
      `RELATED,ESTABLISHED` partner, and `nat POSTROUTING` still held
      `-o wlan1 -j MASQUERADE` *plus* a duplicated `-o eth2 -j MASQUERADE`. Harmless while
      the interface is absent, and `SOPHIE-FWD` is in front of all of it, but it shows the
      remove-then-add path is not symmetric. Root cause is visible in the log: the
      dispatcher fired **three** `pi5connect` instances concurrently for the same
      `eth2 up`, all three reaching "Adding rules for new WAN" within the same second.
      The `flock` added in `639a285` is the fix.

      **Checked 2026-10-27 and the rules are clean -- but this is NOT evidence yet.** There
      are exactly two per-WAN FORWARD rules and one WAN MASQUERADE rule, all for the live
      `eth1`, and nothing for `wlan1` or `eth2`. The catch is that the last WAN *change* was
      at 16:39 on 2026-10-26, before which the 16:18 reboot had already cleared the table,
      so a clean table today is what a reboot gives you for free. **This item needs an
      interface to genuinely go away while the lock is in force** -- unplug the wired
      adapter, or select cellular from the Internet page -- and then a re-count. Deliberately
      not done from a session: it drops the uplink.

- [x] ~~**`usbhub/README.md`'s observed socket map is stale.**~~ Done 2026-10-27, and it
      turned up a hardware change nobody had recorded. The README documented
      `3-1`/`3-1.3` (USB 2) + `4-1`/`4-1.3` (USB 3) from 2026-10-18; the hub now enumerates
      as `1-2` + `1-2.3` with **no USB 3 chip at all**. `/etc/usbhub/sockets.json` was
      already correct, so only the document was wrong.

      **Why the USB 3 chip is gone: the hub has been moved to a black (USB 2) port.** `1-2`
      hangs off root hub `usb1` at 480 Mb/s, and `usb2` -- the SuperSpeed root hub sharing
      that connector pair -- has nothing attached, so the SuperSpeed upstream link never
      trains and the USB 3 chip never enumerates. Hence one sysfs identity per socket
      instead of two. Nothing is broken: both chips still report `ppps`, `SocketMap` acts on
      whatever identities exist, and `/api/sockets` resolves all seven correctly with the
      right names and the gating on socket 3.

      It also costs nothing as populated, which is worth stating rather than assuming --
      read from `/api/sockets`, **no device on the hub is a SuperSpeed device**: the Alfa is
      `0e8d:7612` (MT7612U, a USB 2.0 part) at 480, the wired uplink is `0bda:8152`, a
      Realtek *10/100* adapter, at 480, and the BT500 is at 12. The SD card reader, which
      *is* SuperSpeed, is in a blue port directly and not on the hub.

      - [x] ~~**Decide whether to move the hub back to a blue port.**~~ **Decided
            2026-10-27 by the owner: it stays on USB 2.0.** Recorded as a choice in
            `usbhub/README.md` and in `CLAUDE.md`'s hardware table, so the next session does
            not read the missing USB 3 chip as a fault and "fix" it.

            The two costs are accepted, not outstanding: a SuperSpeed device on the hub
            would silently fall back to 480 Mb/s, and the "one socket, two identities"
            behaviour -- including the 2026-10-18 finding that the two chips' port power is
            independent rather than ganged -- cannot be re-verified while there is no second
            identity to switch. Two consequences to keep in mind as a result:
            **a SuperSpeed device belongs in a blue Pi port**, which also means it cannot be
            power-gated (fine today -- nothing needing gating needs SuperSpeed); and
            **the two-identity handling in `SocketMap` is not dead code** -- it is correct
            for any USB 3 hub, including this one in a blue port, so it should not be
            simplified away on the evidence of one cabling.

      What changed in the README: the live map replaces the 2026-10-18 one; a new
      "Bus paths are not stable" section carries a dated table of both cablings and the rule
      *read the live name, do not hardcode it*; the mapping command no longer says
      `--hubs 3-1,3-1.3,4-1,4-1.3` but discovers the names, and now also documents
      `--relocate`, which reapplies the stored socket geometry by VID:PID with nothing
      unplugged -- that is how the current map was produced; the automatic cascade
      protection is described by rule rather than by path; and every surviving `3-1`/`4-1`
      reference is now explicitly labelled as a record of a measurement on a date.

      The one hand-written path is called out rather than glossed: `USBHUB_PROTECTED` in
      `usbhub-api.service` is belt-and-braces over the automatic cascade detection, so it
      has to be re-measured when the hub moves. Checked 2026-10-27 -- it reads
      `1-2:4,1-2:3` (socket 7's Bluetooth adapter, and the internal cascade), so somebody
      already updated it for the move; it is correct as cabled.

- [x] ~~**`usbhub_ports.py` on disk has drifted from the repo**~~ **Resolved 2026-10-27 by
      running `setup_usbhub_api.sh`.** All four files (`usbhub_ports.py`, `usbhub_api.py`,
      `map_sockets.py` and the unit) now `diff` identical to the repo; the previous driver
      was kept as `/usr/local/sbin/usbhub_ports.py.prev` by the installer.

      The drift was from commit `c345012` ("Remove dead Coolgear code"), which the Oct 20
      install predated. Comment-only, except that the repo version deletes
      `get_current_active_port()` -- a shim for the old Coolgear-shaped callers. Nothing in
      the repo calls it, confirmed by grep before and `grep -c` on the installed file after:
      0 occurrences, nothing broken. The unit's functional content is unchanged; only its
      `USBHUB_PROTECTED` *comment* was trimmed, and the value is still `1-2:4,1-2:3`.

      The one thing worth verifying rather than trusting was socket power, since this
      restarts the root service that owns it. The installer's header claims "restarting this
      service never changes a port: it only reads state at start-up", and that held: all
      seven sockets came back with identical `enabled`/`device_present`, including socket 3
      still gated off and socket 7's Bluetooth still powered. Service `active`,
      `/api/health` 200, uplink and internet unaffected, 9/9 containers healthy, and the
      alarm still reporting both zones OFF on its heartbeat.

      Also confirmed the automatic cascade protection the README describes, from the
      service's own start-up line: `protected=['1-2:3', '1-2:4'] +auto ['1-2:3', 'usb1:2']`
      -- it found the internal cascade and the hub's own upstream port by itself.

      `WatchdogSec` survived the restart: `WatchdogTimestamp` advanced 15:00:57 -> 15:01:57,
      exactly the 60s interval, with `NRestarts=0`. `wifi-api-rp5` likewise.

      While here, fixed the installer's own stale hint: `setup_usbhub_api.sh` printed
      `map_sockets.py --hubs 3-1,3-1.3,4-1,4-1.3` for the no-map case. It now points at
      `--relocate` for a moved hub, says to read the current hub names rather than copy them
      from a note, and mentions that a USB 2 port gives one identity per socket so one pass
      is all there is.

- [x] ~~README/CLAUDE.md still mention reaching Sophie over SSH at `192.168.2.196`.~~ Done
      2026-10-27 -- **and the item's own premise was wrong.** Neither `README.md` nor
      `CLAUDE.md` ever mentioned that address; `README.md` is only the MQTT topic table and
      `CLAUDE.md`'s Remote Desktop section already said VNC and Pi Connect. The two real
      users were `plan_rv_improvements.md`, which called it "the bench Pi", and the `ssh -t`
      example in `sdcard-writes/setup-passwordless-sudo.sh`. Both now point at
      `ssh tblank@10.0.0.1` over Sophie's own WiFi, with a line on what the home LAN can
      still do: SSH in from the home side now works only from the laptop, via the two
      `--mac-source` ACCEPT rules in `SOPHIE-IN` (`28:d0:ea:d4:f7:47` and
      `08:3a:88:55:27:80`, both confirmed present 2026-10-27).

      Also fixed one that was not on any list: `~/dotfiles/claude/CLAUDE-rv.md` said
      "No VPN configured; access via SSH on local network", which has been false since the
      firewall went in and is exactly the sort of line that sends a session down a dead end.
      It now names the default-deny uplink, `10.0.0.1` on `br0`, and Pi Connect.

      Confirmed still current 2026-10-27: `eth1` is `192.168.2.197`, `wlan1` is
      `192.168.2.107`. The remaining `.196` strings in the repo are deliberate -- the
      correction note in `plan_firewall.md` and the history lines here.
