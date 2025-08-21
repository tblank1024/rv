#!/bin/bash
# Bluetooth adapter configuration script
# This script ensures only the USB Bluetooth adapter is used

echo "=== Bluetooth Adapter Configuration ==="

# Show current status
echo "Current Bluetooth adapters:"
hciconfig

echo ""
echo "Current RF-kill status:"
rfkill list

echo ""
echo "Configuring adapters..."

# Disable built-in Pi adapter (hci0)
echo "Disabling built-in Pi adapter (hci0)..."
sudo hciconfig hci0 down

# Unblock and enable USB adapter (hci1)
echo "Enabling USB adapter (hci1)..."
sudo rfkill unblock bluetooth
sudo hciconfig hci1 up

echo ""
echo "Final configuration:"
hciconfig

echo ""
echo "Verification:"
if hciconfig hci1 | grep -q "UP RUNNING"; then
    echo "✅ USB adapter (hci1) is UP and RUNNING"
else
    echo "❌ USB adapter (hci1) is not running"
fi

if hciconfig hci0 | grep -q "DOWN"; then
    echo "✅ Built-in adapter (hci0) is DOWN"
else
    echo "❌ Built-in adapter (hci0) is still running"
fi

echo ""
echo "Configuration complete!"
