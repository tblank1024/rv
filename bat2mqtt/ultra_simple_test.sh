#!/bin/bash

# Ultra-Simple BLE Test - Focus on what works
echo "=== Ultra-Simple BLE Connection Test ==="
echo "Device: F8:33:31:56:ED:16"
echo "Adapter: hci1"
echo ""

start_time=$(date +%s)

cleanup() {
    echo "*** Test interrupted ***"
    sudo pkill -f "gatttool.*F8:33:31:56:ED:16" 2>/dev/null
    exit 130
}
trap cleanup SIGINT SIGTERM

echo "Testing BLE connection (8 seconds)..."
echo ""

# Just test the method that actually works reliably
timeout 8 sudo gatttool -i hci1 -b F8:33:31:56:ED:16 --char-write-req --handle=0x0013 --value=0100 --listen > /tmp/ble_test.txt 2>&1

# Count notifications
notifications=$(grep -c "Notification handle" /tmp/ble_test.txt 2>/dev/null || echo 0)

# Calculate runtime
end_time=$(date +%s)
runtime=$((end_time - start_time))

echo "=== Results ==="
if [ $notifications -gt 0 ]; then
    echo "✅ SUCCESS: Received $notifications notifications in 8 seconds"
    echo ""
    echo "Sample battery data:"
    grep "Notification handle" /tmp/ble_test.txt | head -2 | sed 's/^/  /'
    
    # Parse voltage if possible
    first_line=$(grep "Notification handle" /tmp/ble_test.txt | head -1)
    if [[ $first_line =~ value:\ ([0-9a-f\ ]+) ]]; then
        hex_data="${BASH_REMATCH[1]}"
        ascii_data=$(echo "$hex_data" | xxd -r -p 2>/dev/null || echo "")
        if [[ $ascii_data =~ ^([0-9]+), ]]; then
            voltage_raw="${BASH_REMATCH[1]}"
            voltage=$(echo "scale=2; $voltage_raw / 100" | bc 2>/dev/null || echo "$voltage_raw")
            echo "  → Battery voltage: ${voltage}V"
        fi
    fi
    
    result=0
else
    echo "❌ FAILED: No data received"
    echo ""
    echo "Troubleshooting info:"
    if grep -q "Connection refused\|Error\|Failed" /tmp/ble_test.txt; then
        echo "  Connection error detected"
    elif grep -q "Characteristic value was written" /tmp/ble_test.txt; then
        echo "  Connected but no notifications (check handle 0x0013)"
    else
        echo "  Unknown issue - check device is in range and powered"
    fi
    result=1
fi

echo ""
echo "Test completed in $runtime seconds"
echo ""
echo "💡 This is your production command:"
echo "   sudo gatttool -i hci1 -b F8:33:31:56:ED:16 --char-write-req --handle=0x0013 --value=0100 --listen"

# Optional: Show how to test interactive mode manually
if [ $result -eq 0 ]; then
    echo ""
    echo "🔧 To test interactive mode manually:"
    echo "   sudo gatttool -i hci1 -b F8:33:31:56:ED:16 -I"
    echo "   [LE]> connect"
    echo "   [LE]> char-write-req 0x0013 0100"
    echo "   [LE]> (wait for data, then Ctrl+C)"
fi

rm -f /tmp/ble_test.txt
exit $result
