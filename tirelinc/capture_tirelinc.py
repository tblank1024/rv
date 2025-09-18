#!/usr/bin/env python3
"""
TireLinc Advertising Data Capture
Captures tire pressure data from TireLinc advertising packets
"""

import asyncio
import struct
import time
from bleak import BleakScanner

TIRELINC_MAC = 'F4:CF:A2:85:D0:62'

def decode_tire_data(data, data_type="unknown"):
    """Attempt to decode tire pressure data from various data formats"""
    if not data or len(data) == 0:
        return []
    
    results = []
    hex_data = data.hex()
    
    print(f"    Raw {data_type} data ({len(data)} bytes): {hex_data}")
    
    # Try to decode as ASCII text
    try:
        ascii_text = data.decode('ascii')
        if ascii_text.isprintable():
            results.append(f"ASCII text: '{ascii_text}'")
    except:
        pass
    
    # Look for pressure values in various formats
    for i in range(len(data) - 1):
        if i + 1 < len(data):
            # 16-bit values
            val16_le = struct.unpack('<H', data[i:i+2])[0]
            val16_be = struct.unpack('>H', data[i:i+2])[0]
            
            # Check for reasonable pressure values (20-80 PSI)
            if 20 <= val16_le <= 80:
                results.append(f"Possible pressure @{i}: {val16_le} PSI (16-bit LE)")
            if 20 <= val16_be <= 80:
                results.append(f"Possible pressure @{i}: {val16_be} PSI (16-bit BE)")
            
            # Check for kPa values (140-550 kPa ≈ 20-80 PSI)
            if 140 <= val16_le <= 550:
                psi = val16_le * 0.145038  # Convert kPa to PSI
                results.append(f"Possible pressure @{i}: {val16_le} kPa ({psi:.1f} PSI)")
            if 140 <= val16_be <= 550:
                psi = val16_be * 0.145038
                results.append(f"Possible pressure @{i}: {val16_be} kPa ({psi:.1f} PSI)")
    
    # Look for 8-bit pressure values (scaled)
    for i in range(len(data)):
        val8 = data[i]
        # Some TPMS systems use scaled 8-bit values
        if val8 > 0:
            # Try different scaling factors
            for scale in [0.5, 1.0, 2.0, 4.0]:
                scaled_val = val8 * scale
                if 20 <= scaled_val <= 80:
                    results.append(f"Possible pressure @{i}: {scaled_val} PSI (8-bit, scale {scale})")
    
    # Look for temperature values (-40 to +85°C range)
    for i in range(len(data)):
        temp_c = data[i] - 40  # Common temperature encoding
        if -40 <= temp_c <= 85:
            temp_f = temp_c * 9/5 + 32
            results.append(f"Possible temp @{i}: {temp_c}°C ({temp_f:.1f}°F)")
    
    # Look for tire ID patterns (usually 1-6 for tire positions)
    for i in range(len(data)):
        if 1 <= data[i] <= 6:
            results.append(f"Possible tire ID @{i}: {data[i]}")
    
    return results

def parse_advertising_data(advertisement_data):
    """Parse and display advertising data from TireLinc"""
    timestamp = time.strftime("%H:%M:%S")
    print(f"\n[{timestamp}] TireLinc Advertisement:")
    print(f"  RSSI: {advertisement_data.rssi} dBm")
    
    if advertisement_data.local_name:
        print(f"  Local Name: {advertisement_data.local_name}")
    
    # Check manufacturer data
    if advertisement_data.manufacturer_data:
        print(f"  Manufacturer Data:")
        for company_id, data in advertisement_data.manufacturer_data.items():
            print(f"    Company ID: 0x{company_id:04x} ({company_id})")
            decoded = decode_tire_data(data, "manufacturer")
            for result in decoded:
                print(f"      {result}")
    
    # Check service data  
    if advertisement_data.service_data:
        print(f"  Service Data:")
        for uuid, data in advertisement_data.service_data.items():
            print(f"    Service UUID: {uuid}")
            decoded = decode_tire_data(data, "service")
            for result in decoded:
                print(f"      {result}")
    
    # Check service UUIDs
    if advertisement_data.service_uuids:
        print(f"  Service UUIDs: {advertisement_data.service_uuids}")
    
    print("  " + "="*60)

async def scan_for_tirelinc():
    """Scan for TireLinc and capture advertising data"""
    print("TireLinc Advertising Data Capture")
    print("=================================")
    print(f"Scanning for TireLinc device: {TIRELINC_MAC}")
    print("Looking for tire pressure data in advertising packets...")
    print("Press Ctrl+C to stop\n")
    
    def detection_callback(device, advertisement_data):
        if device.address.upper() == TIRELINC_MAC.upper():
            parse_advertising_data(advertisement_data)
    
    try:
        async with BleakScanner(detection_callback=detection_callback) as scanner:
            # Scan indefinitely until interrupted
            while True:
                await asyncio.sleep(1.0)
    except KeyboardInterrupt:
        print("\nScan stopped by user")
    except Exception as e:
        print(f"Scan error: {e}")

if __name__ == "__main__":
    asyncio.run(scan_for_tirelinc())
