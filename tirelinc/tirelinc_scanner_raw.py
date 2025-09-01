#!/usr/bin/env python3
"""
TireLinc Raw Advertisement Scanner
Scans for BLE advertisements from TireLinc device and displays raw data
"""

import asyncio
import time
from bleak import BleakScanner

# Target TireLinc MAC address
TIRELINC_MAC = 'F4:CF:A2:85:D0:62'

def format_hex_data(data):
    """Format hex data with spacing for readability"""
    hex_str = data.hex().upper()
    return ' '.join([hex_str[i:i+4] for i in range(0, len(hex_str), 4)])

def format_ascii_data(data):
    """Format data showing printable ASCII and hex for non-printable"""
    result = ""
    for byte in data:
        if 32 <= byte <= 126:  # Printable ASCII
            result += chr(byte)
        else:
            result += f"\\x{byte:02X}"
    return result

def analyze_advertisement_data(advertisement_data):
    """Analyze and display all advertisement data sections"""
    print("\n--- ADVERTISEMENT DATA BREAKDOWN ---")
    
    # Access AdvertisementData attributes directly
    print(f"Local Name: {advertisement_data.local_name}")
    print(f"Short Name: {advertisement_data.local_name_short}")
    print(f"Service UUIDs: {advertisement_data.service_uuids}")
    print(f"Platform Data: {advertisement_data.platform_data}")
    
    # Check manufacturer data
    if advertisement_data.manufacturer_data:
        print(f"\n--- MANUFACTURER DATA (Potential Tire Data) ---")
        for mfg_id, mfg_data in advertisement_data.manufacturer_data.items():
            print(f"Manufacturer ID: {mfg_id} (0x{mfg_id:04X})")
            print(f"Raw Hex: {format_hex_data(mfg_data)}")
            print(f"ASCII: '{format_ascii_data(mfg_data)}'")
            print(f"Length: {len(mfg_data)} bytes")
            
            # Byte-by-byte breakdown
            print(f"Byte breakdown:")
            for i, byte in enumerate(mfg_data):
                char = chr(byte) if 32 <= byte <= 126 else f"\\x{byte:02X}"
                print(f"  Byte {i:2d}: 0x{byte:02X} ({byte:3d}) = '{char}'")
    
    # Check service data
    if advertisement_data.service_data:
        print(f"\n--- SERVICE DATA (Potential Tire Data) ---")
        for service_uuid, service_data in advertisement_data.service_data.items():
            print(f"Service UUID: {service_uuid}")
            print(f"Raw Hex: {format_hex_data(service_data)}")
            print(f"ASCII: '{format_ascii_data(service_data)}'")
            print(f"Length: {len(service_data)} bytes")
            
            # Byte-by-byte breakdown
            print(f"Byte breakdown:")
            for i, byte in enumerate(service_data):
                char = chr(byte) if 32 <= byte <= 126 else f"\\x{byte:02X}"
                print(f"  Byte {i:2d}: 0x{byte:02X} ({byte:3d}) = '{char}'")

def detection_callback(device, advertisement_data):
    """Callback function called when a BLE device is detected"""
    
    # Check if this is our TireLinc device
    if device.address.upper() == TIRELINC_MAC.upper():
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        
        print(f"\n{'='*80}")
        print(f"[{timestamp}] TIRELINC DEVICE DETECTED!")
        print(f"Device: {device.name} ({device.address})")
        print(f"RSSI: {device.rssi} dBm")
        print(f"{'='*80}")
        
        # Display all raw advertisement data
        analyze_advertisement_data(advertisement_data)
        
        # Try to extract any raw data
        raw_data_found = False
        
        # Check manufacturer data
        if advertisement_data.manufacturer_data:
            raw_data_found = True
            print(f"\n--- MANUFACTURER DATA ANALYSIS ---")
            for mfg_id, data in advertisement_data.manufacturer_data.items():
                print(f"Manufacturer {mfg_id}: {format_hex_data(data)}")
                
                # Try to interpret as tire sensor data
                if len(data) >= 6:  # Assuming minimum data length for tire info
                    print(f"Potential tire data interpretation:")
                    print(f"  Raw bytes: {[hex(b) for b in data]}")
                    
                    # Common tire sensor data patterns
                    if len(data) >= 8:
                        # Try different interpretations
                        pressure_raw = int.from_bytes(data[0:2], 'little')
                        temp_raw = int.from_bytes(data[2:4], 'little') if len(data) >= 4 else 0
                        print(f"  Possible pressure (little-endian): {pressure_raw}")
                        print(f"  Possible temperature (little-endian): {temp_raw}")
                        
                        pressure_raw_big = int.from_bytes(data[0:2], 'big')
                        temp_raw_big = int.from_bytes(data[2:4], 'big') if len(data) >= 4 else 0
                        print(f"  Possible pressure (big-endian): {pressure_raw_big}")
                        print(f"  Possible temperature (big-endian): {temp_raw_big}")
        
        # Check service data
        if advertisement_data.service_data:
            raw_data_found = True
            print(f"\n--- SERVICE DATA ANALYSIS ---")
            for service_uuid, data in advertisement_data.service_data.items():
                print(f"Service {service_uuid}: {format_hex_data(data)}")
        
        if not raw_data_found:
            print("\n--- NO RAW DATA FOUND IN ADVERTISEMENT ---")
            print("This device might only advertise basic info or use a different data format")
        
        print(f"{'='*80}")

async def scan_for_tirelinc():
    """Continuously scan for TireLinc advertisements"""
    print("TireLinc Raw Advertisement Scanner")
    print("=" * 50)
    print(f"Target Device: {TIRELINC_MAC}")
    print("Scanning for BLE advertisements...")
    print("Press Ctrl+C to stop")
    print()
    
    # Create scanner with callback
    scanner = BleakScanner(detection_callback)
    
    try:
        # Start scanning
        await scanner.start()
        print("Scanner started. Listening for advertisements...")
        
        # Keep scanning
        while True:
            await asyncio.sleep(1.0)
            
    except KeyboardInterrupt:
        print("\nStopping scanner...")
    finally:
        await scanner.stop()
        print("Scanner stopped.")

if __name__ == "__main__":
    try:
        asyncio.run(scan_for_tirelinc())
    except KeyboardInterrupt:
        print("\nStopped by user")
    except Exception as e:
        print(f"Error: {e}")
