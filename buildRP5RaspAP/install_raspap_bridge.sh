#!/bin/bash

# RaspAP Bridge Mode Installation and Configuration Script
# This script installs RaspAP and configures it for bridge mode with proper networking

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
sudo apt install -y git curl wget dnsmasq hostapd bridge-utils iptables-persistent

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

# eth0 bridge member configuration
sudo tee /etc/systemd/network/raspap-br0-member-eth0.network << 'EOF'
[Match]
Name=eth0

[Network]
Bridge=br0
LinkLocalAddressing=no
ConfigureWithoutCarrier=yes
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
# STEP 7: Configure iptables for internet sharing
# =============================================================================
echo
echo "=== STEP 7: Configuring iptables for internet sharing via USB ==="

# Enable IP forwarding permanently
echo 'net.ipv4.ip_forward=1' | sudo tee -a /etc/sysctl.conf

# Configure iptables rules for internet sharing
sudo tee /etc/iptables/rules.v4 << 'EOF'
# Generated by iptables-save
*filter
:INPUT ACCEPT [0:0]
:FORWARD ACCEPT [0:0]
:OUTPUT ACCEPT [0:0]

# Allow loopback
-A INPUT -i lo -j ACCEPT

# Allow established and related connections
-A INPUT -m state --state RELATED,ESTABLISHED -j ACCEPT
-A FORWARD -m state --state RELATED,ESTABLISHED -j ACCEPT

# Allow traffic from bridge to internet (eth1)
-A FORWARD -i br0 -o eth1 -j ACCEPT

# Allow traffic between bridge members
-A FORWARD -i br0 -o br0 -j ACCEPT

# Allow SSH (be careful not to lock yourself out)
-A INPUT -p tcp --dport 22 -j ACCEPT

# Allow HTTP and HTTPS for RaspAP web interface
-A INPUT -p tcp --dport 80 -j ACCEPT
-A INPUT -p tcp --dport 443 -j ACCEPT

# Allow DNS and DHCP
-A INPUT -p udp --dport 53 -j ACCEPT
-A INPUT -p tcp --dport 53 -j ACCEPT
-A INPUT -p udp --dport 67 -j ACCEPT
-A INPUT -p udp --dport 68 -j ACCEPT

# Allow traffic from bridge network
-A INPUT -s 10.0.0.0/24 -j ACCEPT

COMMIT

*nat
:PREROUTING ACCEPT [0:0]
:INPUT ACCEPT [0:0]
:OUTPUT ACCEPT [0:0]
:POSTROUTING ACCEPT [0:0]

# Masquerade traffic going out via USB (eth1) - internet sharing
-A POSTROUTING -o eth1 -j MASQUERADE

COMMIT
EOF

# Load iptables rules
sudo iptables-restore < /etc/iptables/rules.v4

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
sudo systemctl enable iptables
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
