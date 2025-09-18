#!/usr/bin/env python3
"""
TireLinc 6-Tire Data Decoder
Analyzes the 6-byte manufacturer data to extract pressure and temperature for 6 tires
"""

import asyncio
import struct
import time
from datetime import datetime
from bleak import BleakScanner

TIRELINC_MAC = 'F4:CF:A2:85:D0:62'
COMPANY_ID = 0x05c7  # TireLinc manufacturer ID

def decode_6_tire_data(data):
    """
    Decode 6-byte TireLinc data into 6 tire readings
    Based on the captured data: 011801010000
    
    Hypothesis: Each byte or pair of bytes represents tire data
    """
    if len(data) != 6:
        return None
    
    # Convert to hex for easier analysis
    hex_data = data.hex()
    print(f"    Raw 6-byte data: {hex_data}")
    
    # Method 1: Each byte represents one tire (simple approach)
    method1_tires = []
    for i, byte_val in enumerate(data):
        tire_id = i + 1
        # Try different pressure scaling factors
        pressure_psi = byte_val * 0.5  # Scale factor to get reasonable PSI
        temp_c = byte_val - 40 if byte_val > 40 else None  # Temperature offset
        
        method1_tires.append({
            'tire_id': tire_id,
            'raw_value': byte_val,
            'pressure_psi': pressure_psi,
            'temp_c': temp_c
        })
    
    # Method 2: 2 bytes per tire (3 tires total, maybe alternating data)
    method2_tires = []
    for i in range(0, 6, 2):
        tire_id = (i // 2) + 1
        if i + 1 < len(data):
            # Combine two bytes for pressure/temp
            word = struct.unpack('>H', data[i:i+2])[0]  # Big endian 16-bit
            
            # Try extracting pressure and temp from the 16-bit word
            pressure_raw = word & 0xFF  # Lower 8 bits
            temp_raw = (word >> 8) & 0xFF  # Upper 8 bits
            
            pressure_psi = pressure_raw * 0.5  # Scale to reasonable PSI
            temp_c = temp_raw - 40 if temp_raw > 40 else None
            
            method2_tires.append({
                'tire_id': tire_id,
                'raw_word': word,
                'pressure_psi': pressure_psi,
                'temp_c': temp_c
            })
    
    # Method 3: Nibble-based (4 bits per value, 12 values total)
    method3_data = []
    for byte_val in data:
        high_nibble = (byte_val >> 4) & 0x0F
        low_nibble = byte_val & 0x0F
        method3_data.extend([high_nibble, low_nibble])
    
    method3_tires = []
    for i in range(0, min(12, len(method3_data)), 2):
        tire_id = (i // 2) + 1
        if i + 1 < len(method3_data):
            pressure_raw = method3_data[i]
            temp_raw = method3_data[i + 1]
            
            pressure_psi = pressure_raw * 3.0 + 20  # Scale to 20-65 PSI range
            temp_c = temp_raw * 5.0 - 20  # Scale to reasonable temp range
            
            method3_tires.append({
                'tire_id': tire_id,
                'pressure_psi': pressure_psi,
                'temp_c': temp_c
            })
    
    # Method 4: Based on actual captured values (011801010000)
    # Let's analyze the specific pattern we see
    method4_analysis = analyze_specific_pattern(data)
    
    return {
        'method1_individual_bytes': method1_tires,
        'method2_word_pairs': method2_tires,
        'method3_nibbles': method3_tires,
        'method4_pattern_analysis': method4_analysis
    }

def analyze_specific_pattern(data):
    """
    Analyze the specific pattern we see: 011801010000
    This might be a status/header + actual tire data
    """
    analysis = {
        'pattern': data.hex(),
        'interpretation': {}
    }
    
    # The pattern 011801010000 might mean:
    # 01 - Header/status byte
    # 18 - Could be pressure value (24 decimal = 24*0.5 = 12 PSI or 24*2 = 48 PSI)
    # 01 - Tire ID or status
    # 01 - Another tire ID or status  
    # 00 - No data or placeholder
    # 00 - No data or placeholder
    
    if len(data) >= 6:
        analysis['interpretation'] = {
            'header': data[0],  # 0x01
            'data_byte_1': data[1],  # 0x18 (24 decimal)
            'data_byte_2': data[2],  # 0x01
            'data_byte_3': data[3],  # 0x01
            'data_byte_4': data[4],  # 0x00
            'data_byte_5': data[5],  # 0x00
        }
        
        # Hypothesis: Only some bytes contain active tire data
        active_tires = []
        
        # Check if bytes 1-6 represent tire data
        for i in range(1, 6):
            if data[i] > 0:  # Non-zero values might be active tires
                pressure_psi = data[i] * 2.0  # Scale factor
                active_tires.append({
                    'tire_position': i,
                    'raw_value': data[i],
                    'pressure_psi': pressure_psi
                })
        
        analysis['active_tires'] = active_tires
    
    return analysis

def display_tire_data(results, timestamp):
    """Display the analyzed tire data in a formatted way"""
    print(f"\n[{timestamp.strftime('%H:%M:%S')}] TireLinc 6-Tire Data Analysis:")
    print("=" * 57)
    
    if not results:
        print("No tire data decoded")
        return
    
    # Display each method's results
    for method_name, tires in results.items():
        print(f"\n{method_name}:")
        
        if not tires:
            print("  No valid tire data found")
            continue
            
        for tire in tires:
            pressure_str = f"{tire['pressure_psi']:5.1f}" if tire.get('pressure_psi') is not None else "  N/A"
            
            # Handle both temperature_f and temperature_c keys
            temp_f = tire.get('temperature_f')
            temp_c = tire.get('temperature_c')
            if temp_f is not None:
                temp_str = f"{temp_f:5.1f}°F"
            elif temp_c is not None:
                temp_str = f"{temp_c:5.1f}°C"
            else:
                temp_str = "  N/A"
                
            raw_val = tire.get('raw_value', 0)
            raw_str = f"{raw_val:02X}" if raw_val is not None else "N/A"
            print(f"  Tire {tire['tire_id']}: {pressure_str} PSI, "
                  f"{temp_str} (Raw: {raw_str})")
        
        # Calculate averages for this method
        pressures = [t['pressure_psi'] for t in tires if t.get('pressure_psi') is not None]
        temps_f = [t['temperature_f'] for t in tires if t.get('temperature_f') is not None]
        temps_c = [t['temperature_c'] for t in tires if t.get('temperature_c') is not None]
        
        if pressures:
            avg_pressure = sum(pressures) / len(pressures)
            print(f"  Average Pressure: {avg_pressure:.1f} PSI")
            
        if temps_f:
            avg_temp = sum(temps_f) / len(temps_f)
            print(f"  Average Temperature: {avg_temp:.1f}°F")
        elif temps_c:
            avg_temp = sum(temps_c) / len(temps_c)
            print(f"  Average Temperature: {avg_temp:.1f}°C")

async def scan_and_decode_tires():
    """Scan for TireLinc and decode 6-tire data"""
    print("TireLinc 6-Tire Data Decoder")
    print("============================")
    print(f"Scanning for TireLinc device: {TIRELINC_MAC}")
    print("Analyzing advertising data for 6 tire pressure/temperature readings...")
    print("Press Ctrl+C to stop\n")
    
    def detection_callback(device, advertisement_data):
        if device.address.upper() == TIRELINC_MAC.upper():
            timestamp = datetime.now()
            
            # Look for our specific manufacturer data
            if advertisement_data.manufacturer_data:
                for company_id, data in advertisement_data.manufacturer_data.items():
                    if company_id == COMPANY_ID and len(data) == 6:
                        # This is our 6-byte TireLinc data
                        decoded = decode_6_tire_data(data)
                        display_tire_data(decoded, timestamp)
    
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
    asyncio.run(scan_and_decode_tires())
