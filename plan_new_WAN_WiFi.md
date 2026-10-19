# plan_new_WAN_WiFi.md — USB WiFi adapter as a WAN uplink (replacing the Zero 2W bridge)

STATUS: **in deployment.** The AWUS036ACM is bought, bench-tested on the RP5 and joined to the home
AP as `wlan1` (2026-10-17). Issues 1, 2, 7, 8 and 10 are done, plus issue 11's profile pair, and
`plan_wifi.md` Phase 5 is complete (2026-10-18). Remaining: the outside antenna mount, moving the
adapter onto the hub (issue 5/6), captive-portal fallback (issue 4), `plan_firewall.md` (issue 12),
and the before/after speed comparison. Note the adapter bought was the **ACM**, not the AXML this
plan recommended — see "Measured on hardware".

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

### 1. Interface naming — DONE 2026-10-18
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
Deployed exactly as above, with the real MACs: `10-wlan-ap.link` → `wlan0` (onboard
`2c:cf:67:ab:1b:94`), `11-wlan-wan.link` → `wlan1` (Alfa `00:c0:ca:be:29:62`). Reference copies are
in `raspap/`.

`update-initramfs` was **not** needed — Pi OS does not rename network interfaces in the initramfs.
udev confirms both files applied to the live interfaces:

```
$ udevadm info /sys/class/net/wlan1 | grep -E 'ID_NET_LINK_FILE|ID_NET_NAME='
E: ID_NET_LINK_FILE=/etc/systemd/network/11-wlan-wan.link
E: ID_NET_NAME=wlan1
```

Also answered: Pi OS would otherwise have called it `wlan1` anyway (`ID_NET_NAME_MAC` is
`wlx00c0cabe2962`, but the `NamePolicy=mac` that would use it is masked — see the `enx*` trap in
`WiFitoHostBridge/CLAUDE.md`). The pinning still matters for *which* radio gets which name.
**[USER]** still to verify: names stable across a reboot and across a hub port off/on.

### 2. Which network manager owns which interface — DONE 2026-10-18
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

Deployed: `/etc/NetworkManager/conf.d/99-unmanaged-wlan0.conf` as written above (copy in
`raspap/`). Verified on hardware — `nmcli dev status` shows `wlan0 wifi unmanaged` and
`wlan1 wifi connected`, dhcpcd is `inactive`, and no `.network` file matches `wlan1`.

### 3. Uplink detection — RESOLVED 2026-10-17, verified live
This was written against the **stale repo copy** of `99-pi5connect`. The *deployed* hook already matches
`wlan*` (excluding `wlan0`), so `wlan1` does trigger `pi5connect.sh`. Confirmed on hardware while testing the
Alfa:

```
Dispatcher: triggering pi5connect for wlan1 down
pi5connect.sh triggered: iface=wlan1 status=down
```

The repo copy has since been synced from the deployed version (it had pointed `MAIN_SCRIPT` at the repo path and
invoked it with **no arguments**, which would have made pi5connect fall back to its boot scan instead of acting on
the triggered interface — deploying that copy would have broken uplink switching).

Also added 2026-10-17: the hook now triggers on **`dhcp4-change`**. NM fires `up` as soon as the link is usable,
which can precede DHCP returning a gateway; pi5connect then logged "cannot determine gateway" and exited, and
nothing re-ran it. Measured on the cellular port: lease took 37 s, `up` fired with no gateway, lease landed one
second later, no re-evaluation followed. A slow-DHCP uplink failed while a fast one worked.

The selection note above is also stale. `pi5connect.sh` v2.1 does **not** scan `/sys/class/net` order on an event:
it takes the interface the dispatcher names, then (a) keeps a healthy incumbent WAN rather than being preempted
(`PI5_FORCE=1` overrides), (b) probes the candidate out of its own device with ICMP then TCP before touching the
default route, and (c) rolls back if the commit ends with no internet. Verified: with `eth1` as WAN, bringing up
`wlan1` logged `Keeping WAN=eth1 (healthy); ignoring candidate wlan1.` and left the route alone.

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

### 10. Web UI WiFi picker path — DONE 2026-10-18
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
- ~~Keep the Zero setup intact as a fallback until the Alfa is proven; switching back is just hub
  port + `WIFI_BRIDGE_HOST`.~~ **Overtaken by events: the Zero was unplugged on 2026-10-18**, so
  there is no quick switch back. Reviving it needs the gadget cable re-plugged, `setup_services.sh
  zero` on the Zero and `WIFI_BRIDGE_HOST=10.10.0.1`. The Alfa is now the only WiFi uplink.

**Done as planned, with these additions:**
- The RP5 unit is a separate file, `WiFitoHostBridge/wifi-api-rp5.service`, rather than an edit to
  the Zero's `wifi-bridge-api.service` — so the Zero's fallback stays installable and documented.
  `setup_services.sh` now takes `rp5|zero` and refuses to install one while the other is enabled
  (they would collide on port 12346 and both drive one NetworkManager). The RP5 unit drops the
  `usb0-up.service` ordering: loopback always exists, so there is no bind race.
- `WIFI_BRIDGE_HOST` default in `server.py` is now `127.0.0.1`, and compose sets it explicitly. The
  unreachable-API error message names the right service for whichever host is configured.
- The hardening settings went in as `PROFILE_HARDENING`, applied on every profile the API creates
  **and on every profile it activates** (idempotent; `nmcli connection modify` does not reactivate,
  so it cannot drop the uplink). `ipv6.method disabled` is included, which issue 12 also asks for.
- The `p2p-dev-wlan0` comment was Zero-specific and is fixed; nothing else assumed the Zero.
- Issue 11's profile pair is implemented here too, so the picker creates it — see issue 11.
- `plan_wifi.md` Phase 5 was done at the same time, so TCP:12345 and `/api/wifi-config` are gone.

### 11. Band plan with Sophie's AP
Campground WiFi is mostly 2.4 GHz; move Sophie's AP (onboard `wlan0`) to 5 GHz so the Roku is off the uplink's
band. If the park AP offers 5 GHz, prefer it for the uplink and put Sophie's AP on a non-overlapping 5 GHz
channel. See the hostapd fixes C/D in `WiFitoHostBridge/plan-speed.md`.

**"Prefer 5 GHz" must be enforced explicitly — NetworkManager gets it wrong (measured 2026-10-17).** NM ranks
candidate BSSes by signal strength, so given the same SSID on both bands it picked **2.4 GHz at -62 dBm over
5 GHz at -78 dBm — and the band it chose was 10-40x slower** (see Measured section). Signal strength is the wrong
metric when the strong band is congested and the weak one is clean.

Workaround in use: two profiles per SSID, the 5 GHz one with a higher autoconnect priority.

```bash
nmcli con add type wifi ifname wlan1 con-name <ssid>-5g ssid <ssid> \
  -- 802-11-wireless-security.key-mgmt wpa-psk 802-11-wireless-security.psk <psk> \
     802-11-wireless.band a connection.autoconnect-priority 10
nmcli con add type wifi ifname wlan1 con-name <ssid>    ssid <ssid> \
  -- ... (no band lock, priority 0)   # fallback for 2.4-only parks
```

NM tries the higher priority first and falls back if the 5 GHz BSS is absent. Note a band-locked profile fails
outright where that band is missing, which is why the unlocked fallback is required.

**DONE 2026-10-18 — the picker creates the pair.** `rpzero_wifi_api.py` adds `<name>-5g` (band `a`,
autoconnect-priority 10) plus the unlocked `<name>`, but only when the scan actually saw that SSID
on 5/6 GHz — so a 2.4-only park gets one profile and no guaranteed-failing activation attempt.
Three consequences worth knowing:

- The scan's per-SSID `freq` and `signal` are the **strongest** BSS's, which on a dual-band SSID is
  routinely the 2.4 GHz one. The API now also reports `bands`, `has_5g`, `in_use_band` and
  `in_use_signal` from the *associated* BSS. Without that split, `/api/status` reported
  "band 2.4 GHz" while sitting on a 5 GHz-locked profile.
- `connect` falls back to the unlocked profile if the 5 GHz activation fails with `no_ap` (the scan
  can be seconds stale), but not on an auth failure, which would just waste another 50 s.
- **Forget had to change meaning.** It used to refuse an SSID with several profiles (409
  `ambiguous`); that would have made every pair unforgettable from the picker. It now deletes every
  profile for the SSID, active one last, and the picker calls it by `ssid` instead of `uuid`.

### 12. Sophie directly exposed to the campground network (must fix BEFORE first join)
> Superseded by `plan_firewall.md`, which covers all uplinks with interface-based default-deny. Deploy that
> before the Alfa first joins a park network; the notes below are kept for context.

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
  or only the RELATED,ESTABLISHED rule `pi5connect.sh` adds).
- **IPv6:** a park network with SLAAC gives `wlan1` a global v6 address that bypasses all iptables (v4) rules.
  Disable it on the uplink profile: `nmcli con modify <profile> ipv6.method disabled`, and add
  `ipv6.method disabled` to `rpzero_wifi_api.py`'s `connection add` (issue 10). Verify `ip -6 addr show wlan1` shows
  no global address.
- **mDNS:** `/etc/avahi/avahi-daemon.conf` → `deny-interfaces=wlan1` (and other uplinks), restart avahi.
- **SSH:** key-only (`PasswordAuthentication no`) as defense in depth.

Verify before trusting a park network: from a laptop joined **directly to the park WiFi** (not Sophie's), run
`nmap -Pn -p- <Sophie wlan1 IP>` → all ports filtered. Then from the RV LAN confirm the dashboard, MQTT, SSH,
and VNC still work via `br0`.

## Measured on hardware — 2026-10-17 (AWUS036ACM on the RP5)

Bench test with the Alfa plugged **directly into an RP5 USB 3 port** (not the hub), `eth1` wired kept as the live
WAN throughout so the test could not strand the session. Raw data in `WiFitoHostBridge/Results_WiFi_testing.md`.

### It just works — no driver, firmware or modeswitch issues

Contrary to issue 7, nothing was needed. Plugged in, enumerated, bound, radio registered:

```
usb 4-1: New USB device found, idVendor=0e8d, idProduct=7612
mt76x2u 4-1:1.0: ASIC revision: 76120044
mt76x2u 4-1:1.0: ROM patch build: 20141115060606a
ieee80211 phy1: Selected rate control algorithm 'minstrel_ht'
```

No virtual-CD mode, no `usb-modeswitch`, no `firmware-misc-nonfree`. `mt76x2u` is in the stock Pi OS kernel
(6.12.96). The radio exposes **28 channels on 5 GHz** and 14 on 2.4, with VHT (`0x318001b0`, short GI 80 MHz).
Regulatory domain already `country US: DFS-FCC`, so issue 8 is satisfied as-is.

**Gotcha:** the power LED stays dark until something brings the interface up. It is *not* a sign of failure —
easy to misread as "no power", since Windows activates the radio on plug-in and lights it immediately.

### Throughput, same SSID, same position, minutes apart

| Path | Download | Latency | Link |
|---|---|---|---|
| Wired `eth1` (reference) | **90.5 Mbps** | 1.1 ms to router | 100 Mb full duplex |
| **Alfa, 5 GHz ch36, -78 dBm** | **28.2 / 29.6 / 30.0 Mbps** — steady | **5.5 ms** avg | VHT-MCS1 40 MHz **NSS 2** |
| Alfa, 2.4 GHz ch6, -62 dBm | 0.68 / 2.2 / 3.5 Mbps — erratic | ping timed out | MCS5 20 MHz NSS 1 |

**The headline: 5 GHz beat 2.4 GHz by 10-40x despite being 16 dB weaker.** Cause is co-channel contention, not
signal: a scan found `Decher`, `Decher&BlankGuests`, `Buckley Clan 2` and two hidden networks **all on 2437 MHz**.
A clean weak channel beats a strong congested one, decisively. This was the opposite of the prediction going in
(that -78 dBm would be too weak for 5 GHz to be worth using at this location).

So the Alfa's value is **reaching 5 GHz at all** — not signal strength and not MIMO. On 2.4 GHz it measured
-62 dBm vs the Zero's -64.3, i.e. no meaningful antenna advantage from where it sat. The 2x2 does engage
(tx MCS 11-12 on 2.4, NSS 2 on 5 GHz under load), but the AP only sent 1x1 rates downstream, so MIMO mostly
helped upload. The Zero is 2.4-only and cannot escape that congested channel at all, which is the real argument
for replacing it.

Caveat: the adapter sat on the Pi's chassis with stock dipoles unoriented — the antenna work in "Antenna and
mounting" should improve the 5 GHz figure, and that is where the remaining headroom is.

### Issue 6 (power) — a real constraint found on the RP5

The Pi 5 caps **total** USB current at 600 mA unless `usb_max_current_enable=1` is set in
`/boot/firmware/config.txt`. It is not set, and declared draws on the Pi's own ports already exceed it:

| Device | `bMaxPower` |
|---|---|
| Edimax Bluetooth | 500 mA |
| ASUS BT500 | 500 mA |
| CoolGear hub | 100 mA |
| Alfa (when added) | ~450-500 mA |

`bMaxPower` is a declared ceiling, not actual draw, and Linux does not enforce the Pi's limit at the descriptor
level — which is why it initialised fine and scanned fine. But the limiter is real hardware and a 2x2 radio under
sustained transmit is the load that trips it. `vcgencmd get_throttled` stayed `0x0` throughout this test.

Two mitigations, and the second is free: set `usb_max_current_enable=1` (needs an adequate PSU **and a reboot**),
or run the adapter from the externally-powered hub as issue 6 already proposes — the planned Plugable replacement
has a 60 W supply, so the Alfa draws from the hub rather than the Pi.

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

1. ~~Run `WiFitoHostBridge/plan-speed.md` tests with the current Zero setup (baseline).~~ DONE —
   `WiFitoHostBridge/Results_WiFi_testing.md`.
2. ~~Buy the adapter~~ DONE — the **ACM**, not the AXML. Active USB extension and weatherproof box
   still to buy.
3. ~~Bench test on Sophie~~ DONE 2026-10-17 — "Measured on hardware" above.
4. ~~Apply issues 1, 2, 7, 8 (names, NM ownership, firmware, country).~~ DONE 2026-10-18. 7 and 8
   needed nothing. **[USER]** still owes the reboot check: `wlan0` AP still works, and the names
   are stable across a reboot and a hub port off/on.
5. Apply `plan_firewall.md` (supersedes issue 12: uplink firewall, IPv6 off, avahi), then issue 4
   (captive-portal fallback). Issue 3 needed no work — the deployed dispatcher already handles
   `wlan*`. Deferred by decision 2026-10-18: parked on a trusted home LAN, so not yet urgent.
   **Must be done before the Alfa first joins a park network.**
6. ~~Apply issue 10 (WiFi API on the RP5 host)~~ DONE 2026-10-18 — `wifi-api-rp5.service`,
   `WIFI_BRIDGE_HOST=127.0.0.1`. End-to-end picker test: see Verification below.
7. Move the adapter to its outside mount on the hub port the Zero used; run the `nmap` check from
   the park WiFi, then re-run the speed tests and compare with the baseline. Note the Coolgear hub
   is being replaced by a Plugable 7-port powered hub, which also settles issue 6 (the Pi 5's
   600 mA total USB cap) by powering the adapter from the hub.
8. ~~Update `rv/CLAUDE.md` (uplink option 3) and `rv/raspap/README.txt`~~ DONE 2026-10-18. Retire or
   archive the Zero setup once proven — its installed files were deliberately left in place.

## Verification — picker end to end (2026-10-18)

Run on the RP5 with the wired `eth1` uplink live, so a failed WiFi join cannot strand the session.
`pi5connect.sh` v2.1 keeps a healthy incumbent WAN, which is the second layer of that protection.

1. `sudo ./setup_services.sh rp5`, then `curl -s http://127.0.0.1:12346/api/health` — expect
   `ifname: wlan1`.
2. `curl -s 'http://127.0.0.1:12346/api/networks?rescan=1'` as root — expect `Sophie` with
   `blocked: "self"`, and dual-band SSIDs carrying `has_5g: true` with `bands: ["2.4","5"]`.
3. `cd docker && docker compose up -d --build webserver`, then the Internet page: status panel shows
   the band, list shows 5 GHz tags, connect to a dual-band SSID creates the `-5g` pair
   (`nmcli -f NAME,TYPE con show`), and Forget removes **both**.

### Results (2026-10-18, service v0.3.0 on `wlan1`, WAN on `eth1` throughout)

Passed: health reports `ifname: wlan1`; root rescan returns `Sophie` with `blocked: "self"` and
`joinable: false`, and `bands`/`has_5g` are right on every SSID; `/api/status` reports
`band: "5"`, `signal: 41` while on `alfa-Decher-5g` — the **associated** BSS, not the SSID's
strongest, which is the bug this fixed (the 2.4 GHz BSS of the same SSID reads 64); the saved pair
is `alfa-Decher-5g` (band `a`, priority 10) + `alfa-Decher` (unlocked, priority 0); the dashboard
proxy at `127.0.0.1:12346` returns all of it through `/api/wifi/*`, and `/api/wifi-config` is gone.
Guards: self-AP → 400 `blocked_self`; 7-char PSK → 400; no ssid → 400; forget an active SSID
without `force` → 409 naming the profile.

Also passed, on live connects to a network that cannot complete: the `-5g` profile is tried first,
the **`no_ap` fallback** then retries the unlocked sibling (phase text
`associating (no 5 GHz; any band)`), the failure is reported as `no_ap`/`auth_failed`, both created
profiles are deleted, and `rolled_back: true` with `alfa-Decher-5g` reactivated and its IP intact.
Profile hardening is confirmed applied at creation: `powersave=disable`, `cloned-mac=permanent`,
`ipv6.method=disabled`.

**Forget on a 2-profile set: verified 2026-10-18** on a real WPA2 dual-band SSID. The pair built as
designed (`-5g` band `a` priority 10 + unlocked priority 0, both hardened) and the join landed on
the `-5g` profile. `forget {ssid, force}` returned **two** `deleted_profiles`, in the order the code
claims — unlocked sibling first, **active profile last**, so dropping the link cannot leave a
sibling behind to autoconnect into the network just forgotten. `nmcli` confirmed zero remaining,
the `Decher` pair was untouched, and `wlan1` auto-recovered to `alfa-Decher-5g` within 8 s on
priority 10. `deleted` (singular) is the active profile, which is what the dashboard names.

New ground truth found while testing (all four cost time to interpret):

- **The first forced rescan after a service start returns a short list.** At 15 s uptime it was
  missing `Sophie` at signal 100; three later rescans all returned it. NM's BSS table is still
  filling. Don't read a cold first scan as a scan bug.
- **`/api/profiles` is TTL-cached and goes stale during a connect** — `do_connect` refreshes it
  once at entry, before it creates anything. Polling it mid-connect shows the *pre-connect* list,
  so use `nmcli -t -f NAME con show` as ground truth when watching profiles get created.
- ~~**A pair is not guaranteed for a marginal network.** Correct behaviour, not a bug.~~
  **Wrong — corrected the same day, it was a bug.** Partly it is a marginal network's volatile
  5 GHz BSS, but the dominant cause was the cold cache: `ssid_has_5ghz` and `key_mgmt_for` both read
  `NETWORKS_CACHE.peek()`, and **every mutate invalidates that cache**, so a connect following a
  failed connect or a forget saw nothing and silently skipped the `-5g` sibling. That is exactly the
  retry a user makes after mistyping a password. Proved on hardware: with a correct password the
  first connect built one profile, and the second — after a scan — built the pair. `key_mgmt_for`
  had it worse: a cold cache reads as `security=""`, which sends a WPA3-only AP down the `wpa-psk`
  path and fails the handshake, surfacing as a rejected password. Both now use `get()`, which loads
  with `rescan=False` (sub-second, no radio activity) inside a connect that already runs 20-50 s.
  Fixed in v0.3.1. **The lesson generalises: `peek()` is only safe where a stale-or-empty answer is
  acceptable, which is `load_status`, not a decision that shapes what gets created.**
- **`/api/status` reports an empty `band` and `signal: 0` between a connect and the next
  `/api/networks` call.** `load_status` uses `Cache.peek()` on purpose so a 2-5 s status poll never
  blocks behind a 5.3 s scan; the connect invalidated the cache and only a scan refills it. The
  picker renders `—` for an empty band, so this is invisible in the UI. Leave it alone.

### Signal in dBm (API v0.4.0, verified 2026-10-18)

The picker showed a 0-100 quality percentage because that is all `nmcli` reports. Real RSSI now comes
from `iw`. Verified against `iw dev wlan1 link` as ground truth: status reported **-78 dBm** where iw
read -78, and a warm scan resolved all six networks -- five measured, one flagged estimated, none
missing. Two results worth keeping:

- **Deriving dBm from the percentage cannot work at the top of the scale.** NM clamps at
  -40 dBm = 100%, so Sophie's own AP reads 100% while iw measures **-32 dBm**; the inverse would have
  said -40. At the other end the inverse was within ~1 dB. That settles measure-vs-derive.
- **dBm survives a cold scan cache where the percentage does not.** Thirty seconds after the service
  restarted, status read `pct=0` but `dBm=-78`, because `iw link` reads the live association and owes
  nothing to the scan cache. The dBm is now the more reliable of the two numbers.

Note the list and the status panel legitimately differ for a dual-band SSID: the list shows the
**strongest** BSS (`Decher` -65 dBm, a 2.4 GHz radio) and status the **associated** one (-77 dBm on
5 GHz). Same split that caused the original band/signal bug -- here it is intended, and `band: "5"`
makes it legible.

The whole run was done with an unprivileged timed auto-revert armed
(`scratchpad/wlan1-revert.sh`: after 240 s, re-`POST /api/connect {"ssid":"Decher"}` unless already
there). Worth reusing — **it needs no sudo**, because the root API is the thing doing the work.
It logged `revert not needed`. The WAN stayed `eth1` the entire time; `wlan1`'s default route sits
at metric 500, so even a successful join to a captive-portal network could not have stolen it.

## The Plugable hub goes in — measured 2026-10-18

Installed into the free blue USB3 port, the Alfa moved to the other blue port.
The Coolgear and the live WAN (`eth1`, Coolgear port 3) were not touched, so the
session was never at risk. Driver and service: `usbhub/`, and its README now
carries the detail.

**The `.link` MAC pinning held across a physical port move.** The Alfa went from
`usb4/4-1` to `usb2/2-1` — a different bus and a different controller — and came
back as `wlan1`, still on `alfa-Decher-5g` with its lease. That was the stated
purpose of `11-wlan-wan.link` and it is now demonstrated rather than assumed.

**A "7-in-1" hub is four hub chips, not one.** One upstream cable presents as:

```
3-1  +  3-1.3     USB 2 chips (bus 3)     port 3 of each pair = internal cascade
4-1  +  4-1.3     USB 3 chips (bus 4)
```

Two 4-port chips in series on each speed, so 4 + 4 presents as 7 sockets. The
consequence for control: **a socket has two sysfs identities**, one per speed,
and a device appears under only the one matching its own speed. Port numbers are
therefore not socket numbers, and the map has to be observed with a device in
hand (`usbhub/map_sockets.py`). `SocketMap` switches all of a socket's
identities, since which one gates VBUS is a board-layout question.

All four chips claim `ppps` to `uhubctl`. That is a capability claim, not proof
that disabling a port removes VBUS; still to be confirmed with a measurement.

### Collateral: the Edimax Bluetooth adapter was displaced

The Pi 5's blue ports each carry both speeds on one connector — blue A is
`usb2:1` (SS) + `usb1:1` (HS), blue B is `usb4:1` + `usb3:1`. Moving the Alfa
into blue A therefore evicted the Edimax, which was on blue A's USB 2 half.

`bat2mqtt` pins that adapter **by MAC** (`08:BE:AC:35:8E:5E` → `hci1`), so when
it vanished battery monitoring stopped at 14:01:56 with no error in the log and
no healthcheck to trip `autoheal` — it still reports `Up`. `hciconfig hci1` now
says "No such device". TireLinc was unaffected: it pins
`C8:7F:54:97:71:1B` = the ASUS BT500, still on `usb3:2`, and is publishing.

Fix: plug the Edimax into the Plugable and restart the container. Worth noting as
a pattern — MAC-pinned adapters survive renumbering but not unplugging, and a
container with no healthcheck fails silently.
