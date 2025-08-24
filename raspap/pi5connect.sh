#!/bin/bash

# pi5connect.sh - Configures internet uplink for RaspAP bridge
# This script finds active internet interfaces and configures routing

# Log everything for troubleshooting
exec >> /var/log/pi5connect.log 2>&1
echo "[$(date)] pi5connect.sh triggered with args: $@"

# List of possible USB/uplink interfaces (update as needed)
UPLINK_IFACES=("enx7cc2c643fc22" "usb0" "usb1" "eth1")

# Bridge interface for LAN
BRIDGE_IFACE="br0"
BRIDGE_IP="10.0.0.1/24"

echo "[$(date)] Configuring bridge $BRIDGE_IFACE with $BRIDGE_IP"

# Ensure bridge is up with correct IP
sudo ip link set $BRIDGE_IFACE up
if ! ip addr show $BRIDGE_IFACE | grep -q "10.0.0.1/24"; then
    sudo ip addr add $BRIDGE_IP dev $BRIDGE_IFACE
fi

# Find the first active uplink interface
ACTIVE_UPLINK=""
for iface in "${UPLINK_IFACES[@]}"; do
    if ip link show "$iface" 2>/dev/null | grep -q "state UP"; then
        # Check if it has an IP address
        if ip addr show "$iface" | grep -q "inet "; then
            ACTIVE_UPLINK="$iface"
            echo "[$(date)] Found active uplink interface: $ACTIVE_UPLINK"
            break
        fi
    fi
done

if [ -z "$ACTIVE_UPLINK" ]; then
    echo "[$(date)] No active uplink interface found."
    # Clear any existing default routes that might conflict
    sudo ip route del default 2>/dev/null || true
    echo "[$(date)] No internet uplink - bridge will work for local access only"
else
    echo "[$(date)] Using uplink interface: $ACTIVE_UPLINK"
    
    # Get the default gateway for the uplink interface
    UPLINK_GATEWAY=$(ip route show dev "$ACTIVE_UPLINK" | grep default | awk '{print $3}' | head -n1)
    
    if [ -n "$UPLINK_GATEWAY" ]; then
        echo "[$(date)] Found gateway: $UPLINK_GATEWAY via $ACTIVE_UPLINK"
        
        # Set up IP forwarding
        echo 1 | sudo tee /proc/sys/net/ipv4/ip_forward > /dev/null
        
        # Clear existing iptables rules for clean setup
        sudo iptables -t nat -F POSTROUTING 2>/dev/null || true
        sudo iptables -F FORWARD 2>/dev/null || true
        
        # Set up NAT for internet sharing
        sudo iptables -t nat -A POSTROUTING -o "$ACTIVE_UPLINK" -j MASQUERADE
        sudo iptables -A FORWARD -i "$BRIDGE_IFACE" -o "$ACTIVE_UPLINK" -j ACCEPT
        sudo iptables -A FORWARD -i "$ACTIVE_UPLINK" -o "$BRIDGE_IFACE" -m state --state RELATED,ESTABLISHED -j ACCEPT
        
        echo "[$(date)] NAT and forwarding rules configured for $ACTIVE_UPLINK"
    else
        echo "[$(date)] No gateway found for $ACTIVE_UPLINK"
    fi
fi

# Ensure DNS is working for bridge clients
if [ -f /etc/resolv.conf ]; then
    # Copy system DNS to dnsmasq if it's running
    if systemctl is-active --quiet dnsmasq; then
        echo "[$(date)] dnsmasq is running - DNS should be handled automatically"
    fi
fi

echo "[$(date)] pi5connect.sh configuration complete"
