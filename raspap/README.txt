# RaspAP Bridge Configuration

This directory contains configuration files for setting up a network bridge that:
1. Bridges eth0 and wlan0 together via br0 bridge interface
2. Provides internet connectivity through USB/uplink interfaces
3. Enables WiFi hotspot with internet sharing

## Essential Files (Keep These):

### Core Scripts:
- **pi5connect.sh** - Main script that finds active internet interfaces and configures NAT/routing
- **99-pi5connect** - NetworkManager dispatcher script that triggers pi5connect.sh when interfaces change
- **setup-bridge.sh** - Bridge setup script that ensures br0 has correct IP (10.0.0.1/24)
- **wan_revert.sh** - Timed auto-revert watchdog, for use while rewiring the USB uplinks

### Configuration Files:
- **bridge-setup.service** - Systemd service for automatic bridge setup on boot
- **raspap-bridge-br0.network** - systemd-networkd configuration for br0 bridge (10.0.0.1/24)
- **raspap-br0-member-wlan0.network** - Configuration to add wlan0 to br0 bridge

### Two-radio files (added 2026-10-18, for the Alfa USB WiFi uplink):
- **10-wlan-ap.link** - Pins the ONBOARD radio to wlan0 by MAC (2c:cf:67:ab:1b:94)
- **11-wlan-wan.link** - Pins the ALFA adapter to wlan1 by MAC (00:c0:ca:be:29:62)
- **99-unmanaged-wlan0.conf** - Tells NetworkManager to leave wlan0 alone (hostapd owns it)

Without the .link files, enumeration order can swap at boot and hostapd would start on the Alfa;
a hub port toggle could also bring the adapter back as wlan2. These are reference copies of what
is deployed -- re-capture them if the hardware changes.

## Installation:

1. Copy 99-pi5connect to NetworkManager dispatcher directory:
   ```bash
   sudo cp 99-pi5connect /etc/NetworkManager/dispatcher.d/
   sudo chmod +x /etc/NetworkManager/dispatcher.d/99-pi5connect
   ```

2. Install systemd service for bridge setup:
   ```bash
   sudo cp bridge-setup.service /etc/systemd/system/
   sudo systemctl enable bridge-setup.service
   ```

3. Install systemd-networkd configurations:
   ```bash
   sudo cp raspap-*.network /etc/systemd/network/
   sudo systemctl enable systemd-networkd
   ```

4. Two-radio setup (only with the Alfa USB WiFi adapter fitted):
   ```bash
   sudo cp 10-wlan-ap.link 11-wlan-wan.link /etc/systemd/network/
   sudo cp 99-unmanaged-wlan0.conf /etc/NetworkManager/conf.d/
   sudo systemctl reload NetworkManager
   ```
   The .link files apply on the next hotplug or boot, not retroactively. Verify with
   `udevadm info /sys/class/net/wlan1 | grep ID_NET_LINK_FILE` and
   `nmcli dev status` (wlan0 = unmanaged, wlan1 = managed).

## wan_revert.sh - the auto-revert watchdog

Arm this before unplugging anything on the WAN side. It snapshots the working state, then runs as
a transient systemd unit -- so it outlives the SSH session that started it -- and restores *some*
working uplink if the RV is left with none.

```bash
sudo ./wan_revert.sh arm 90        # snapshot + watch for 90 minutes, then self-disarm
sudo ./wan_revert.sh status        # armed? internet up? what was the snapshot?
sudo ./wan_revert.sh disarm        # done rewiring
tail -f /var/log/wan-revert.log    # what it is doing
```

It refuses to arm when there is no internet, because then it cannot tell a rewiring mistake from
the state it started in. `WAN_REVERT_DRYRUN=1` logs every action and changes nothing.

Default timing: 120 s grace before the first check, then a check every 60 s, and the ladder runs
only after 3 consecutive failures. That is deliberate -- an adapter is out of its socket for tens
of seconds during normal work and the watchdog must not fight you.

The recovery ladder, least-disruptive first, re-probing after every rung and stopping as soon as
the probe passes (same probe as pi5connect.sh: ICMP then HTTP to IP literals, no DNS):

1. `nmcli networking on`, re-run pi5connect.sh
2. Power ON every mapped socket on the powered hub, so whatever is plugged in enumerates and
   pi5connect has a candidate to probe. Turning a socket on can never cut anything, so this
   ignores the protection list on purpose. Uses the hub API on 127.0.0.1:12347, falling back to
   writing the sysfs `disable` attributes straight from /etc/usbhub/sockets.json -- the API being
   down is exactly the sort of thing that happens mid-rewire.
3. Re-authorize a stalled MT7612U. Seen 2026-10-18: after the hub re-enumerated, the Alfa logged
   `probe with driver mt76x2u failed with error -110` (a firmware-upload timeout) and sat there
   enumerated with no driver and no wlan1. Nothing in the kernel retries it. Writing 0 then 1 to
   the device's `authorized` re-runs the probe and touches nothing else on the bus.
4. Bring up a saved WiFi profile on wlan1, in autoconnect-priority order, skipping NM's
   `preconfigured` stub and anything matching our own AP name (joining Sophie loops the uplink
   back through the RP5).
5. `nmcli device connect` any ethernet device that has carrier but no IPv4. Needed because
   "Wired connection 1" is pinned to `connection.interface-name=eth1`, not to a MAC, so an
   adapter that lands on eth2 has no profile.
6. Re-run pi5connect.sh with PI5_FORCE=1.

If all six fail it logs loudly and stops. It does **not** reboot unless `WAN_REVERT_REBOOT=1`: a
reboot restores the *boot-time* configuration, which after rewiring no longer matches the
hardware, so it is as likely to hurt as to help.

What it never touches: br0, eth0, wlan0, hostapd. The control path (SSH over br0) is independent
of the uplink by design, and the watchdog must not be the thing that breaks that.

Nothing is installed and nothing stays enabled -- `arm` creates a transient unit via systemd-run,
so a reboot clears it. Re-arm after a reboot if you are still working.

## How It Works:

1. **Bridge Setup**: br0 bridge is created with IP 10.0.0.1/24
2. **Interface Detection**: pi5connect.sh automatically detects active USB/ethernet uplink interfaces
3. **NAT Configuration**: Sets up iptables rules for internet sharing from uplink to bridge
4. **Auto-Triggering**: NetworkManager dispatcher runs pi5connect.sh when interfaces change state

## Network Layout:
- Bridge (br0): 10.0.0.1/24 - Access point and gateway
- WiFi clients connect to wlan0 → bridged to br0
- Internet via USB/ethernet interfaces (eth1, usb0, etc.) → NAT to br0
