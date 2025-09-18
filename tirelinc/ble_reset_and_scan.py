#!/usr/bin/env python3
"""
Comprehensive BLE Reset and Scanner
Addresses Pi Bluetooth stack issues with thorough reset procedure
"""

import subprocess
import time
import sys
import os

def run_command(cmd, timeout=10, ignore_errors=False):
    """Run a command with timeout and error handling"""
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        if not ignore_errors and result.returncode != 0:
            print(f"Command failed: {cmd}")
            print(f"Error: {result.stderr}")
        return result
    except subprocess.TimeoutExpired:
        print(f"Command timed out: {cmd}")
        return None
    except Exception as e:
        print(f"Command exception: {cmd} - {e}")
        return None

def comprehensive_ble_reset():
    """Perform a comprehensive BLE stack reset"""
    print("=== Starting Comprehensive BLE Reset ===")
    
    # 1. Kill all Bluetooth processes
    print("1. Killing Bluetooth processes...")
    run_command("sudo pkill -f bluetooth", ignore_errors=True)
    run_command("sudo pkill -f hci", ignore_errors=True)
    run_command("sudo pkill -f gatttool", ignore_errors=True)
    run_command("sudo pkill -f hcitool", ignore_errors=True)
    run_command("sudo pkill -f hcidump", ignore_errors=True)
    run_command("sudo pkill -f btmon", ignore_errors=True)
    time.sleep(2)
    
    # 2. Reset USB Bluetooth adapters (if USB)
    print("2. Resetting USB Bluetooth adapters...")
    run_command("sudo usb_reset_by_path.sh", ignore_errors=True)  # If available
    
    # 3. Unload and reload Bluetooth kernel modules
    print("3. Reloading Bluetooth kernel modules...")
    run_command("sudo modprobe -r btusb", ignore_errors=True)
    run_command("sudo modprobe -r btintel", ignore_errors=True)
    run_command("sudo modprobe -r bluetooth", ignore_errors=True)
    time.sleep(2)
    run_command("sudo modprobe bluetooth", ignore_errors=True)
    run_command("sudo modprobe btintel", ignore_errors=True)
    run_command("sudo modprobe btusb", ignore_errors=True)
    time.sleep(3)
    
    # 4. Restart Bluetooth service
    print("4. Restarting Bluetooth service...")
    run_command("sudo systemctl stop bluetooth", ignore_errors=True)
    time.sleep(2)
    run_command("sudo systemctl start bluetooth", ignore_errors=True)
    time.sleep(3)
    
    # 5. Reset both adapters individually
    print("5. Resetting HCI adapters...")
    run_command("sudo hciconfig hci0 down", ignore_errors=True)
    run_command("sudo hciconfig hci1 down", ignore_errors=True)
    time.sleep(2)
    run_command("sudo hciconfig hci0 reset", ignore_errors=True)
    run_command("sudo hciconfig hci1 reset", ignore_errors=True)
    time.sleep(2)
    run_command("sudo hciconfig hci0 up", ignore_errors=True)
    run_command("sudo hciconfig hci1 up", ignore_errors=True)
    time.sleep(3)
    
    # 6. Clear any stuck scanning states
    print("6. Clearing scanning states...")
    run_command("sudo hciconfig hci1 noscan", ignore_errors=True)
    run_command("sudo hciconfig hci1 piscan", ignore_errors=True)
    time.sleep(1)
    
    # 7. Verify adapters are working
    print("7. Verifying adapter status...")
    result = run_command("hciconfig")
    if result and result.stdout:
        print("Adapter status:")
        print(result.stdout)
    
    print("=== BLE Reset Complete ===\n")

def test_scan_with_hcitool():
    """Test scanning using hcitool"""
    print("Testing hcitool scan...")
    result = run_command("timeout 10s sudo hcitool -i hci1 lescan", timeout=15)
    if result and result.stdout:
        lines = result.stdout.strip().split('\n')
        devices = []
        for line in lines:
            if ':' in line and len(line.split()) >= 2:
                parts = line.split(None, 1)
                if len(parts) >= 2:
                    mac = parts[0]
                    name = parts[1] if len(parts) > 1 else "Unknown"
                    devices.append((mac, name))
        
        print(f"Found {len(devices)} devices with hcitool:")
        for mac, name in devices:
            print(f"  {mac} - {name}")
        return devices
    else:
        print("hcitool scan failed or no devices found")
        return []

def test_scan_with_bluetoothctl():
    """Test scanning using bluetoothctl"""
    print("Testing bluetoothctl scan...")
    
    # Start scan
    cmd = 'echo -e "select 08:BE:AC:35:8E:5E\\nscan on" | timeout 15s bluetoothctl'
    result = run_command(cmd, timeout=20)
    
    if result and result.stdout:
        lines = result.stdout.split('\n')
        devices = []
        for line in lines:
            if '[NEW]' in line and 'Device' in line:
                parts = line.split()
                if len(parts) >= 3:
                    mac = parts[2]
                    name = ' '.join(parts[3:]) if len(parts) > 3 else "Unknown"
                    devices.append((mac, name))
        
        print(f"Found {len(devices)} devices with bluetoothctl:")
        for mac, name in devices:
            print(f"  {mac} - {name}")
        return devices
    else:
        print("bluetoothctl scan failed or no devices found")
        return []

def test_tire_connections():
    """Test connections to known tire sensors"""
    tire_sensors = {
        "B4:10:7B:36:04:B9": "BR_out",
        "60:98:66:5F:51:B1": "BL_out", 
        "E7:C2:D1:F3:59:21": "FR",
        "C1:35:98:B8:BF:A3": "FL",
        "EF:A2:C1:A8:1D:E6": "BR_in",
        "F8:33:31:56:FB:8E": "BL_in"
    }
    
    print("Testing tire sensor connections...")
    connected = []
    
    for mac, name in tire_sensors.items():
        print(f"Testing {name} ({mac})...")
        result = run_command(f"timeout 8s sudo gatttool -i hci1 -b {mac} --primary", timeout=10)
        if result and result.returncode == 0 and result.stdout.strip():
            print(f"  OK {name} - Connected successfully")
            connected.append((mac, name))
        else:
            print(f"  FAIL {name} - Connection failed/timeout")
    
    print(f"\nSuccessfully connected to {len(connected)}/6 tire sensors:")
    for mac, name in connected:
        print(f"  {name}: {mac}")
    
    return connected

def main():
    """Main function"""
    if os.geteuid() != 0:
        print("ERROR: This script must be run as root")
        sys.exit(1)
    
    print("Comprehensive BLE Reset and Scanner for Pi")
    print("=" * 50)
    
    # Perform comprehensive reset
    comprehensive_ble_reset()
    
    # Test different scanning methods
    print("Testing scanning methods...")
    
    hcitool_devices = test_scan_with_hcitool()
    print()
    
    bluetoothctl_devices = test_scan_with_bluetoothctl()
    print()
    
    # Test tire sensor connections
    connected_tires = test_tire_connections()
    
    # Summary
    print("\n" + "=" * 50)
    print("SCAN RESULTS SUMMARY:")
    print(f"hcitool found: {len(hcitool_devices)} devices")
    print(f"bluetoothctl found: {len(bluetoothctl_devices)} devices") 
    print(f"Tire sensors connected: {len(connected_tires)}/6")
    
    if len(connected_tires) >= 4:
        print("GOOD - Most tire sensors accessible")
    elif len(connected_tires) >= 2:
        print("OK - Some tire sensors accessible")  
    else:
        print("POOR - Few/no tire sensors accessible")

if __name__ == "__main__":
    main()
