#!/usr/bin/env python3
"""
TireLinc Change Monitor - Watches for changes in BLE data
Highlights when data changes to help identify tire sensor updates
"""

import asyncio
from datetime import datetime
from bleak import BleakScanner

# Target TireLinc MAC address
TIRELINC_MAC = 'F4:CF:A2:85:D0:62'

# Track previous values to detect changes
last_mfg_05c7 = None
last_mfg_004c = None
change_count = 0

async def detection_callback(device, advertisement_data):
    """Callback function called when a BLE advertisement is detected"""
    global last_mfg_05c7, last_mfg_004c, change_count
    
    # Check if this is our target device
    if device.address.upper() == TIRELINC_MAC.upper():
        current_time = datetime.now().strftime("%H:%M:%S")
        
        # Check manufacturer data
        if advertisement_data.manufacturer_data:
            current_05c7 = None
            current_004c = None
            
            for mfg_id, data in advertisement_data.manufacturer_data.items():
                hex_data = data.hex().upper()
                
                if mfg_id == 0x05C7:  # TireLinc manufacturer data
                    current_05c7 = hex_data
                elif mfg_id == 0x004C:  # Apple iBeacon data
                    current_004c = hex_data
            
            # Check for changes
            mfg_05c7_changed = (current_05c7 != last_mfg_05c7)
            mfg_004c_changed = (current_004c != last_mfg_004c)
            
            # Only print if there's a change or every 30 seconds for status
            if mfg_05c7_changed or mfg_004c_changed or (change_count % 100 == 0):
                print(f"\n[{current_time}] TireLinc Data:")
                
                if current_05c7:
                    status = "**CHANGED**" if mfg_05c7_changed else "same"
                    print(f"  MFG:05C7 {hex_data} ({status})")
                    if mfg_05c7_changed:
                        print(f"    Previous: {last_mfg_05c7}")
                        print(f"    Current:  {current_05c7}")
                
                if current_004c:
                    status = "**CHANGED**" if mfg_004c_changed else "same"
                    print(f"  MFG:004C {current_004c} ({status})")
                    if mfg_004c_changed:
                        print(f"    Previous: {last_mfg_004c}")
                        print(f"    Current:  {current_004c}")
                
                if mfg_05c7_changed or mfg_004c_changed:
                    print(f"  *** CHANGE DETECTED AT {current_time} ***")
            
            # Update last known values
            if current_05c7:
                last_mfg_05c7 = current_05c7
            if current_004c:
                last_mfg_004c = current_004c
                
            change_count += 1

async def monitor_changes():
    """Monitor for changes in TireLinc BLE data"""
    print("TireLinc Change Monitor")
    print("======================")
    print(f"Monitoring device: {TIRELINC_MAC}")
    print("Watching for changes in MFG:05C7 and MFG:004C data...")
    print("Status updates every ~30 seconds, changes highlighted immediately")
    print("Press Ctrl+C to stop\n")
    
    # Create scanner with callback
    scanner = BleakScanner(detection_callback)
    
    try:
        # Start scanning
        await scanner.start()
        
        # Keep scanning
        while True:
            await asyncio.sleep(0.3)  # Check frequently for changes
            
    except KeyboardInterrupt:
        print("\n\nStopping monitor...")
    finally:
        await scanner.stop()
        print("Monitor stopped.")

if __name__ == "__main__":
    asyncio.run(monitor_changes())
