#!/usr/bin/env python3
"""
Full BLE Scanner - Show ALL advertisements from TireLinc device
"""

import asyncio
from datetime import datetime
from bleak import BleakScanner

# Target TireLinc MAC address
TIRELINC_MAC = 'F4:CF:A2:85:D0:62'

async def detection_callback(device, advertisement_data):
    """Callback function called when a BLE advertisement is detected"""
    # Check if this is our target device
    if device.address.upper() == TIRELINC_MAC.upper():
        current_time = datetime.now().strftime("%H:%M:%S")
        
        print(f"[{current_time}] Device: {device.name} ({device.address})")
        print(f"  RSSI: {advertisement_data.rssi}")
        print(f"  Local Name: {advertisement_data.local_name}")
        print(f"  Service UUIDs: {advertisement_data.service_uuids}")
        print(f"  Service Data: {advertisement_data.service_data}")
        
        # Show ALL manufacturer data
        if advertisement_data.manufacturer_data:
            for mfg_id, data in advertisement_data.manufacturer_data.items():
                hex_data = data.hex().upper()
                print(f"  MFG:{mfg_id:04X} HEX:{hex_data}")
        else:
            print("  No manufacturer data")
        
        print("---")

async def scan_for_all_tirelinc():
    """Continuously scan for ALL TireLinc advertisements"""
    print("Full TireLinc Scanner - All Advertisement Data")
    print(f"Scanning for device: {TIRELINC_MAC}")
    print()
    
    # Create scanner with callback
    scanner = BleakScanner(detection_callback)
    
    try:
        # Start scanning
        await scanner.start()
        
        # Keep scanning
        while True:
            await asyncio.sleep(1.0)
            
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        await scanner.stop()

if __name__ == "__main__":
    asyncio.run(scan_for_all_tirelinc())
