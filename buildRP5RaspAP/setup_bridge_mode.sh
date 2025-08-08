#!/bin/bash

# Script to set up a proper bridge between eth0 and wlan0
# This creates a true Layer 2 bridge for seamless communication

echo "=== Setting up Bridge Mode for eth0 and wlan0 ==="

# Check if running as root
if [ "$(id -u)" -ne 0 ]; then
  echo "Error: This script must be run with sudo." >&2
  exit 1
fi

# Configuration
BRIDGE_NAME="br0"
ETH_INTERFACE="eth0"
WIRELESS_INTERFACE="wlan0"
BRIDGE_IP="10.0.0.1"
BRIDGE_NETMASK="255.255.255.0"

echo "Creating bridge $BRIDGE_NAME with interfaces $ETH_INTERFACE and $WIRELESS_INTERFACE"

# 1. Install bridge utilities
echo "1. Installing bridge utilities..."
apt-get update -qq
apt-get install -y bridge-utils

# 2. Stop NetworkManager from managing these interfaces
echo "2. Configuring NetworkManager..."
cat > /etc/NetworkManager/conf.d/bridge-interfaces.conf << EOF
[keyfile]
unmanaged-devices=interface-name:$ETH_INTERFACE;interface-name:$WIRELESS_INTERFACE;interface-name:$BRIDGE_NAME
EOF

# 3. Create bridge interface
echo "3. Creating bridge interface..."
if ! ip link show $BRIDGE_NAME > /dev/null 2>&1; then
    brctl addbr $BRIDGE_NAME
    echo "   Bridge $BRIDGE_NAME created"
else
    echo "   Bridge $BRIDGE_NAME already exists"
fi

# 4. Add interfaces to bridge
echo "4. Adding interfaces to bridge..."

# Remove IP from eth0 if present
ip addr flush dev $ETH_INTERFACE 2>/dev/null || true

# Add eth0 to bridge
if ! brctl show $BRIDGE_NAME | grep -q $ETH_INTERFACE; then
    brctl addif $BRIDGE_NAME $ETH_INTERFACE
    echo "   Added $ETH_INTERFACE to bridge"
fi

# For wireless, we need to ensure hostapd is configured for bridge mode
# This is handled by RaspAP, but we'll verify the configuration

# 5. Configure bridge IP
echo "5. Configuring bridge IP address..."
ip addr add $BRIDGE_IP/$BRIDGE_NETMASK dev $BRIDGE_NAME 2>/dev/null || true

# 6. Bring up interfaces
echo "6. Bringing up interfaces..."
ip link set dev $ETH_INTERFACE up
ip link set dev $WIRELESS_INTERFACE up
ip link set dev $BRIDGE_NAME up

# 7. Configure hostapd for bridge mode (modify RaspAP configuration)
echo "7. Updating hostapd configuration for bridge mode..."
HOSTAPD_CONF="/etc/hostapd/hostapd.conf"
if [ -f "$HOSTAPD_CONF" ]; then
    # Backup original
    cp "$HOSTAPD_CONF" "$HOSTAPD_CONF.backup"
    
    # Add bridge directive if not present
    if ! grep -q "^bridge=" "$HOSTAPD_CONF"; then
        echo "bridge=$BRIDGE_NAME" >> "$HOSTAPD_CONF"
        echo "   Added bridge directive to hostapd.conf"
    fi
else
    echo "   Warning: hostapd.conf not found at $HOSTAPD_CONF"
fi

# 8. Update dnsmasq configuration for bridge
echo "8. Updating dnsmasq configuration..."
DNSMASQ_CONF="/etc/dnsmasq.conf"
if [ -f "$DNSMASQ_CONF" ]; then
    # Backup original
    cp "$DNSMASQ_CONF" "$DNSMASQ_CONF.backup"
    
    # Update interface directive
    sed -i "s/^interface=.*/interface=$BRIDGE_NAME/" "$DNSMASQ_CONF"
    echo "   Updated dnsmasq to use bridge interface"
fi

# 9. Create systemd service for bridge setup
echo "9. Creating bridge setup service..."
cat > /etc/systemd/system/setup-bridge.service << EOF
[Unit]
Description=Setup network bridge
After=network.target

[Service]
Type=oneshot
ExecStart=/bin/bash -c '
    brctl addbr $BRIDGE_NAME 2>/dev/null || true
    ip addr flush dev $ETH_INTERFACE 2>/dev/null || true
    brctl addif $BRIDGE_NAME $ETH_INTERFACE 2>/dev/null || true
    ip addr add $BRIDGE_IP/$BRIDGE_NETMASK dev $BRIDGE_NAME 2>/dev/null || true
    ip link set dev $ETH_INTERFACE up
    ip link set dev $BRIDGE_NAME up
'
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable setup-bridge.service

echo ""
echo "=== Bridge Configuration Complete ==="
echo "Bridge: $BRIDGE_NAME"
echo "Bridge IP: $BRIDGE_IP"
echo "Interfaces: $ETH_INTERFACE (added), $WIRELESS_INTERFACE (via hostapd)"
echo ""
echo "Next steps:"
echo "1. Restart hostapd: sudo systemctl restart hostapd"
echo "2. Restart dnsmasq: sudo systemctl restart dnsmasq"
echo "3. Reboot to ensure all services start correctly"
echo ""
echo "To verify bridge status: brctl show"
echo "To check bridge addresses: ip addr show $BRIDGE_NAME"
