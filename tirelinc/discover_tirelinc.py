#!/usr/bin/env python3
"""
TireLinc Discovery Tool
Discovers services and characteristics of TireLinc device
"""

import asyncio
from bleak import BleakClient, BleakScanner

TIRELINC_MAC = 'F4:CF:A2:85:D0:62'

async def discover_device():
    """First, let's see if we can discover the device and its details"""
    print("Scanning for TireLinc device...")
    
    devices = await BleakScanner.discover(timeout=10.0)
    tirelinc_device = None
    
    for device in devices:
        print(f"Found device: {device.address} - {device.name}")
        if device.address.upper() == TIRELINC_MAC.upper():
            tirelinc_device = device
            print(f"*** Found TireLinc: {device.name} at {device.address}")
            break
    
    if not tirelinc_device:
        print(f"TireLinc device {TIRELINC_MAC} not found in scan")
        return False
    
    return True

async def explore_services():
    """Try to connect and explore available services"""
    print(f"\nAttempting to connect to TireLinc {TIRELINC_MAC}...")
    
    async with BleakClient(TIRELINC_MAC) as client:
        if not client.is_connected:
            print("Failed to connect")
            return
        
        print("Connected! Exploring services...")
        
        services = await client.get_services()
        
        for service in services:
            print(f"\nService: {service.uuid}")
            print(f"  Description: {service.description}")
            
            for char in service.characteristics:
                print(f"    Characteristic: {char.uuid}")
                print(f"      Properties: {char.properties}")
                print(f"      Description: {char.description}")
                
                # Try to read if readable
                if "read" in char.properties:
                    try:
                        value = await client.read_gatt_char(char.uuid)
                        print(f"      Value: {value.hex() if value else 'None'}")
                    except Exception as e:
                        print(f"      Read error: {e}")
                
                # Check for descriptors
                for desc in char.descriptors:
                    print(f"        Descriptor: {desc.uuid}")

async def try_simple_read():
    """Try to read from common GATT characteristics"""
    print(f"\nTrying simple reads from {TIRELINC_MAC}...")
    
    # Common GATT characteristics to try
    common_chars = [
        "00002a00-0000-1000-8000-00805f9b34fb",  # Device Name
        "00002a01-0000-1000-8000-00805f9b34fb",  # Appearance  
        "00002a04-0000-1000-8000-00805f9b34fb",  # Peripheral Preferred Connection Parameters
        "00002a05-0000-1000-8000-00805f9b34fb",  # Service Changed
        "0000180a-0000-1000-8000-00805f9b34fb",  # Device Information Service
        "0000ffe0-0000-1000-8000-00805f9b34fb",  # Common custom service
        "0000ffe1-0000-1000-8000-00805f9b34fb",  # Common custom characteristic
    ]
    
    try:
        async with BleakClient(TIRELINC_MAC) as client:
            if not client.is_connected:
                print("Failed to connect")
                return
            
            print("Connected! Trying to read common characteristics...")
            
            for char_uuid in common_chars:
                try:
                    value = await client.read_gatt_char(char_uuid)
                    print(f"  {char_uuid}: {value.hex() if value else 'None'}")
                    if value:
                        try:
                            decoded = value.decode('utf-8')
                            print(f"    Decoded: {decoded}")
                        except:
                            pass
                except Exception as e:
                    print(f"  {char_uuid}: Error - {e}")
                    
    except Exception as e:
        print(f"Connection failed: {e}")

async def main():
    """Main function"""
    print("TireLinc Discovery Tool")
    print("======================")
    
    # First check if device is discoverable
    found = await discover_device()
    if not found:
        return
    
    # Try to explore services (this will likely fail if device doesn't accept connections)
    try:
        await explore_services()
    except Exception as e:
        print(f"Service exploration failed: {e}")
        print("Device likely doesn't accept connections (broadcast-only)")
    
    # Try simple reads
    try:
        await try_simple_read()
    except Exception as e:
        print(f"Simple read failed: {e}")

if __name__ == "__main__":
    asyncio.run(main())
