#!/usr/bin/env python3
"""
CAN bit rate verification script for oscilloscope testing.
Sends specific patterns to make bit rate measurement easier.
"""

import can
import time

def send_scope_test_patterns():
    """Send test patterns optimized for oscilloscope bit rate verification"""
    
    print("CAN Bit Rate Verification for Oscilloscope")
    print("=========================================")
    print("Target bit rate: 250 kbps")
    print("Expected bit time: 4.0 microseconds")
    print("Expected byte time: 32.0 microseconds (8 bits)")
    print()
    
    try:
        can1 = can.interface.Bus(channel='can1', interface='socketcan')
        
        print("Continuous CAN transmission for oscilloscope measurement")
        print("Sending alternating bit patterns (0x55 = 01010101)")
        print("   - Each bit should be 4.0us wide")
        print("   - Connect scope to CANH or CANL") 
        print("   - Trigger on falling edge")
        print("   - Press Ctrl+C to stop transmission")
        print()
        
        try:
            count = 0
            while True:
                # Send alternating bit pattern - best for measuring individual bits
                msg = can.Message(
                    arbitration_id=0x123,
                    data=[0x55, 0x55, 0x55, 0x55, 0x55, 0x55, 0x55, 0x55],
                    is_extended_id=False
                )
                can1.send(msg)
                count += 1
                # if count % 100 == 0:
                #     print(f"   Sent {count} messages... (Press Ctrl+C to stop)")
                time.sleep(0.01)  # 10ms between frames = continuous activity
                
        except KeyboardInterrupt:
            print(f"\n   Transmission stopped after {count} messages")
        
        can1.shutdown()
        print("Oscilloscope measurement session complete!")
        
    except Exception as e:
        print(f"Error: {e}")

def print_measurement_guide():
    """Print oscilloscope measurement instructions"""
    print("\n" + "="*60)
    print("OSCILLOSCOPE MEASUREMENT GUIDE")
    print("="*60)
    print()
    print("1. SETUP:")
    print("   - Connect probe to CANH pin on MCP2515")
    print("   - Ground clip to circuit ground") 
    print("   - Trigger: Edge, falling, ~1.5V threshold")
    print("   - Time scale: 2us/div (to see individual bits)")
    print("   - Voltage scale: 1V/div")
    print()
    print("2. MEASUREMENTS TO TAKE:")
    print("   - Individual bit width: Should be 4.0us +/- 0.1us")
    print("   - Byte transmission time: Should be 32.0us (8 bits)")
    print("   - Frame gap time: Variable (inter-frame spacing)")
    print()
    print("3. WHAT YOU'LL SEE:")
    print("   - Dominant bits: Low voltage (~1V)")
    print("   - Recessive bits: High voltage (~3.5V)")
    print("   - Clean square waves at 250kHz bit rate")
    print()
    print("4. VERIFICATION:")
    print("   - If bit time = 4.0us -> Bit rate = 250 kbps OK")
    print("   - If bit time != 4.0us -> Check configuration")
    print()

if __name__ == "__main__":
    print_measurement_guide()
    input("Press Enter when oscilloscope is connected and ready...")
    send_scope_test_patterns()
