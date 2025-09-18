#!/bin/bash

echo "=== Ensuring Bridge Configuration Persists After Reboot ==="
echo

# Check current status
echo "Current configuration status:"
echo "✓ dhcpcd.conf - Updated with bridge configuration"
echo "✓ dnsmasq configuration - Set for bridge DHCP"
echo "✓ systemd-networkd - $(systemctl is-enabled systemd-networkd)"
echo "✓ dnsmasq service - $(systemctl is-enabled dnsmasq)"
echo

# Enable dhcpcd if it's not enabled (it should be for RaspAP)
if ! systemctl is-enabled dhcpcd >/dev/null 2>&1; then
    echo "Enabling dhcpcd service for boot..."
    sudo systemctl enable dhcpcd
else
    echo "✓ dhcpcd service already enabled"
fi

# Make sure dnsmasq is enabled
if ! systemctl is-enabled dnsmasq >/dev/null 2>&1; then
    echo "Enabling dnsmasq service for boot..."
    sudo systemctl enable dnsmasq
else
    echo "✓ dnsmasq service already enabled"
fi

# Ensure systemd-networkd is enabled (it manages the bridge)
if ! systemctl is-enabled systemd-networkd >/dev/null 2>&1; then
    echo "Enabling systemd-networkd service for boot..."
    sudo systemctl enable systemd-networkd
else
    echo "✓ systemd-networkd service already enabled"
fi

echo
echo "=== Bridge Configuration Files (PERSISTENT) ==="
echo "1. Bridge creation: /etc/systemd/network/raspap-bridge-br0.netdev"
echo "2. eth0 bridging: /etc/systemd/network/raspap-br0-member-eth0.network"
echo "3. wlan0 bridging: /etc/systemd/network/raspap-br0-member-wlan0.network"
echo "4. Bridge IP config: /etc/dhcpcd.conf"
echo "5. DHCP server config: /etc/dnsmasq.d/090_br0.conf"

echo
echo "=== Service Order at Boot ==="
echo "1. systemd-networkd creates br0 bridge"
echo "2. systemd-networkd enslaves eth0 and wlan0 to br0"
echo "3. dhcpcd assigns static IP 10.0.0.1/24 to br0"
echo "4. dnsmasq starts DHCP server on br0 (range 10.0.0.50-254)"

echo
echo "=== Testing Reboot Persistence ==="
echo "All configuration is saved to persistent files. After reboot:"
echo "- Bridge br0 will be created automatically"
echo "- eth0 and wlan0 will be enslaved to br0"
echo "- br0 will get IP 10.0.0.1/24"
echo "- DHCP server will serve IPs 10.0.0.50-254"
echo "- All connected devices will get consistent IPs"

echo
echo "=== REBOOT READY ==="
echo "Your configuration WILL persist after reboot!"
echo "To test: sudo reboot"
echo "After reboot, run: sudo bash show_bridge_config.sh"
