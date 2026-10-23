# TODO — Sophie (RV1-PI5)

Open work, most urgent first. Opened 2026-10-23 out of the firewall deployment
(`plan_firewall.md`, `firewall/README.md`).

## Firewall — finish the deployment

- [ ] **Reboot and confirm `ARMED`.** The live rules were applied by hand on 2026-10-21;
      `uptime -s` is still that same boot, so the `After=netfilter-persistent.service`
      ordering fix has never run on the boot path. Until this passes, a reboot could
      silently leave Sophie exposed exactly as it did on 2026-10-21.
      ```bash
      sudo reboot
      # after it comes back:
      sudo sophie-firewall.sh status | tail -1      # expect: == ARMED
      ```
      Or just open the dashboard's Debug page — the Host Firewall card says `Armed` or
      `EXPOSED`. Specifically confirm `-A INPUT -j SOPHIE-IN` at **position 1** for both
      families; that is the rule that went missing the first time.

- [ ] **Outside `nmap`**, from a laptop on the home WiFi (not on Sophie's AP). The only
      check that cannot be done from on-box, and the last item in the plan's rollout.
      ```bash
      nmap -Pn -p- 192.168.2.197        # eth1, active uplink
      nmap -Pn -p- 192.168.2.107        # wlan1, the Alfa
      nmap -6 -Pn -p 22,80,1883,5900,8000,9001 <eth1 fd69:… address>
      ```
      Expect every port filtered. Repeat per uplink type on first use (Starlink,
      cellular) — table in `plan_firewall.md` §"Verification per uplink".

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
