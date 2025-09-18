#!/usr/bin/env python3
"""
Simple TireLinc Raw Data Output
Just prints hex and ASCII values for each payload
"""

import asyncio
import time
from datetime import datetime
from bleak import BleakScanner

# Target TireLinc MAC address
TIRELINC_MAC = 'F4:CF:A2:85:D0:62'

async def detection_callback(device, advertisement_data):
    """Callback function called when a BLE advertisement is detected"""
    # Check if this is our target device
    if device.address.upper() == TIRELINC_MAC.upper():
        current_time = datetime.now().strftime("%H:%M:%S")
        
        # Check manufacturer data
        if advertisement_data.manufacturer_data:
            for mfg_id, data in advertisement_data.manufacturer_data.items():
                # Only show MFG:004C data (commented out MFG:05C7 as requested)
                if mfg_id == 0x004C:  # Apple iBeacon format
                    hex_data = data.hex().upper()
                    print(f"[{current_time}] HEX:{hex_data}")
                # elif mfg_id == 0x05C7:  # Status data - commented out but kept in codebase
                #     hex_data = data.hex().upper()
                #     print(f"[{current_time}] MFG:{mfg_id:04X} HEX:{hex_data}")

async def scan_for_tirelinc():
    """Continuously scan for TireLinc advertisements"""
    print("TireLinc Simplified Raw Data Output")
    print("Format: [TIME] HEX:...")
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
    try:
        asyncio.run(scan_for_tirelinc())
    except KeyboardInterrupt:
        print("\nStopped")
