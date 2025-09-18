#!/bin/bash
# Script to ensure br0 bridge is properly configured with 10.0.0.1 IP
# This should be run on boot or when network interfaces come up

LOG_FILE="/var/log/bridge-setup.log"

echo "[$(date)] Setting up bridge br0 with 10.0.0.1 IP" >> "$LOG_FILE"

# Bring up the bridge interface
/usr/bin/ip link set br0 up

# Check if IP is already assigned
if ! /usr/bin/ip addr show br0 | grep -q "10.0.0.1/24"; then
    echo "[$(date)] Assigning 10.0.0.1/24 to br0" >> "$LOG_FILE"
    /usr/bin/ip addr add 10.0.0.1/24 dev br0
else
    echo "[$(date)] 10.0.0.1/24 already assigned to br0" >> "$LOG_FILE"
fi

# Ensure iptables forwarding is enabled for the bridge
echo 1 > /proc/sys/net/ipv4/ip_forward

# Configure custom DNS entries for dnsmasq
DNSMASQ_CONFIG="/etc/dnsmasq.d/090_br0.conf"
if [ -f "$DNSMASQ_CONFIG" ]; then
    # Check if custom DNS entries already exist
    if ! grep -q "address=/sophie/10.0.0.1" "$DNSMASQ_CONFIG"; then
        echo "[$(date)] Adding custom DNS entries to dnsmasq" >> "$LOG_FILE"
        echo "" >> "$DNSMASQ_CONFIG"
        echo "# Custom DNS entries" >> "$DNSMASQ_CONFIG"
        echo "address=/sophie/10.0.0.1" >> "$DNSMASQ_CONFIG"
        echo "address=/www.sophie/10.0.0.1" >> "$DNSMASQ_CONFIG"
        
        # Restart dnsmasq to apply changes
        if systemctl is-active --quiet dnsmasq; then
            systemctl restart dnsmasq
            echo "[$(date)] dnsmasq restarted with new DNS entries" >> "$LOG_FILE"
        fi
    else
        echo "[$(date)] Custom DNS entries already exist in dnsmasq config" >> "$LOG_FILE"
    fi
else
    echo "[$(date)] Warning: dnsmasq config file not found at $DNSMASQ_CONFIG" >> "$LOG_FILE"
fi

echo "[$(date)] Bridge setup complete" >> "$LOG_FILE"
