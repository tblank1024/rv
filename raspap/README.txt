# RaspAP Bridge Configuration

This directory contains configuration files for setting up a network bridge that:
1. Bridges eth0 and wlan0 together via br0 bridge interface
2. Provides internet connectivity through USB/uplink interfaces
3. Enables WiFi hotspot with internet sharing

## Essential Files (Keep These):

### Core Scripts:
- **pi5connect.sh** - Main script that finds active internet interfaces and configures NAT/routing
- **99-pi5connect** - NetworkManager dispatcher script that triggers pi5connect.sh when interfaces change
- **setup-bridge.sh** - Bridge setup script that ensures br0 has correct IP (10.0.0.1/24)

### Configuration Files:
- **bridge-setup.service** - Systemd service for automatic bridge setup on boot
- **raspap-bridge-br0.network** - systemd-networkd configuration for br0 bridge (10.0.0.1/24)
- **raspap-br0-member-wlan0.network** - Configuration to add wlan0 to br0 bridge

## Installation:

1. Copy 99-pi5connect to NetworkManager dispatcher directory:
   ```bash
   sudo cp 99-pi5connect /etc/NetworkManager/dispatcher.d/
   sudo chmod +x /etc/NetworkManager/dispatcher.d/99-pi5connect
   ```

2. Install systemd service for bridge setup:
   ```bash
   sudo cp bridge-setup.service /etc/systemd/system/
   sudo systemctl enable bridge-setup.service
   ```

3. Install systemd-networkd configurations:
   ```bash
   sudo cp raspap-*.network /etc/systemd/network/
   sudo systemctl enable systemd-networkd
   ```

## How It Works:

1. **Bridge Setup**: br0 bridge is created with IP 10.0.0.1/24
2. **Interface Detection**: pi5connect.sh automatically detects active USB/ethernet uplink interfaces
3. **NAT Configuration**: Sets up iptables rules for internet sharing from uplink to bridge
4. **Auto-Triggering**: NetworkManager dispatcher runs pi5connect.sh when interfaces change state

## Network Layout:
- Bridge (br0): 10.0.0.1/24 - Access point and gateway
- WiFi clients connect to wlan0 → bridged to br0
- Internet via USB/ethernet interfaces (eth1, usb0, etc.) → NAT to br0
