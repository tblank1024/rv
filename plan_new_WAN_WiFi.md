# plan_new_WAN_WiFi.md — USB WiFi adapter as a WAN uplink (replacing the Zero 2W bridge)

STATUS: proposal, nothing purchased or deployed (2026-10-09).

## Goal

Replace the Pi Zero 2W WiFi bridge (uplink option 3, "RP2", on the CoolGear USB hub) with a dual-band 2x2 USB WiFi
adapter plugged into the same hub port, with external antennas mounted outside the RV. Sophie (RP5) joins the
campground WiFi directly as `wlan1`; RaspAP keeps serving the RV on the onboard `wlan0`.

Why: the Zero 2W is 1x1, 2.4 GHz only, PCB antenna inside the RV skin (~15–25 Mbps TCP best case), and its
traffic adds a USB-gadget hop and a second NAT. See `WiFitoHostBridge/plan-speed.md` for the throughput tests;
run those first to confirm the uplink (and not the RaspAP config) is the bottleneck.

```
Before: Roku -- wlan0/br0 [RP5] -- USB hub port -- [Zero 2W] ~~2.4 GHz~~ campground AP
After:  Roku -- wlan0/br0 [RP5] -- USB hub port -- [Alfa adapter, outside] ~~2.4/5 GHz~~ campground AP
```

## Adapter choice

Both: MediaTek chipset, in-kernel Linux driver (no DKMS), 2x2 MIMO, 2.4 + 5 GHz, detachable RP-SMA antennas.

| | AWUS036ACM | AWUS036AXML |
|---|---|---|
| Chipset / driver | MT7612U / `mt76x2u` (in-kernel since ~4.19) | MT7921AUN / `mt7921u` (in-kernel since 5.18) |
| Standard | WiFi 5 (802.11ac) | WiFi 6E (802.11ax), adds 6 GHz |
| Max PHY (2x2, 80 MHz, 5 GHz) | 867 Mbps | ~1200 Mbps |
| Price | lower | ~$20–30 more |

**AWUS036ACM — pros**
- Most mature, widely used Linux driver; lots of field reports on Raspberry Pi.
- Cheaper.

**AWUS036ACM — cons**
- WiFi 5 only: no OFDMA/BSS coloring, which help on crowded shared channels with newer APs.
- Older design; less future headroom as campgrounds upgrade.

**AWUS036AXML — pros**
- WiFi 6: OFDMA and BSS coloring help in dense campgrounds *if the park AP is 802.11ax*.
- 6 GHz capable (future-proofing only; campgrounds rarely offer it).
- Current chipset, longer support life.

**AWUS036AXML — cons**
- Newer driver (fine on Pi OS Bookworm 6.x kernels, but less field history than mt76x2u).
- Needs MediaTek firmware blobs (`firmware-misc-nonfree`) present.
- Slightly more expensive.

**Same for both:** peak rates are irrelevant here; USB 2.0 (~250–300 Mbps real) and the campground link/backhaul
will limit first. Against older 802.11n/ac park APs they perform about the same. Both draw several hundred mA
while transmitting.

**Recommendation:** AWUS036AXML. Mounting (outside, high, short coax) matters more than the choice of adapter.

## Antenna and mounting

1. **Get out of the RV skin.** Aluminum skin and tinted glass cost ~10–20 dB, more than any antenna gain.
2. **Keep coax short, run USB long.** At 5 GHz, RG-58 ≈ 0.25 dB/ft, LMR-195 ≈ 0.18 dB/ft. Put the adapter at the
   antenna (weatherproof box) with short pigtails and run an active USB 2.0 extension back to the hub.
3. **Start with the stock dipoles** (omni, 2x2). Add a dual-band **dual-polarized** 2x2 panel (~10–14 dBi,
   30–60° beamwidth) only if typical sites are weak/interference-limited. Dual-pol gives two streams on
   line-of-sight paths; re-aim at each site.
4. FCC: 2.4 GHz point-to-multipoint EIRP limit 36 dBm. ~20 dBm conducted + 14 dBi is at the limit; reduce TX power
   for higher-gain antennas.
5. Physical separation from Sophie's AP antenna reduces desense when both are on 2.4 GHz.

## Integration issues with RaspAP / Sophie, and the approach

### 1. Interface naming (must fix)
hostapd (`interface=wlan0`), `raspap-br0-member-wlan0.network`, `pi5connect.sh`, and `99-pi5connect` all identify
the AP radio by the name `wlan0`. With a second WiFi device, enumeration order can swap at boot (AP starts on the
Alfa). After re-plugging (hub port toggle), the adapter could also come back as `wlan2`.
Also check whether Pi OS names it `wlan1` or `wlx<mac>`.

Approach: pin both names by MAC with systemd `.link` files (applied by udev on every hotplug):
```
# /etc/systemd/network/10-wlan-ap.link
[Match]
MACAddress=<onboard wlan0 MAC>
[Link]
Name=wlan0

# /etc/systemd/network/11-wlan-wan.link
[Match]
MACAddress=<Alfa MAC>
[Link]
Name=wlan1
```
Then `sudo update-initramfs -u` (if names are applied in initramfs), reboot, and verify with `ip link`.

### 2. Which network manager owns which interface (must fix)
Sophie has traces of NetworkManager, systemd-networkd (`raspap/*.network`), and dhcpcd
(`buildRP5RaspAP/install_raspap_bridge.sh`). Exactly one must own `wlan1`.

Approach:
- NetworkManager owns `wlan1` (the join logic already uses `nmcli`).
- `wlan0` is unmanaged by NM (hostapd owns it): `/etc/NetworkManager/conf.d/99-unmanaged-wlan0.conf`:
  ```
  [keyfile]
  unmanaged-devices=interface-name:wlan0
  ```
- Confirm no systemd-networkd `.network` file matches `wlan1` (current ones match `br0`, `eth0`, `wlan0` by exact
  name; OK) and dhcpcd isn't running (`systemctl is-active dhcpcd`), or has `denyinterfaces wlan1`.
- **Do not use RaspAP's "WiFi client" page** for `wlan1`. It drives wpa_supplicant directly and will fight NM.
  Ignore `wlan1` in the RaspAP dashboard; never select it as the AP interface.
- Verify: `nmcli dev status` (wlan1 = managed, wlan0 = unmanaged), `networkctl list`.

### 3. Uplink detection (must fix)
`raspap/99-pi5connect` only triggers `pi5connect.sh` for `KNOWN_UPLINKS=("eth1")` or names matching
`enx*|eth*|usb*|wwan*|ppp*`. `wlan1` never triggers it, so no default route/MASQUERADE gets set.
`pi5connect.sh` itself already accepts `wlan1` (it only excludes `wlan0`).

Approach: in `99-pi5connect` add `wlan1` to `KNOWN_UPLINKS` (or add `wlan[1-9]*|wlx*` to the pattern). Keep the
exclude list (`wlan0`, `br0`, ...) unchanged.

Note: `pi5connect.sh` picks the first UP interface that can ping 8.8.8.8, in `/sys/class/net` order (`eth*` before
`wlan1`). Fine as long as only one hub port is powered at a time.

### 4. Captive portals (likely at campgrounds)
`pi5connect.sh` only selects an uplink if `ping -I <iface> 8.8.8.8` succeeds. Behind a captive portal that fails
until someone logs in, so Sophie never routes to it, and nobody on the RV LAN can reach the portal page to log in.

Approach: in `pi5connect.sh`, if no interface passes the ping test but exactly one candidate is UP with a gateway,
select it anyway (route + MASQUERADE) and log "no internet; possible captive portal". Then a phone/laptop on Sophie
WiFi gets the portal page and logs in (the portal authorizes the Alfa's MAC, so the whole RV is authorized).
Keep the MAC stable for this: `nmcli con modify <profile> 802-11-wireless.cloned-mac-address permanent`.

### 5. USB hub port switching = hot-plug
Selecting the WiFi WAN on the CoolGear hub powers the port on; the adapter enumerates, loads firmware, and NM
reconnects (several seconds to ~20 s). Switching away removes `wlan1` entirely.

Approach:
- Rely on issue 1 (stable name) and NM autoconnect (profiles bound to the SSID, `connection.autoconnect yes`,
  `connection.interface-name wlan1` or none).
- If the web UI shows uplink status, allow ~30 s after a port switch before reporting failure.

### 6. Power
Spec USB 2.0 port = 500 mA; adapters can exceed it while transmitting, worse at the end of a long cable.
Approach: confirm the CoolGear hub is externally powered; use an active (repeater) USB extension. Check `dmesg`
for disconnect/reset messages under load (`iperf3`).

### 7. First-plug quirks
- Virtual CD-ROM mode: if `lsusb` shows a storage device instead of `0e8d:xxxx`, install/verify `usb-modeswitch`.
- Firmware: `sudo apt install firmware-misc-nonfree` (MediaTek blobs); check `dmesg | grep -i mt79` (or `mt76`)
  for firmware load errors.

### 8. Regulatory domain
Wrong/unset country limits 5 GHz channels and TX power on both radios.
Approach: set `country=US` (`raspi-config` / `iw reg set US` and `country_code=US` in hostapd); verify `iw reg get`
shows US for both phys.

### 9. Power save
Disable power save on the uplink: `nmcli con modify <profile> 802-11-wireless.powersave 2` (and in the profiles
the web UI creates; see 10).

### 10. Web UI WiFi picker path
Today: Internet page network picker → `server.py /api/wifi/{status,networks,profiles,connect,forget}` → HTTP JSON
to `rpzero_wifi_api.py` (WiFitoHostBridge repo) on the Zero at `10.10.0.1:12346`, running as root, driving `nmcli`
on the Zero's `wlan0`. The webserver container uses `network_mode: host`. (The older `/api/wifi-config` →
`RP5toRPZero2WControl.py` → `RPZero2WListener.py` path on 12345 also still exists.)

Approach (no new code; `rpzero_wifi_api.py` is already env-configurable):
- Run `rpzero_wifi_api.py` **on the RP5 host** as root under systemd (adapt `wifi-bridge-api.service`) with:
  ```
  WIFI_API_BIND=127.0.0.1
  WIFI_API_ALLOWED_NET=127.0.0.0/8
  WIFI_IFNAME=wlan1
  SELF_AP_SSID=Sophie          # keeps Sophie's own AP out of the picker
  ```
  Binding 127.0.0.1 keeps the API off both the campground network and the RV LAN.
- In `docker-compose.yml`, set `WIFI_BRIDGE_HOST=127.0.0.1` for the webserver (`server.py` reads it for both the
  API on 12346 and the old path). No client code change.
- In the API's `nmcli connection add` (`rpzero_wifi_api.py` ~line 735), add `802-11-wireless.powersave 2` and
  `802-11-wireless.cloned-mac-address permanent` (issues 4 and 9). This benefits the Zero too.
- Check that the code doesn't assume Zero-only details (e.g., the `p2p-dev-wlan0` comment ~line 426) when run on
  the RP5, which also has a `p2p-dev-wlan0` for the AP radio.
- Keep the Zero setup intact as a fallback until the Alfa is proven; switching back is just hub port +
  `WIFI_BRIDGE_HOST`.

### 11. Band plan with Sophie's AP
Campground WiFi is mostly 2.4 GHz; move Sophie's AP (onboard `wlan0`) to 5 GHz so the Roku is off the uplink's
band. If the park AP offers 5 GHz, prefer it for the uplink and put Sophie's AP on a non-overlapping 5 GHz
channel. See the hostapd fixes C/D in `WiFitoHostBridge/plan-speed.md`.

### 12. Sophie directly exposed to the campground network (must fix BEFORE first join)
Today the Zero NATs between the park WiFi and Sophie, so other campers can't open connections to her. With the
adapter, Sophie's `wlan1` is on the park network itself, and her services listen on all interfaces: dashboard
(8000/3000), MQTT (1883/9001), SSH, VNC (5900), RaspAP web UI (80), dnsmasq (53), plus mDNS. The webserver
container is `network_mode: host`, so it binds `wlan1` too. Docker-published ports are reached via FORWARD
(DNAT), so INPUT rules alone don't cover them. This already applies to the direct-Ethernet uplink (option 2)
today.

Approach: apply to whatever uplink is active (`ACTIVE_IFACE`), not just `wlan1`, idempotently from
`raspap/pi5connect.sh` (it already runs on every uplink change; `-C` before `-I`):
```bash
# host services: only replies to connections Sophie started
iptables -I INPUT 1 -i "$ACTIVE_IFACE" -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
iptables -I INPUT 2 -i "$ACTIVE_IFACE" -j DROP
# Docker-published ports (DNAT -> FORWARD); DOCKER-USER is evaluated before Docker's own rules
iptables -I DOCKER-USER 1 -i "$ACTIVE_IFACE" -m conntrack --ctstate ESTABLISHED,RELATED -j RETURN
iptables -I DOCKER-USER 2 -i "$ACTIVE_IFACE" -j DROP
```
Remove the rules for the old interface when the uplink changes (same loop that removes old MASQUERADE rules).
DHCP client traffic uses raw sockets and is unaffected; ICMP errors (PMTU) pass as RELATED.
`pi5connect.sh` only runs once an uplink is selected, so there is a window after `wlan1` associates (or forever,
if it is UP but never selected). Close it with the same four rules for `wlan1` saved statically at boot
(`iptables-save > /etc/iptables/rules.v4`, iptables-persistent); rules by interface name are valid even while
`wlan1` doesn't exist.

Also:
- **FORWARD:** confirm new connections from the uplink to `br0` are dropped (`iptables -S FORWARD`: policy DROP,
  or only the RELATED,ESTABLISHED rule `pi5connect.sh` adds). Never run `WiFitoHostBridge/fix_interface_routing.sh`
  on Sophie (it sets FORWARD ACCEPT and flushes NAT).
- **IPv6:** a park network with SLAAC gives `wlan1` a global v6 address that bypasses all iptables (v4) rules.
  Disable it on the uplink profile: `nmcli con modify <profile> ipv6.method disabled`, and add
  `ipv6.method disabled` to `rpzero_wifi_api.py`'s `connection add` (issue 10). Verify `ip -6 addr show wlan1` shows
  no global address.
- **mDNS:** `/etc/avahi/avahi-daemon.conf` → `deny-interfaces=wlan1` (and other uplinks), restart avahi.
- **SSH:** key-only (`PasswordAuthentication no`) as defense in depth.

Verify before trusting a park network: from a laptop joined **directly to the park WiFi** (not Sophie's), run
`nmap -Pn -p- <Sophie wlan1 IP>` → all ports filtered. Then from the RV LAN confirm the dashboard, MQTT, SSH,
and VNC still work via `br0`.

## Tradeoffs vs keeping the Zero

- **Security:** Sophie sits directly on untrusted networks (issue 12). Required fix, not optional.
- **Fault isolation:** an adapter driver/firmware hang or USB reset now happens on the box that runs everything and
  can disturb other devices on the hub (BLE dongles). Mitigation: power-cycle the hub port via the CoolGear.
- **Complexity on Sophie:** two radios, name pinning, NM vs hostapd ownership. A RaspAP/Pi OS update can now break
  uplink and AP together.
- **Rework:** the Zero's WiFi API and the picker were just built; moving the API to the RP5 is mostly config but
  needs re-testing, and a root `nmcli` API now runs on the main box.
- **Cost:** ~$60–70 adapter + active USB extension + weatherproof enclosure.
- Not downsides: placement (both are on a USB cable), power, captive portals (same either way), RP5 CPU (far
  below limits at USB 2.0 / campground rates).
- Fallback: keep the Zero; switching back = hub port + `WIFI_BRIDGE_HOST`.

## Rollout

1. Run `WiFitoHostBridge/plan-speed.md` tests with the current Zero setup (baseline).
2. Buy the AWUS036AXML (+ active USB 2.0 extension, weatherproof box).
3. Bench test on Sophie: plug into a spare port, `lsusb`, `dmesg`, `iw dev`, `nmcli dev wifi list ifname wlanX`.
4. Apply issues 1, 2, 7, 8 (names, NM ownership, firmware, country). Reboot; verify `wlan0` AP still works and
   names are stable across hub port off/on.
5. Apply issue 12 (uplink firewall, IPv6 off, avahi), then issue 3 (dispatcher) and 4 (captive-portal
   fallback). Only then connect manually with `nmcli`; verify default route
   and MASQUERADE via `wlan1`, internet from the RV LAN.
6. Apply issue 10 (WiFi API on the RP5 host) and test the Internet page network picker end to end.
7. Move the adapter to its outside mount on the Zero's hub port (replacing the Zero); run the issue 12 `nmap` check from
   the park WiFi, then re-run the speed tests and compare
   with the baseline.
8. Update `rv/CLAUDE.md` (uplink option 3 description) and `rv/raspap/README.txt`; retire or archive the Zero
   setup once proven.
