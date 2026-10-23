# TODO — Sophie (RV1-PI5)

Open work, most urgent first. Opened 2026-10-23 out of the firewall deployment
(`plan_firewall.md`, `firewall/README.md`).

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
      Caveat: `wlan1` was scanned by address but not exercised as an interface — every
      logged packet arrived `IN=eth1`, because both uplinks share `192.168.2.0/24` and
      `arp_ignore=0` lets either NIC answer for either address. Harmless (nothing in
      `INPUT` mentions `wlan1`, and `SOPHIE-IN` ends in DROP), but unobserved.
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

- [ ] **`net.ipv4.conf.all.arp_ignore=1` + `arp_announce=2`.** Sophie has two uplink NICs on
      the same `192.168.2.0/24` at home (eth1 and wlan1), and with the defaults she answers
      ARP for either address on either NIC. That is ARP flux: peers cache whichever MAC
      replied first, traffic for the Alfa's address can arrive on the Realtek, and
      per-interface testing becomes impossible (it is why the 2026-10-23 scan never touched
      `wlan1`). These two sysctls are the standard fix. Check the interaction with
      `pi5connect.sh`'s WAN selection and the nightly cheaper-WAN scan before enabling, and
      prefer `/etc/sysctl.d/` over a live `sysctl -w` so it survives a reboot.

## Small / unrelated

- [ ] `chmod 0440 /etc/sudoers.d/debian_frontend /etc/sudoers.d/usb-reset` — `visudo -c`
      flags both as bad permissions. Pre-existing, they load today, but it is the kind of
      thing that stops working after a sudo upgrade.
- [ ] `iptables -S INPUT` carries **four** identical `br0` DNS accept rules where
      `pi5connect.sh`'s `-C` guard should have produced two
      (`raspap/pi5connect.sh:218-221`). Harmless, but if the count grows with each WAN
      change the guard isn't matching and the list leaks. Worth re-counting after a few
      uplink switches.
- [ ] README/CLAUDE.md still mention reaching Sophie over SSH at `192.168.2.196`. That
      path is now firewalled off by design — update the instructions to Pi Connect or
      Sophie's own WiFi (`plan_firewall.md` §"Things that will break", item 1).
