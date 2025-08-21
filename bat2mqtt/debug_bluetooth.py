#!/usr/bin/env python3
# Debug script to test Bluetooth connection

import asyncio
import sys
from bleak import BleakClient, BleakScanner

DEV_MAC1 = 'F8:33:31:56:ED:16'
CHARACTERISTIC_UUID = '0000ffe1-0000-1000-8000-00805f9b34fb'
ADAPTER = "hci1"  # Force use of USB adapter

async def scan_devices():
    print(f"Scanning for BLE devices using adapter {ADAPTER}...")
    devices = await BleakScanner.discover(adapter=ADAPTER)
    for device in devices:
        print(f"Device: {device.name} - {device.address}")
        if device.address == DEV_MAC1:
            print(f"Found target device: {device.name}")
            return True
    return False

async def test_connection():
    print(f"Testing connection to {DEV_MAC1} using adapter {ADAPTER}")
    
    client = BleakClient(DEV_MAC1, adapter=ADAPTER)
    try:
        print("Attempting to connect...")
        await client.connect(timeout=30.0)  # Increased timeout
        print(f"Connected: {client.is_connected}")
        
        if client.is_connected:
            print("Getting services...")
            services = client.services  # Use property instead of method
            for service in services:
                print(f"Service: {service.uuid}")
                for char in service.characteristics:
                    print(f"  Characteristic: {char.uuid} - Properties: {char.properties}")
                    if char.uuid == CHARACTERISTIC_UUID:
                        print(f"  ✅ Found target characteristic: {char.uuid}")
                        
        await client.disconnect()
        print("Disconnected successfully")
        
    except Exception as e:
        print(f"Connection failed: {e}")
        return False
    
    return True

async def main():
    print("=== Bluetooth Debug Tool ===")
    
    # First scan for devices (optional, skip if device doesn't advertise)
    print("Scanning for BLE devices...")
    try:
        found = await scan_devices()
        if not found:
            print("Target device not found in scan (but this is okay if device doesn't advertise)")
    except Exception as e:
        print(f"Scan failed: {e}")
    
    # Then test connection directly 
    print("\nTesting direct connection...")
    success = await test_connection()
    if success:
        print("Success: Bluetooth connection test successful")
    else:
        print("Failed: Bluetooth connection test failed")

if __name__ == "__main__":
    asyncio.run(main())
