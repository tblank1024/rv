#!/bin/bash

# RaspAP Bridge Mode Installation and Configuration Script
# This script installs RaspAP and configures it for bridge mode with proper networking
#
# THIS SCRIPT NO LONGER TOUCHES NETFILTER. See STEP 7.
#
# It used to write a permissive /etc/iptables/rules.v4 and `iptables-restore`
# it immediately. Re-running it on the live RV would therefore have:
#   - flushed SOPHIE-IN / SOPHIE-FWD, disarming the host firewall
#     (firewall/sophie-firewall.sh, plan_firewall.md)
#   - reopened ports 22, 80, 443 and 53 on EVERY interface, including the
#     uplink -- undoing the MAC-restricted SSH rule added 2026-10-26
#   - set the INPUT and FORWARD policies back to ACCEPT
#   - re-enabled netfilter-persistent, whose iptables-restore is what silently
#     de-armed the firewall for two days on 2026-10-21
#
# Netfilter on Sophie now has two owners and neither is this script:
#   NAT and per-WAN forwarding -> /usr/local/sbin/pi5connect.sh, at runtime
#   filter policy              -> firewall/sophie-firewall.sh, via systemd

set -e  # Exit on any error

echo "================================================"
echo "RaspAP Bridge Mode Installation & Configuration"
echo "================================================"
echo
echo "This script will:"
echo "1. Install the latest RaspAP"
echo "2. Configure bridge mode with DHCP range 10.0.0.x"
echo "3. Bridge eth0 and wlan0 on the same subnet"
echo "4. Enable internet access via USB (eth1)"
echo "5. Allow all devices to communicate with each other"
echo

# Check if running as root
if [[ $EUID -eq 0 ]]; then
   echo "This script should NOT be run as root. Please run as a regular user with sudo privileges."
   exit 1
fi

# Check if user has sudo privileges
if ! sudo -n true 2>/dev/null; then
    echo "This script requires sudo privileges. Please ensure you can use sudo."
    exit 1
fi

read -p "Press Enter to continue or Ctrl+C to cancel..."
echo

# =============================================================================
# STEP 1: System Update and Prerequisites
# =============================================================================
echo "=== STEP 1: Updating system and installing prerequisites ==="
sudo apt update
sudo apt upgrade -y
# iptables-persistent deliberately NOT installed: it enables
# netfilter-persistent, which restores a saved ruleset at boot and raced the
# host firewall into a two-day silent exposure on 2026-10-21. Nothing here
# needs a saved ruleset -- see the note at the top of this file.
sudo apt install -y git curl wget dnsmasq hostapd bridge-utils

# =============================================================================
# STEP 2: Install RaspAP
# =============================================================================
echo
echo "=== STEP 2: Installing latest RaspAP ==="

# Download and run the RaspAP installer
curl -sL https://install.raspap.com | bash -s -- --yes

echo "RaspAP installation completed!"

# =============================================================================
# STEP 3: Configure Bridge Mode
# =============================================================================
echo
echo "=== STEP 3: Configuring bridge mode ==="

# Create systemd network configuration for bridge
echo "Creating bridge network configuration..."

# Bridge device configuration
sudo tee /etc/systemd/network/raspap-bridge-br0.netdev << 'EOF'
[NetDev]
Name=br0
Kind=bridge
EOF

# Bridge network configuration  
sudo tee /etc/systemd/network/raspap-bridge-br0.network << 'EOF'
[Match]
Name=br0

[Network]
DHCP=no
IPForward=yes
ConfigureWithoutCarrier=yes
EOF

# eth0 bridge member configuration.
#
# Matched by MAC, NOT by name. br0 is the first ACCEPT in SOPHIE-IN, so
# whatever joins it is inside the trusted zone and bypasses the host firewall.
# A name match meant any device that enumerated as eth0 -- a USB uplink
# adapter, say -- would land there. Unlikely, since the built-in NIC is a SoC
# device (driver macb, 1f00100000.ethernet) that enumerates before USB, but
# the consequence is a total firewall bypass, so it is pinned.
#
# The MAC is read from the live interface rather than hardcoded, so this stays
# correct if the script is ever run on a different board.
ONBOARD_MAC="$(cat /sys/class/net/eth0/address)"
if [[ -z "$ONBOARD_MAC" ]]; then
    echo "ERROR: cannot read /sys/class/net/eth0/address -- refusing to write a"
    echo "       bridge-member file that would match by name instead." >&2
    exit 1
fi
echo "Pinning the onboard NIC into br0 by MAC: $ONBOARD_MAC"

sudo tee /etc/systemd/network/raspap-br0-member-eth0.network << EOF
# Matched by MAC, not by name -- see the note in install_raspap_bridge.sh.
[Match]
MACAddress=$ONBOARD_MAC

[Network]
Bridge=br0
LinkLocalAddressing=no
ConfigureWithoutCarrier=yes
EOF

# Keep the NAME stable too, matching 10-wlan-ap.link and 11-wlan-wan.link.
# Belt and braces: either this or the MAC match above would be enough on its
# own to keep a USB adapter out of the trusted bridge.
sudo tee /etc/systemd/network/12-eth-onboard.link << EOF
[Match]
MACAddress=$ONBOARD_MAC

[Link]
Name=eth0
EOF

# wlan0 bridge member configuration  
sudo tee /etc/systemd/network/raspap-br0-member-wlan0.network << 'EOF'
[Match]
Name=wlan0

[Network]
Bridge=br0
LinkLocalAddressing=no
ConfigureWithoutCarrier=yes
EOF

# Enable systemd-networkd
sudo systemctl enable systemd-networkd

# =============================================================================
# STEP 4: Configure dhcpcd for bridge
# =============================================================================
echo
echo "=== STEP 4: Configuring dhcpcd for bridge mode ==="

# Backup original dhcpcd.conf
sudo cp /etc/dhcpcd.conf /etc/dhcpcd.conf.backup.$(date +%Y%m%d_%H%M%S)

# Configure dhcpcd for bridge mode
sudo tee /etc/dhcpcd.conf << 'EOF'
# RaspAP Bridge Mode Configuration
hostname
clientid
persistent
option rapid_commit
option domain_name_servers, domain_name, domain_search, host_name
option classless_static_routes
option ntp_servers
require dhcp_server_identifier
slaac private
nohook lookup-hostname

# Bridge configuration - br0 gets static IP
interface br0
static ip_address=10.0.0.1/24
static routers=10.0.0.1
static domain_name_server=10.0.0.1 8.8.8.8
nogateway

# Internet connection via USB (eth1) - get IP via DHCP
interface eth1
# DHCP will be used for internet connection

# Prevent dhcpcd from managing bridge members
denyinterfaces wlan0,eth0
nohook lookup-hostname:eth0,wlan0
EOF

# =============================================================================
# STEP 5: Configure dnsmasq for DHCP
# =============================================================================
echo
echo "=== STEP 5: Configuring dnsmasq DHCP server ==="

# Configure dnsmasq for bridge DHCP
sudo tee /etc/dnsmasq.d/090_br0.conf << 'EOF'
# RaspAP Bridge DHCP Configuration
interface=br0
bind-interfaces
dhcp-range=10.0.0.50,10.0.0.254,255.255.255.0,24h
dhcp-option=6,10.0.0.1,8.8.8.8
dhcp-option=3,10.0.0.1
dhcp-authoritative
dhcp-leasefile=/var/lib/misc/dnsmasq.leases

# Enable DNS forwarding
server=8.8.8.8
server=8.8.4.4
cache-size=1000

# Log DHCP transactions for debugging
log-dhcp
log-queries
log-facility=/var/log/dnsmasq.log
EOF

# =============================================================================
# STEP 6: Configure hostapd for bridge mode
# =============================================================================
echo
echo "=== STEP 6: Configuring hostapd for bridge mode ==="

# Update RaspAP hostapd configuration for bridge mode
sudo tee /etc/raspap/hostapd.ini << 'EOF'
WifiInterface = wlan0
LogEnable = 0
WifiAPEnable = 1
BridgedEnable = 1
WifiManaged = br0
EOF

# Configure hostapd for bridge
sudo tee /etc/hostapd/hostapd.conf << 'EOF'
# RaspAP Bridge Mode hostapd configuration
interface=wlan0
bridge=br0
driver=nl80211
ssid=RaspAP-Bridge
hw_mode=g
channel=7
wmm_enabled=0
macaddr_acl=0
auth_algs=1
ignore_broadcast_ssid=0
wpa=2
wpa_passphrase=ChangeMe
wpa_key_mgmt=WPA-PSK
wpa_pairwise=TKIP
rsn_pairwise=CCMP
EOF

# =============================================================================
# STEP 7: IP forwarding only -- netfilter is not ours to configure
# =============================================================================
echo
echo "=== STEP 7: Enabling IP forwarding (netfilter left to its owners) ==="

# A drop-in, not an append to /etc/sysctl.conf: the old line appended a
# duplicate every time this script ran.
sudo tee /etc/sysctl.d/99-raspap-forward.conf << 'EOF'
# Required for br0 clients to reach the internet. The NAT and forwarding RULES
# are written at runtime by pi5connect.sh, which picks the uplink; the filter
# policy is owned by sophie-firewall.sh. This file only turns the kernel knob.
net.ipv4.ip_forward=1
EOF
sudo sysctl --system >/dev/null

# No /etc/iptables/rules.v4 is written and no iptables-restore is run. The
# previous version did both, which flushed the host firewall's chains and
# reopened 22/80/443/53 on every interface. If you need the uplink NAT
# re-applied, trigger the owner instead:
#     sudo /usr/local/sbin/pi5connect.sh "$(cat /run/pi5connect-wan | cut -d" " -f1)" up
#     sudo /usr/local/sbin/sophie-firewall.sh apply
#     sudo /usr/local/sbin/sophie-firewall.sh docker

# =============================================================================
# STEP 8: Enable required services
# =============================================================================
echo
echo "=== STEP 8: Enabling required services ==="

# Enable all required services
sudo systemctl enable systemd-networkd
sudo systemctl enable dhcpcd
sudo systemctl enable dnsmasq
sudo systemctl enable hostapd
# NOT enabling iptables/netfilter-persistent -- see the note at the top.
# sophie-firewall.service owns the filter policy at boot.
sudo systemctl enable lighttpd  # For RaspAP web interface

# =============================================================================
# STEP 9: Create management scripts
# =============================================================================
echo
echo "=== STEP 9: Creating management scripts ==="

# Create a status check script
sudo tee /usr/local/bin/raspap-bridge-status << 'EOF'
#!/bin/bash
echo "=== RaspAP Bridge Status ==="
echo
echo "Bridge interface:"
ip addr show br0 2>/dev/null || echo "Bridge not found"
echo
echo "Bridge members:"
bridge link show 2>/dev/null || echo "No bridge members"
echo
echo "Internet connection (eth1):"
ip addr show eth1 | grep "inet " || echo "No internet connection"
echo
echo "DHCP leases:"
cat /var/lib/misc/dnsmasq.leases 2>/dev/null || echo "No DHCP leases"
echo
echo "Service status:"
echo "  systemd-networkd: $(systemctl is-active systemd-networkd)"
echo "  dhcpcd: $(systemctl is-active dhcpcd)"
echo "  dnsmasq: $(systemctl is-active dnsmasq)"
echo "  hostapd: $(systemctl is-active hostapd)"
echo
echo "IP forwarding: $(cat /proc/sys/net/ipv4/ip_forward)"
EOF

chmod +x /usr/local/bin/raspap-bridge-status

# Create a restart script
sudo tee /usr/local/bin/raspap-bridge-restart << 'EOF'
#!/bin/bash
echo "Restarting RaspAP bridge services..."
sudo systemctl restart systemd-networkd
sleep 3
sudo systemctl restart dhcpcd
sudo systemctl restart dnsmasq
sudo systemctl restart hostapd
echo "Services restarted. Run 'raspap-bridge-status' to check status."
EOF

chmod +x /usr/local/bin/raspap-bridge-restart

# =============================================================================
# STEP 10: Final configuration and restart
# =============================================================================
echo
echo "=== STEP 10: Applying configuration ==="

# Stop services
sudo systemctl stop hostapd dnsmasq dhcpcd 2>/dev/null || true

# Clear any existing network configuration
sudo ip link set br0 down 2>/dev/null || true
sudo ip link delete br0 2>/dev/null || true

# Apply sysctl settings
sudo sysctl -p

# Start services in the correct order
echo "Starting services..."
sudo systemctl start systemd-networkd
sleep 3
sudo systemctl start dhcpcd
sleep 2
sudo systemctl start dnsmasq
sleep 2
sudo systemctl start hostapd

# =============================================================================
# INSTALLATION COMPLETE
# =============================================================================
echo
echo "================================================"
echo "         INSTALLATION COMPLETED!"
echo "================================================"
echo
echo "Configuration Summary:"
echo "  • Bridge IP: 10.0.0.1"
echo "  • DHCP Range: 10.0.0.50 - 10.0.0.254"
echo "  • WiFi SSID: RaspAP-Bridge"
echo "  • WiFi Password: ChangeMe"
echo "  • Internet via: USB port (eth1)"
echo "  • Web Interface: http://10.0.0.1"
echo
echo "Network Layout:"
echo "  Internet → USB(eth1) → Pi → Bridge(br0) → eth0 + wlan0"
echo "  All devices on eth0 and wlan0 share the 10.0.0.x subnet"
echo
echo "Management Commands:"
echo "  • Check status: raspap-bridge-status"
echo "  • Restart services: raspap-bridge-restart"
echo "  • Web interface: http://10.0.0.1 (admin/secret)"
echo
echo "Next Steps:"
echo "1. Connect internet source to USB port"
echo "2. Connect devices to eth0 or WiFi 'RaspAP-Bridge'"
echo "3. Change WiFi password via web interface"
echo "4. Test connectivity between all devices"
echo
echo "REBOOT RECOMMENDED to ensure all services start properly!"
echo "After reboot, run: raspap-bridge-status"
echo
read -p "Press Enter to continue..."
