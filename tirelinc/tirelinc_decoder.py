#!/usr/bin/env python3
"""
TireLinc Advertising Data Decoder
Captures and analyzes BLE advertising packets from TireLinc TPMS
"""

import asyncio
import struct
from bleak import BleakScanner
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TIRELINC_MAC = "F4:CF:A2:85:D0:62"

def decode_tpms_data(data):
    """
    Attempt to decode tire pressure monitoring data
    TPMS data often includes:
    - Tire pressure (PSI or kPa)
    - Temperature (°C or °F)
    - Battery level
    - Sensor ID
    """
    if not data:
        return "No data"
    
    hex_data = data.hex()
    logger.info(f"Raw hex data: {hex_data}")
    
    # Try common TPMS data patterns
    results = []
    
    # Pattern 1: Look for pressure values (typical range 20-60 PSI = 138-414 kPa)
    for i in range(0, len(data) - 1, 2):
        if i + 1 < len(data):
            # Try 16-bit values
            val16_le = struct.unpack('<H', data[i:i+2])[0]  # Little endian
            val16_be = struct.unpack('>H', data[i:i+2])[0]  # Big endian
            
            # Check if values could be pressure (20-100 PSI range)
            if 20 <= val16_le <= 100:
                results.append(f"Possible pressure @{i}: {val16_le} PSI (LE)")
            if 20 <= val16_be <= 100:
                results.append(f"Possible pressure @{i}: {val16_be} PSI (BE)")
            
            # Check if values could be kPa (138-690 kPa range)
            if 138 <= val16_le <= 690:
                results.append(f"Possible pressure @{i}: {val16_le} kPa (LE)")
            if 138 <= val16_be <= 690:
                results.append(f"Possible pressure @{i}: {val16_be} kPa (BE)")
    
    # Pattern 2: Look for temperature values (-40 to +85°C typical range)
    for i in range(len(data)):
        temp_c = data[i] - 40  # Common offset encoding
        if -40 <= temp_c <= 85:
            results.append(f"Possible temp @{i}: {temp_c}°C")
    
    # Pattern 3: Look for manufacturer-specific patterns
    if len(data) >= 4:
        # Check for common TPMS manufacturer prefixes
        if data[0:2] == b'\x02\x01':  # Common BLE advertising flag
            results.append("Standard BLE advertising data detected")
    
    return results if results else ["No recognizable TPMS patterns found"]

async def scan_callback(device, advertisement_data):
    """Callback for when a device is discovered"""
    if device.address.upper() == TIRELINC_MAC.upper():
        logger.info(f"Found TireLinc device: {device.name}")
        logger.info(f"Address: {device.address}")
        logger.info(f"RSSI: {advertisement_data.rssi} dBm")
        
        # Analyze manufacturer data
        if advertisement_data.manufacturer_data:
            logger.info("Manufacturer Data:")
            for company_id, data in advertisement_data.manufacturer_data.items():
                logger.info(f"  Company ID: 0x{company_id:04x}")
                logger.info(f"  Data: {data.hex()}")
                decoded = decode_tpms_data(data)
                for result in decoded:
                    logger.info(f"    {result}")
        
        # Analyze service data
        if advertisement_data.service_data:
            logger.info("Service Data:")
            for uuid, data in advertisement_data.service_data.items():
                logger.info(f"  Service UUID: {uuid}")
                logger.info(f"  Data: {data.hex()}")
                decoded = decode_tpms_data(data)
                for result in decoded:
                    logger.info(f"    {result}")
        
        # Check local name and other data
        if advertisement_data.local_name:
            logger.info(f"Local Name: {advertisement_data.local_name}")
        
        logger.info("-" * 50)

async def main():
    """Main scanning function"""
    logger.info("Starting TireLinc advertising data capture...")
    logger.info(f"Looking for device: {TIRELINC_MAC}")
    logger.info("Press Ctrl+C to stop")
    
    try:
        # Scan for 60 seconds
        async with BleakScanner(detection_callback=scan_callback) as scanner:
            await asyncio.sleep(60.0)
    except KeyboardInterrupt:
        logger.info("Scan stopped by user")
    except Exception as e:
        logger.error(f"Error during scan: {e}")

if __name__ == "__main__":
    asyncio.run(main())
