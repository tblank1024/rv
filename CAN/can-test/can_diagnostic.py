#!/usr/bin/env python3
"""
Comprehensive CAN Bus Diagnostic Tool for Waveshare Dual CAN Board
Tests MCP2515 installation and CAN bus connectivity
"""

import os
import time
import subprocess
import can
from datetime import datetime

def run_command(cmd):
    """Run shell command and return output"""
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        return result.returncode, result.stdout, result.stderr
    except Exception as e:
        return 1, "", str(e)

def test_kernel_modules():
    """Test if CAN kernel modules are loaded"""
    print("=== Testing Kernel Modules ===")
    
    modules = ['can', 'can_raw', 'mcp251x', 'can_dev']
    for module in modules:
        ret, out, err = run_command(f"lsmod | grep {module}")
        if ret == 0:
            print(f"✅ {module} module loaded")
        else:
            print(f"❌ {module} module NOT loaded")
    print()

def test_hardware_detection():
    """Test if MCP2515 chips are detected"""
    print("=== Testing Hardware Detection ===")
    
    ret, out, err = run_command("dmesg | grep -i mcp251")
    if "successfully initialized" in out:
        print("✅ MCP2515 chips detected and initialized")
        print("Hardware detection output:")
        for line in out.strip().split('\n'):
            if 'mcp251' in line.lower():
                print(f"   {line}")
    else:
        print("❌ MCP2515 chips not detected in dmesg")
    print()

def test_can_interfaces():
    """Test CAN interface status"""
    print("=== Testing CAN Interfaces ===")
    
    interfaces = ['can0', 'can1']
    for interface in interfaces:
        ret, out, err = run_command(f"ip link show {interface}")
        if ret == 0:
            print(f"✅ {interface} interface exists")
            # Get detailed info
            ret2, details, err2 = run_command(f"ip -details link show {interface}")
            if "state UP" in details:
                print(f"   Status: UP")
            if "bitrate" in details:
                bitrate = [line for line in details.split('\n') if 'bitrate' in line]
                if bitrate:
                    print(f"   {bitrate[0].strip()}")
        else:
            print(f"❌ {interface} interface not found")
    print()

def test_multiple_bitrates(interface='can0'):
    """Test different bitrates to find the correct one"""
    print(f"=== Testing Multiple Bitrates on {interface} ===")
    
    bitrates = [125000, 250000, 500000, 1000000]
    
    for bitrate in bitrates:
        print(f"Testing bitrate: {bitrate}")
        
        # Configure interface
        run_command(f"sudo ip link set {interface} down")
        run_command(f"sudo ip link set {interface} type can bitrate {bitrate} restart-ms 100")
        run_command(f"sudo ip link set {interface} up")
        
        # Test for messages (short timeout)
        try:
            bus = can.interface.Bus(channel=interface, interface='socketcan')
            print(f"   Listening for 3 seconds on {bitrate} baud...")
            
            start_time = time.time()
            message_count = 0
            
            while time.time() - start_time < 3:
                msg = bus.recv(timeout=0.1)
                if msg:
                    message_count += 1
                    print(f"   ✅ Received message: {msg}")
                    
            if message_count > 0:
                print(f"   ✅ SUCCESS: Received {message_count} messages at {bitrate} baud")
                bus.shutdown()
                return bitrate
            else:
                print(f"   ❌ No messages received at {bitrate} baud")
                
            bus.shutdown()
            
        except Exception as e:
            print(f"   ❌ Error testing {bitrate}: {e}")
    
    print("❌ No CAN traffic detected at any standard bitrate")
    return None

def test_loopback():
    """Test CAN loopback functionality"""
    print("=== Testing CAN Loopback ===")
    
    # Configure can0 and can1 for loopback test
    run_command("sudo ip link set can0 down")
    run_command("sudo ip link set can1 down")
    
    run_command("sudo ip link set can0 type can bitrate 250000 restart-ms 100")
    run_command("sudo ip link set can1 type can bitrate 250000 restart-ms 100")
    
    run_command("sudo ip link set can0 up")
    run_command("sudo ip link set can1 up")
    
    try:
        # Set up buses
        bus0 = can.interface.Bus(channel='can0', interface='socketcan')
        bus1 = can.interface.Bus(channel='can1', interface='socketcan')
        
        # Send message from can1
        test_msg = can.Message(arbitration_id=0x123, data=[0x01, 0x02, 0x03, 0x04], is_extended_id=False)
        print(f"Sending test message from can1: {test_msg}")
        bus1.send(test_msg)
        
        # Try to receive on can0
        print("Listening on can0 for loopback message...")
        received_msg = bus0.recv(timeout=2.0)
        
        if received_msg:
            print(f"✅ Loopback SUCCESS: {received_msg}")
        else:
            print("❌ Loopback FAILED: No message received")
            
        bus0.shutdown()
        bus1.shutdown()
        
    except Exception as e:
        print(f"❌ Loopback test error: {e}")

def check_physical_connections():
    """Provide guidance on physical connections"""
    print("=== Physical Connection Check ===")
    print("Verify these connections on your Waveshare Dual CAN board:")
    print("1. CAN-H and CAN-L are connected to your CAN bus")
    print("2. Ground is properly connected")
    print("3. 5V power is connected (or 3.3V if that's what your board uses)")
    print("4. Check for 120Ω termination resistors at BOTH ends of CAN bus")
    print("5. Verify wiring matches your working RP4 setup")
    print()

def main():
    print("CAN Bus Diagnostic Tool for Raspberry Pi 5 + Waveshare Dual CAN")
    print("=" * 60)
    print(f"Test started at: {datetime.now()}")
    print()
    
    # Run all tests
    test_kernel_modules()
    test_hardware_detection()
    test_can_interfaces()
    
    # Test for actual CAN traffic
    working_bitrate = test_multiple_bitrates('can0')
    
    if working_bitrate:
        print(f"SUCCESS: CAN traffic detected at {working_bitrate} baud!")
    else:
        print("\nNo external CAN traffic detected. Testing internal loopback...")
        test_loopback()
        
    print("\nTroubleshooting Summary:")
    print("If no traffic detected:")
    print("1. Check CAN bus termination (120 ohm resistors)")
    print("2. Verify correct bitrate matches your CAN network")
    print("3. Check physical wiring (CAN-H, CAN-L, GND)")
    print("4. Ensure CAN bus has active devices transmitting")
    print("5. Try different CAN interfaces (can1 if available)")
    
    check_physical_connections()

if __name__ == "__main__":
    main()