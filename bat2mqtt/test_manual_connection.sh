#!/bin/bash

# Test manual gatttool connection exactly like our successful manual session
echo "=== Testing Manual gatttool Connection ==="
echo "Device: F8:33:31:56:ED:16"
echo "Adapter: hci1"
echo "Starting interactive session and trying connect..."

# Use expect to automate the interactive session
expect << 'EOF'
set timeout 30
spawn sudo gatttool -i hci1 -b F8:33:31:56:ED:16 -t random -I

expect "[F8:33:31:56:ED:16][LE]>"
send "connect\r"

expect {
    "Connection successful" {
        puts "*** CONNECTION SUCCESS ***"
        send "char-write-req 0x000b 0100\r"
        expect "[F8:33:31:56:ED:16][LE]>"
        puts "Notification enabled, listening for data..."
        sleep 10
        send "quit\r"
        exit 0
    }
    "Connection refused" {
        puts "*** CONNECTION REFUSED - Device not advertising ***"
        send "quit\r"
        exit 1
    }
    "Software caused connection abort" {
        puts "*** CONNECTION ABORT - Interference detected ***"
        send "quit\r"
        exit 1
    }
    timeout {
        puts "*** CONNECTION TIMEOUT ***"
        send "quit\r"
        exit 1
    }
}
EOF

echo "Connection test completed."
