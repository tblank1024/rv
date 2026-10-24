# TODO — Sophie (RV1-PI5)

Open work, most urgent first. Opened 2026-10-23 out of the firewall deployment
(`plan_firewall.md`, `firewall/README.md`).

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

- [ ] **Pin the USB-ethernet adapters by MAC** with `.link` files, the way
      `11-wlan-wan.link` pins the Alfa. `usbhub/README.md` already recommends it. The
      modem is `d0:0e:8d:0f:3b:c7` (`cdc_ether`). Policy does not need it, but every
      *document*, log grep and debugging session does -- `eth1` meaning "wired" in one
      boot and "cellular" in the next is a trap for humans even when the code is immune.
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

- [ ] **Disable `netfilter-persistent`.** `systemctl disable netfilter-persistent`. Its
      `iptables-restore` flushes the whole filter table and was the cause of the
      2026-10-21 exposure. The ordering fix makes it survivable, but `rules.v4` is dead
      weight — `pi5connect.sh` installs the MASQUERADE rule itself on every WAN change.
      Removes the hazard instead of sequencing around it.

- [ ] **Review `SOPHIE-IN drop:` logs** over a few days parked at home, for anything of
      ours trying to reach Sophie inbound — home automation at `192.168.2.11` especially
      (`plan_firewall.md` §"Things that will break", item 2). First 25 minutes showed only
      discovery broadcasts and mDNS multicast, nothing legitimate. Prefer making the
      connection dial outward from Sophie over adding an inbound exception.
      ```bash
      sudo journalctl -k | grep 'SOPHIE-IN drop' | sed -E 's/.*drop: //' | sort | uniq -c | sort -rn
      ```

- [ ] **`buildRP5RaspAP/install_raspap_bridge.sh` still writes the permissive `rules.v4`**
      (`INPUT ACCEPT`, `FORWARD ACCEPT`, all-ACCEPT rules). A rebuild from that script
      recreates the problem the firewall exists to fix. Make it emit a NAT-only file, or
      nothing at all.

## Phase 2 hardening

Defence in depth: each item still protects Sophie if a firewall rule is ever wrong.
Full list and rationale in `plan_firewall.md` §"Phase 2 hardening".

- [ ] **Dashboard auth** — do this one first. `:8000` has no authentication at all, and
      its endpoints can reboot the Pi, restart containers and cut USB hub power. Anyone on
      Sophie's WiFi (a guest, a phone) can call them today. At minimum gate the
      destructive routes.
- [ ] **Bind LAN-only services to the LAN address**: uvicorn `0.0.0.0` → `10.0.0.1`
      (`webserver/server/server.py`, check nothing on Sophie uses `localhost:8000` first —
      the compose healthcheck does), and mosquitto's `listener 9001` → `10.0.0.1`
      (`docker/mqtt/config/mosquitto.conf`). The 1883 listener needs localhost for the
      host-network containers.
- [ ] **SSH key-only**: `PasswordAuthentication no` in `/etc/ssh/sshd_config.d/`. Confirm
      key login works first.
- [ ] **mDNS**: `allow-interfaces=br0` in `/etc/avahi/avahi-daemon.conf`.
- [ ] **Least privilege for the webserver container**: `privileged`, `pid: host` and the
      Docker socket, already flagged in `docker-compose.yml` as Phase 4. Note the firewall
      status endpoint reads the host chains through `nsenter -t 1`, so it depends on
      `pid: host` + privileged; trimming those needs a different route (a small host-side
      API like `usbhub-api.service`, or `iptables` in the image).
- [ ] **Remote access**: Tailscale or WireGuard — dials out, works through CGNAT, needs no
      inbound exception. This is the replacement for the old `192.168.2.196` SSH habit.
- [ ] **Updates**: periodic `apt full-upgrade` and container image rebuilds.
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

## Small / unrelated

- [ ] `chmod 0440 /etc/sudoers.d/debian_frontend /etc/sudoers.d/usb-reset` — `visudo -c`
      flags both as bad permissions. Pre-existing, they load today, but it is the kind of
      thing that stops working after a sudo upgrade.
- [ ] `iptables -S INPUT` carries **four** identical `br0` DNS accept rules where
      `pi5connect.sh`'s `-C` guard should have produced two
      (`raspap/pi5connect.sh:218-221`). Harmless. Re-counted after the stage-2 cellular
      switch on 2026-10-23: **still four, not six** -- so the `-C` guard does hold across a
      WAN change and the list is not leaking per switch. The duplicate pair comes from
      somewhere else, most likely a race at boot. Lower priority than it looked.

- [ ] **Stale rules for a dead WAN survive a switch.** After `wlan1` went away on
      2026-10-23, `FORWARD` still held `-i br0 -o wlan1 -j ACCEPT` and its
      `RELATED,ESTABLISHED` partner, and `nat POSTROUTING` still held
      `-o wlan1 -j MASQUERADE` *plus* a duplicated `-o eth2 -j MASQUERADE`. Harmless while
      the interface is absent, and `SOPHIE-FWD` is in front of all of it, but it shows the
      remove-then-add path is not symmetric. Root cause is visible in the log: the
      dispatcher fired **three** `pi5connect` instances concurrently for the same
      `eth2 up`, all three reaching "Adding rules for new WAN" within the same second.
      A lock around the rule rewrite, like the one `f5cc58a` added for socket power, is
      the obvious fix.

- [ ] **`usbhub/README.md`'s observed socket map is stale.** It records
      `3-1`/`3-1.3`/`4-1`/`4-1.3` from 2026-10-18; after the 2026-10-23 boot the hub
      enumerates as `1-2.3`, with **one** identity per socket rather than two. The API
      still resolves sockets correctly, so nothing is broken, but the README now documents
      a bus path that no longer exists -- and the "one socket, two sysfs identities"
      reasoning needs a line saying the paths themselves are not stable across boots.
      Re-run `map_sockets.py` and update the measured map.
- [ ] README/CLAUDE.md still mention reaching Sophie over SSH at `192.168.2.196`. That
      path is now firewalled off by design — update the instructions to Pi Connect or
      Sophie's own WiFi (`plan_firewall.md` §"Things that will break", item 1).
