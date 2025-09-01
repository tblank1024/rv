#!/bin/bash
# TireLinc Raw Data Capture using hcidump
# This captures raw advertising packets and filters for TireLinc

echo "TireLinc Raw BLE Advertising Capture"
echo "===================================="
echo "Capturing advertising data from TireLinc device: F4:CF:A2:85:D0:62"
echo "Press Ctrl+C to stop"
echo ""

# Start background scanning
sudo hcitool -i hci0 lescan --duplicates > /dev/null 2>&1 &
SCAN_PID=$!

# Give scan time to start
sleep 2

# Capture and filter for TireLinc MAC address
sudo hcidump -i hci0 -R | grep -A 20 -B 5 -i "F4:CF:A2:85:D0:62\|TireLinc"

# Cleanup on exit
trap "kill $SCAN_PID 2>/dev/null" EXIT
