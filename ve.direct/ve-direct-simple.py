#!/usr/bin/env python3
"""
VE.Direct Simple Reader
Reads and decodes VE.Direct protocol data from Victron devices
Supports both real hardware and test mode for debugging
"""

import serial
import time
import glob
import sys
import random

# Configuration - will auto-detect available ports
potential_ports = ['/dev/ttyAMA0', '/dev/ttyAMA10', '/dev/ttyUSB0', '/dev/ttyUSB1']
baud_rate = 19200

def find_serial_ports():
    """Find available serial ports on the system"""
    available_ports = []
    
    # Check common RPi serial ports
    for port in potential_ports:
        try:
            # Try to open the port briefly to test if it exists and is accessible
            test_ser = serial.Serial(port, baud_rate, timeout=0.1)
            test_ser.close()
            available_ports.append(port)
            print(f"Found available port: {port}")
        except (serial.SerialException, FileNotFoundError, PermissionError):
            continue
    
    # Also check for any USB serial devices
    usb_ports = glob.glob('/dev/ttyUSB*')
    for port in usb_ports:
        if port not in available_ports:
            try:
                test_ser = serial.Serial(port, baud_rate, timeout=0.1)
                test_ser.close()
                available_ports.append(port)
                print(f"Found USB serial port: {port}")
            except (serial.SerialException, PermissionError):
                continue
    
    return available_ports

def decode_ve_direct_message(data):
    """
    Decode VE.Direct message data
    VE.Direct protocol sends tab-separated key-value pairs
    """
    if not data or '\t' not in data:
        return None
    
    try:
        parts = data.split('\t')
        if len(parts) != 2:
            return None
            
        key, value = parts
        
        # Common VE.Direct fields with units and scaling
        decoders = {
            'V': lambda x: f"Battery Voltage: {float(x)/1000:.3f}V",
            'VPV': lambda x: f"Panel Voltage: {float(x)/1000:.3f}V", 
            'I': lambda x: f"Battery Current: {float(x)/1000:.3f}A",
            'IL': lambda x: f"Load Current: {float(x)/1000:.3f}A",
            'PPV': lambda x: f"Panel Power: {float(x)}W",
            'H19': lambda x: f"Yield Total: {float(x)/100:.2f}kWh",
            'H20': lambda x: f"Yield Today: {float(x)/100:.2f}kWh",
            'H21': lambda x: f"Maximum Power Today: {float(x)}W",
            'H22': lambda x: f"Yield Yesterday: {float(x)/100:.2f}kWh",
            'H23': lambda x: f"Maximum Power Yesterday: {float(x)}W",
            'CS': lambda x: decode_charger_status(x),
            'MPPT': lambda x: decode_mppt_status(x),
            'ERR': lambda x: decode_error_status(x),
            'PID': lambda x: f"Product ID: {x}",
            'SER#': lambda x: f"Serial Number: {x}",
            'FW': lambda x: f"Firmware Version: {x}",
        }
        
        if key in decoders:
            try:
                return decoders[key](value)
            except (ValueError, TypeError):
                return f"{key}: {value} (decode error)"
        else:
            return f"{key}: {value}"
            
    except Exception as e:
        return f"Parse error: {e}"

def decode_charger_status(value):
    """Decode charger status codes"""
    status_codes = {
        "0": "Off", "1": "Low power", "2": "Fault", "3": "Bulk",
        "4": "Absorption", "5": "Float", "6": "Storage", "7": "Equalize",
        "9": "Inverting", "11": "Power supply", "245": "Starting-up",
        "252": "External control"
    }
    return f"Charger Status: {status_codes.get(value, f'Unknown ({value})')}"

def decode_mppt_status(value):
    """Decode MPPT status codes"""
    status_codes = {
        "0": "Off", "1": "Voltage/current limited", "2": "MPPT active"
    }
    return f"MPPT Status: {status_codes.get(value, f'Unknown ({value})')}"

def decode_error_status(value):
    """Decode error status codes"""
    if value == "0":
        return "Error Status: No error"
    error_codes = {
        "2": "Battery voltage too high", "17": "Charger temperature too high",
        "18": "Charger over current", "19": "Charger current reversed",
        "20": "Bulk time limit exceeded", "21": "Current sensor issue",
        "26": "Terminals overheated", "33": "Input voltage too high",
        "34": "Input current too high"
    }
    return f"Error Status: {error_codes.get(value, f'Unknown error ({value})')}"

def test_mode():
    """Test mode with simulated VE.Direct data"""
    print("Running in TEST MODE (simulated data)")
    print("-" * 50)
    
    test_data_sets = [
        ["PID\t0xA057", "FW\t162", "SER#\tHQ2134ABCDE"],
        [f"V\t{random.randint(12000, 14500)}", f"VPV\t{random.randint(15000, 25000)}", 
         f"PPV\t{random.randint(0, 300)}", f"I\t{random.randint(-1000, 15000)}"],
        [f"IL\t{random.randint(0, 5000)}", "CS\t3", "MPPT\t2", "ERR\t0"],
        [f"H19\t{random.randint(50000, 100000)}", f"H20\t{random.randint(100, 2000)}",
         f"H21\t{random.randint(100, 400)}"]
    ]
    
    try:
        line_count = 0
        cycle = 0
        
        while True:
            cycle += 1
            print(f"\n=== Test Cycle {cycle} ===")
            
            for data_set in test_data_sets:
                for data in data_set:
                    line_count += 1
                    print(f"[{line_count:03d}] {data}")
                    
                    # Decode the test data
                    decoded = decode_ve_direct_message(data)
                    if decoded:
                        print(f"      Decoded: {decoded}")
                    
                    time.sleep(0.2)
                time.sleep(0.5)
            
            time.sleep(2)  # Pause between cycles
            
    except KeyboardInterrupt:
        print("\nTest mode terminated by user.")

def main():
    print("VE.Direct Simple Reader")
    print("=" * 30)
    
    # Check for test mode argument
    if len(sys.argv) > 1 and sys.argv[1].lower() in ['test', '-t', '--test']:
        test_mode()
        return
    
    # Find available serial ports
    available_ports = find_serial_ports()
    
    if not available_ports:
        print("No accessible serial ports found!")
        print("Common causes:")
        print("1. No VE.Direct device connected")
        print("2. User not in 'dialout' group - run: sudo usermod -a -G dialout $USER")
        print("3. Device permissions issue - try running with sudo")
        print("\nTo test without hardware, run: python3 ve-direct-simple.py test")
        return
    
    # Use the first available port
    serial_port = available_ports[0]
    print(f"Using serial port: {serial_port}")
    
    # Open the serial port
    try:
        print(f"Pyserial version: {serial.__version__}")
        ser = serial.Serial(serial_port, baudrate=baud_rate, timeout=1)
        print(f"Serial port {serial_port} opened successfully.")
    except Exception as e:
        print(f"Failed to open serial port: {e}")
        print("Try running with sudo or check device permissions")
        return

    try:
        print("Reading VE.Direct data... (Ctrl+C to stop)")
        print("-" * 50)
        line_count = 0
        
        while True:
            # Read data from the serial port
            data = ser.readline().decode(errors='ignore').strip()

            if data:
                line_count += 1
                print(f"[{line_count:03d}] {data}")
                
                # Basic parsing attempt
                if '\t' in data:
                    parts = data.split('\t')
                    if len(parts) == 2:
                        key, value = parts
                        print(f"      -> {key}: {value}")
                
                # Decode specific known fields
                decoded = decode_ve_direct_message(data)
                if decoded:
                    print(f"      Decoded: {decoded}")

            # Add a delay before reading the next message
            time.sleep(0.1)
            
    except KeyboardInterrupt:
        print("\nProgram terminated by user.")
    except Exception as e:
        print(f"Error during operation: {e}")
    finally:
        # Close the serial port when the program exits
        if 'ser' in locals():
            ser.close()
            print("Serial port closed.")

if __name__ == "__main__":
    main()
