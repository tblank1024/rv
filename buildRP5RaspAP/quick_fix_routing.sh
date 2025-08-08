#!/bin/bash

# Quick fix for RaspAP routing between eth0 and wireless
# This addresses the most common issues preventing inter-interface communication

echo "=== Quick Fix for RaspAP Interface Routing ==="

# Check if running as root
if [ "$(id -u)" -ne 0 ]; then
  echo "Error: Run with sudo"
  exit 1
fi

echo "Applying quick fixes..."

# 1. Enable IP forwarding immediately and persistently
echo "1. Enabling IP forwarding..."
echo 1 > /proc/sys/net/ipv4/ip_forward
echo "net.ipv4.ip_forward=1" > /etc/sysctl.d/99-ip-forward.conf
sysctl -p /etc/sysctl.d/99-ip-forward.conf

# 2. Add iptables rules for inter-interface communication
echo "2. Adding iptables forwarding rules..."
iptables -A FORWARD -i eth0 -o wlan0 -j ACCEPT
iptables -A FORWARD -i wlan0 -o eth0 -j ACCEPT
iptables -A FORWARD -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT

# 3. Allow communication within 10.0.0.x subnet
echo "3. Adding subnet forwarding rules..."
iptables -A FORWARD -s 10.0.0.0/24 -d 10.0.0.0/24 -j ACCEPT

# 4. Save iptables rules
echo "4. Saving iptables rules..."
mkdir -p /etc/iptables
iptables-save > /etc/iptables/rules.v4

# 5. Install iptables-persistent to restore rules on boot
echo "5. Setting up persistent iptables..."
DEBIAN_FRONTEND=noninteractive apt-get install -y iptables-persistent

echo ""
echo "✅ Quick fix applied!"
echo ""
echo "Changes made:"
echo "- IP forwarding enabled"
echo "- Forward rules added for eth0 ↔ wlan0"
echo "- Subnet forwarding enabled for 10.0.0.x"
echo "- Rules saved for persistence"
echo ""
echo "Test by connecting devices to both interfaces and pinging between them."
echo "If issues persist, run: ./diagnose_routing.sh"
