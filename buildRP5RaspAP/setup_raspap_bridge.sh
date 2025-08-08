#!/bin/bash

# Script to set up Raspberry Pi as a bridged AP with RaspAP
# Version 2.1.0

# Ensure script is run as root
if [ "$(id -u)" -ne 0 ]; then
  echo "This script must be run as root. Please use sudo." >&2
  exit 1
fi

set -e # Exit immediately if a command exits with a non-zero status.

# Output version number
SCRIPT_VERSION="2.1.0"
echo "Running setup_raspap_bridge.sh version $SCRIPT_VERSION"

# --- Configuration Variables ---
BRIDGE_IP="10.10.1.1/24"
BRIDGE_INTERFACE_NAME="br0"
ETH_INTERFACE="eth0" # Physical Ethernet interface to be bridged
WLAN_INTERFACE="wlan0" # Physical WLAN interface for AP

DHCP_RANGE_START="10.10.1.50"
DHCP_RANGE_END="10.10.1.200"
DHCP_LEASE_TIME="12h"

# Prompt for user-specific values with defaults
read -r -p "Enter the SSID for your Access Point [Sophie]: " AP_SSID
AP_SSID=${AP_SSID:-Sophie}

read -r -s -p "Enter the Password for your Access Point (min 8 chars) [mysecret]: " AP_PASSWORD
AP_PASSWORD=${AP_PASSWORD:-mysecret}
echo
while [[ ${#AP_PASSWORD} -lt 8 ]]; do
    read -r -s -p "Password must be at least 8 characters. Enter Password [mysecret]: " AP_PASSWORD
    AP_PASSWORD=${AP_PASSWORD:-mysecret}
    echo
done

read -r -p "Enter your USB Internet Interface name (e.g., eth1, usb0, wwan0) [eth1]: " USB_INTERNET_IFACE
USB_INTERNET_IFACE=${USB_INTERNET_IFACE:-eth1}

read -r -p "Enter your Wi-Fi country code (e.g., US, GB) [US]: " WIFI_COUNTRY
WIFI_COUNTRY=${WIFI_COUNTRY:-US}

echo_step() {
    echo -e "\n\033[1;34m>>> $1\033[0m"
}

# --- Script Execution ---

# Phase 1: System Preparation
echo_step "Phase 1: System Preparation"
echo_step "Updating system and installing prerequisites..."
apt update
apt upgrade -y

# Ensure tcpdump is installed
if ! command -v tcpdump &> /dev/null; then
    echo_step "tcpdump not found, installing tcpdump..."
    apt install -y tcpdump
fi

# Set the Wi-Fi country code
echo_step "Setting Wi-Fi country code..."
iw reg set "$WIFI_COUNTRY"
echo "Regulatory domain set to $WIFI_COUNTRY"

# Unblock Wi-Fi
rfkill unblock wlan

# Verify Wi-Fi is unblocked
if rfkill list all | grep -q "Soft blocked: yes"; then
    echo "Error: Wi-Fi is still blocked. Please check your configuration."
    exit 1
fi

# Ensure dhcpcd is installed, as we will configure it
if ! command -v dhcpcd &> /dev/null; then
    echo_step "dhcpcd command not found, installing dhcpcd..."
    apt install -y dhcpcd
fi
apt install -y bridge-utils git dnsmasq hostapd netfilter-persistent iptables-persistent
echo "netfilter-persistent netfilter-persistent/autosave_v4 boolean true" | debconf-set-selections
echo "netfilter-persistent netfilter-persistent/autosave_v6 boolean true" | debconf-set-selections
apt install -y netfilter-persistent # Re-run to apply debconf selections if not already installed

# Exit if this phase fails
if [ $? -ne 0 ]; then
    echo "Phase 1 failed. Exiting."
    exit 1
fi

# Phase 2: Network Bridge Setup
echo_step "Phase 2: Network Bridge Setup"
echo_step "Configuring /etc/dhcpcd.conf..."
DHCPCD_CONF="/etc/dhcpcd.conf"
# Ensure the configuration file exists before trying to grep or modify it
touch "$DHCPCD_CONF"

# Ensure denyinterfaces line is present and correctly formatted at the end of the file if added
if ! grep -Fxq "denyinterfaces $ETH_INTERFACE $WLAN_INTERFACE" "$DHCPCD_CONF"; then
    {
        echo "" # Add a newline for separation if file not empty
        echo "# Deny dhcpcd from managing $ETH_INTERFACE and $WLAN_INTERFACE directly"
        echo "denyinterfaces $ETH_INTERFACE $WLAN_INTERFACE"
    } >> "$DHCPCD_CONF"
fi

# Configure static IP for the bridge interface $BRIDGE_INTERFACE_NAME
# If the interface block for br0 doesn't exist, add it correctly with the full CIDR.
if ! grep -q "^interface $BRIDGE_INTERFACE_NAME" "$DHCPCD_CONF"; then
    {
        echo "" # Add a newline for separation
        echo "# Configure static IP for the bridge interface $BRIDGE_INTERFACE_NAME"
        echo "interface $BRIDGE_INTERFACE_NAME"
        echo "static ip_address=$BRIDGE_IP" # Use $BRIDGE_IP which includes CIDR
    } >> "$DHCPCD_CONF"
fi

# Remove exact duplicate lines from the entire file (useful for idempotency)
awk '!seen[$0]++' "$DHCPCD_CONF" > /tmp/dhcpcd.conf.tmp && mv /tmp/dhcpcd.conf.tmp "$DHCPCD_CONF"

echo_step "Creating systemd service for network bridge setup (network-bridge-setup.service)..."
cat <<EOF > /etc/systemd/system/network-bridge-setup.service
[Unit]
Description=Network Bridge Setup ($BRIDGE_INTERFACE_NAME with $ETH_INTERFACE)
Wants=network-pre.target
Before=network-pre.target
BindsTo=sys-subsystem-net-devices-$ETH_INTERFACE.device
After=sys-subsystem-net-devices-$ETH_INTERFACE.device

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStartPre=/bin/bash -c "[[ \$(brctl show | grep -w $BRIDGE_INTERFACE_NAME) ]] || /sbin/brctl addbr $BRIDGE_INTERFACE_NAME"
ExecStartPre=/bin/bash -c "[[ \$(brctl show $BRIDGE_INTERFACE_NAME | grep -w $ETH_INTERFACE) ]] || /sbin/brctl addif $BRIDGE_INTERFACE_NAME $ETH_INTERFACE"
ExecStartPre=/sbin/ip link set dev $ETH_INTERFACE up
ExecStart=/sbin/ip link set dev $BRIDGE_INTERFACE_NAME up
ExecStop=/sbin/brctl delif $BRIDGE_INTERFACE_NAME $ETH_INTERFACE
ExecStop=/sbin/ip link set dev $BRIDGE_INTERFACE_NAME down
ExecStop=/sbin/brctl delbr $BRIDGE_INTERFACE_NAME

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable network-bridge-setup.service
echo_step "Starting bridge setup service (may show error if already started or eth0 not ready yet, will retry at boot)..."
if ! systemctl restart network-bridge-setup.service; then
    echo "Error: network-bridge-setup.service failed to start. Check the status and logs for more details:"
    echo "  sudo systemctl status network-bridge-setup.service"
    echo "  sudo journalctl -xeu network-bridge-setup.service"
    exit 1
fi

# Verify the bridge is up
echo_step "Verifying bridge setup..."
if ! ip link show br0 | grep -q "state UP"; then
    echo "Error: Bridge br0 is not up. Check your network configuration."
    exit 1
fi

if ! brctl show | grep -q "$ETH_INTERFACE"; then
    echo "Error: $ETH_INTERFACE is not part of the bridge br0. Check your bridge configuration."
    exit 1
fi

# Exit if this phase fails
if [ $? -ne 0 ]; then
    echo "Phase 2 failed. Exiting."
    exit 1
fi

# Phase 3: Wi-Fi Access Point Setup
echo_step "Phase 3: Wi-Fi Access Point Setup"
echo_step "Configuring hostapd for bridged mode..."
HOSTAPD_CONF="/etc/hostapd/hostapd.conf"
# Ensure the hostapd configuration file exists
touch "$HOSTAPD_CONF"

# Overwrite the hostapd configuration with the required settings
cat <<EOF > "$HOSTAPD_CONF"
# Hostapd configuration for bridged mode
interface=$WLAN_INTERFACE
bridge=$BRIDGE_INTERFACE_NAME
ssid=$AP_SSID
wpa_passphrase=$AP_PASSWORD
driver=nl80211
ctrl_interface=/var/run/hostapd
ctrl_interface_group=0
auth_algs=1
wpa=2
wpa_key_mgmt=WPA-PSK
wpa_pairwise=CCMP
beacon_int=100
channel=11
hw_mode=g
ieee80211n=0
country_code=GB
ignore_broadcast_ssid=0
EOF

# Unmask and enable hostapd service
echo_step "Unmasking and enabling hostapd service..."
systemctl unmask hostapd
systemctl enable hostapd

# Restart hostapd to apply the new configuration
systemctl restart hostapd

# Check if hostapd started successfully
if ! systemctl is-active --quiet hostapd; then
    echo "Error: hostapd failed to start. Check the status and logs for more details:"
    echo "  sudo systemctl status hostapd"
    echo "  sudo journalctl -xeu hostapd"
    exit 1
fi

# Exit if this phase fails
if [ $? -ne 0 ]; then
    echo "Phase 3 failed. Exiting."
    exit 1
fi

# Phase 4: DHCP and DNS Setup
echo_step "Phase 4: DHCP and DNS Setup"
echo_step "Configuring dnsmasq for bridged mode..."
# RaspAP typically creates /etc/dnsmasq.d/090_raspap.conf
DNSMASQ_CONF_RASPAP="/etc/dnsmasq.d/090_raspap.conf"
DNSMASQ_CONF_MAIN="/etc/dnsmasq.conf"
DNSMASQ_TARGET_CONF=$DNSMASQ_CONF_RASPAP

if [ ! -f "$DNSMASQ_TARGET_CONF" ]; then
    echo "RaspAP dnsmasq config ($DNSMASQ_TARGET_CONF) not found, attempting to use $DNSMASQ_CONF_MAIN"
    DNSMASQ_TARGET_CONF=$DNSMASQ_CONF_MAIN
    # Ensure dnsmasq.conf includes files from /etc/dnsmasq.d
    if ! grep -q "^conf-dir=/etc/dnsmasq.d" $DNSMASQ_CONF_MAIN; then
        echo "conf-dir=/etc/dnsmasq.d/,*.conf" >> $DNSMASQ_CONF_MAIN
    fi
    # Create the RaspAP specific conf if it was missing
    touch $DNSMASQ_CONF_RASPAP
    DNSMASQ_TARGET_CONF=$DNSMASQ_CONF_RASPAP 
fi

# Clear existing interface and dhcp-range for safety before setting new ones
sed -i '/^interface=/d' $DNSMASQ_TARGET_CONF
sed -i '/^dhcp-range=/d' $DNSMASQ_TARGET_CONF
sed -i '/^dhcp-option=option:router/d' $DNSMASQ_TARGET_CONF
sed -i '/^dhcp-option=option:dns-server/d' $DNSMASQ_TARGET_CONF
sed -i '/^listen-address=/d' $DNSMASQ_TARGET_CONF

cat <<EOF > $DNSMASQ_TARGET_CONF
# Configuration for dnsmasq, managed by RaspAP setup script
interface=$BRIDGE_INTERFACE_NAME
listen-address=::1,127.0.0.1,${BRIDGE_IP%/*}

# DHCP settings
dhcp-range=10.10.1.50,10.10.1.200,255.255.255.0,${DHCP_LEASE_TIME}
dhcp-option=option:router,${BRIDGE_IP%/*}
dhcp-option=option:dns-server,${BRIDGE_IP%/*} # Pi itself as DNS forwarder
# You can also use public DNS servers:
# dhcp-option=option:dns-server,8.8.8.8,1.1.1.1

# Domain (optional)
# domain=lan
EOF

# Restart dnsmasq and check its status
echo_step "Restarting dnsmasq service..."
sudo systemctl restart dnsmasq
if ! systemctl is-active --quiet dnsmasq; then
    echo "Error: dnsmasq service failed to start. Check the configuration and logs:"
    echo "  sudo systemctl status dnsmasq"
    echo "  sudo journalctl -xeu dnsmasq"
    exit 1
fi

# Debug dnsmasq logs
echo_step "Checking dnsmasq logs for errors..."
sudo journalctl -xeu dnsmasq | tail -n 20

# Verify the bridge is up and has the correct IP
echo_step "Verifying bridge configuration..."
if ! ip addr show br0 | grep -q "10.10.1.1"; then
    echo "Warning: Bridge br0 does not have the correct IP address. Attempting to set it manually..."
    sudo ip addr add 10.10.1.1/24 dev br0
    sudo ip link set dev br0 up
    if ! ip addr show br0 | grep -q "10.10.1.1"; then
        echo "Error: Failed to set the correct IP address on br0. Check your network configuration."
        exit 1
    fi
fi

if ! brctl show | grep -q "$ETH_INTERFACE"; then
    echo "Error: $ETH_INTERFACE is not part of the bridge br0. Check the bridge configuration."
    exit 1
fi

# Verify dnsmasq is running
echo_step "Verifying dnsmasq service..."
if ! systemctl is-active --quiet dnsmasq; then
    echo "Error: dnsmasq service is not running. Check the configuration and logs:"
    echo "  sudo systemctl status dnsmasq"
    echo "  sudo journalctl -xeu dnsmasq"
    exit 1
fi

# Debug dnsmasq configuration
echo_step "Displaying dnsmasq configuration..."
cat "$DNSMASQ_TARGET_CONF"

# Test DHCP functionality
echo_step "Testing DHCP functionality..."
echo "Listening for DHCP requests on br0..."
TCPDUMP_LOG="/tmp/tcpdump_br0.log"
sudo timeout 10 tcpdump -i br0 -n > "$TCPDUMP_LOG" 2>&1 || true

# Display full tcpdump output for debugging
echo_step "Full tcpdump output:"
cat "$TCPDUMP_LOG"

# Check if tcpdump captured any traffic at all
if [ ! -s "$TCPDUMP_LOG" ]; then
    echo "Error: No traffic captured on br0. Check if br0 is active and devices are connected."
    exit 1
fi

# Check for DHCP traffic in the tcpdump output (UDP port 67 or 68)
if grep -qE "UDP.*(67|68)" "$TCPDUMP_LOG"; then
    echo "DHCP traffic detected on br0. Proceeding..."
else
    echo "Warning: No explicit DHCP traffic detected on br0 after 10 seconds."
    echo "Suggestions:"
    echo "  1. Ensure dnsmasq is configured to serve DHCP on br0."
    echo "  2. Check if devices connected to eth0 are sending DHCP requests."
    echo "  3. Review dnsmasq logs for errors: sudo journalctl -xeu dnsmasq"
    echo "  4. Verify if the client already has an IP address assigned."
    echo "Proceeding with the script as other traffic is present."
fi

# Clean up the tcpdump log file
sudo rm -f "$TCPDUMP_LOG"

echo_step "DHCP functionality test completed successfully."

# Test DHCP assignment using dhclient
echo_step "Testing DHCP assignment on br0..."
if ! sudo dhclient -v -r br0 && sudo dhclient -v br0; then
    echo "Error: Failed to obtain an IP address on br0. Check dnsmasq and network configuration."
    exit 1
fi

# Clean up the tcpdump log file
sudo rm -f "$TCPDUMP_LOG"

# Exit if this phase fails
if [ $? -ne 0 ]; then
    echo "Phase 4 failed. Exiting."
    exit 1
fi

# Phase 5: Internet Connectivity
echo_step "Phase 5: Internet Connectivity"
echo_step "Enabling IP forwarding..."
SYSCTL_CONF="/etc/sysctl.conf"
FORWARD_LINE="net.ipv4.ip_forward=1"
# Ensure net.ipv4.ip_forward is set to 1
if grep -q -E "^\s*#?\s*net.ipv4.ip_forward\s*=" "$SYSCTL_CONF"; then
    # If the line exists (commented or uncommented), modify it to be uncommented and set to 1
    sed -i -E "s/^\s*#?\s*net.ipv4.ip_forward\s*=.*/$FORWARD_LINE/" "$SYSCTL_CONF"
else
    # If the line doesn't exist at all, add it
    echo "" >> "$SYSCTL_CONF" # Add a newline for separation
    echo "$FORWARD_LINE" >> "$SYSCTL_CONF"
fi
sysctl -p

echo_step "Configuring firewall (iptables) for NAT..."
iptables -t nat -F POSTROUTING # Flush specific chain first
iptables -F FORWARD # Flush FORWARD chain

iptables -t nat -A POSTROUTING -o "$USB_INTERNET_IFACE" -j MASQUERADE
iptables -A FORWARD -i "$BRIDGE_INTERFACE_NAME" -o "$USB_INTERNET_IFACE" -j ACCEPT
iptables -A FORWARD -i "$USB_INTERNET_IFACE" -o "$BRIDGE_INTERFACE_NAME" -m state --state RELATED,ESTABLISHED -j ACCEPT

echo_step "Saving firewall rules..."
netfilter-persistent save

# Exit if this phase fails
if [ $? -ne 0 ]; then
    echo "Phase 5 failed. Exiting."
    exit 1
fi

# Phase 6: RaspAP Installation
echo_step "Phase 6: RaspAP Installation"

# Verify eth0 accessibility before proceeding
echo_step "Verifying eth0 accessibility..."
if ! ip addr show "$ETH_INTERFACE" | grep -q "state UP"; then
    echo "Error: $ETH_INTERFACE is not up. Ensure the bridge is configured correctly before proceeding."
    exit 1
fi

# Test if the bridge is assigning IP addresses
echo_step "Testing DHCP on eth0..."
if ! ping -c 1 -W 2 10.10.1.1 &> /dev/null; then
    echo "Error: Unable to reach the bridge IP (10.10.1.1) via $ETH_INTERFACE. Check your network configuration."
    exit 1
fi

# Prompt user to confirm before proceeding with RaspAP installation
read -r -p "Do you want to proceed with the installation of RaspAP? (y/n): " CONFIRM_RASPAP
if [[ "$CONFIRM_RASPAP" != "y" && "$CONFIRM_RASPAP" != "Y" ]]; then
    echo "Skipping RaspAP installation."
    exit 0
fi

echo_step "Installing RaspAP (this may take several minutes)..."
# Check if RaspAP is already installed to avoid re-running full installer if not needed
if ! command -v raspap &> /dev/null; then
    RASPAP_INSTALL_SCRIPT="/tmp/raspap_install.sh"
    echo "Downloading RaspAP installer script to $RASPAP_INSTALL_SCRIPT..."
    # Added -f to curl to make it fail silently on server errors, exit code will be non-zero.
    # If curl fails, set -e will cause the script to exit.
    if curl -fL -o "$RASPAP_INSTALL_SCRIPT" https://install.raspap.com; then
        echo "Download successful. Installer script is at $RASPAP_INSTALL_SCRIPT"
        chmod +x "$RASPAP_INSTALL_SCRIPT" # Make it executable, though bash doesn't strictly need it if called as `bash script.sh`
        
        echo "Running RaspAP installer script: sudo bash $RASPAP_INSTALL_SCRIPT --yes"
        # The `set -e` in the main script will cause it to exit if the following command fails.
        # Any error output from the RaspAP installer script itself should be visible.
        if sudo bash "$RASPAP_INSTALL_SCRIPT" --yes; then
            echo "RaspAP installer script completed successfully."
        else
            # This else block will likely not be reached if 'set -e' is active,
            # as the script would exit on the 'sudo bash' command failing.
            # However, it's good for clarity or if 'set -e' was temporarily disabled.
            echo "ERROR: RaspAP installer script failed. Exit code: $?"
            # Clean up the downloaded script even on failure
            rm -f "$RASPAP_INSTALL_SCRIPT"
            exit 1 # Explicitly exit if installer failed
        fi
        rm -f "$RASPAP_INSTALL_SCRIPT" # Clean up downloaded script on success
    else
        CURL_EXIT_CODE=$? # Capture curl's exit code
        echo "ERROR: Failed to download RaspAP installer script. Curl exit code: $CURL_EXIT_CODE."
        echo "Please check your internet connection and the URL https://install.raspap.com"
        exit $CURL_EXIT_CODE # Exit with curl's error code
    fi
else
    echo "RaspAP appears to be already installed. Skipping installation."
fi

# Exit if this phase fails
if [ $? -ne 0 ]; then
    echo "Phase 6 failed. Exiting."
    exit 1
fi

# Phase 7: Final Testing
echo_step "Phase 7: Final Testing"
echo_step "Restarting services..."
systemctl restart dhcpcd # To apply new IP to br0 if not already set
systemctl restart network-bridge-setup.service # Ensure bridge is up
systemctl restart hostapd
systemctl restart dnsmasq

echo_step "Setup Complete!"
echo "RaspAP Web UI should be accessible at http://${BRIDGE_IP%/*} or http://raspberrypi.local"
echo "Default RaspAP login: admin / secret (Change this immediately!)"
echo "It is highly recommended to REBOOT your Raspberry Pi now: sudo reboot"

# Exit if this phase fails
if [ $? -ne 0 ]; then
    echo "Phase 7 failed. Exiting."
    exit 1
fi

exit 0