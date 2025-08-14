#!/usr/bin/env python3
"""
VE.Direct Test Data Simulator
Generates fake VE.Direct protocol data for testing without actual hardware
"""

import time
import random

def generate_test_data():
    """Generate realistic VE.Direct test data"""
    
    # Simulate a solar charge controller data cycle
    test_data = [
        "PID\t0xA057",  # Product ID
        "FW\t162",      # Firmware version
        "SER#\tHQ2134ABCDE",  # Serial number
        f"V\t{random.randint(12000, 14500)}",  # Battery voltage (mV)
        f"VPV\t{random.randint(15000, 25000)}", # Panel voltage (mV)
        f"PPV\t{random.randint(0, 300)}",      # Panel power (W)
        f"I\t{random.randint(-1000, 15000)}",  # Battery current (mA)
        f"IL\t{random.randint(0, 5000)}",      # Load current (mA)
        f"H19\t{random.randint(50000, 100000)}", # Total yield (0.01kWh)
        f"H20\t{random.randint(100, 2000)}",   # Today's yield (0.01kWh)
        f"H21\t{random.randint(100, 400)}",    # Max power today (W)
        f"H22\t{random.randint(100, 2000)}",   # Yesterday's yield (0.01kWh)
        f"H23\t{random.randint(100, 400)}",    # Max power yesterday (W)
        "CS\t3",        # Charger state (Bulk)
        "MPPT\t2",      # MPPT state (Active)
        "ERR\t0",       # Error state (No error)
        "Checksum\t\x8A", # Frame end
    ]
    
    return test_data

def main():
    print("VE.Direct Test Data Generator")
    print("=" * 35)
    print("Generating simulated VE.Direct data...")
    print("(This simulates what a real solar charge controller would send)")
    print("-" * 60)
    
    try:
        cycle = 0
        while True:
            cycle += 1
            print(f"\n--- Data Cycle {cycle} ---")
            
            test_data = generate_test_data()
            
            for line in test_data:
                print(line)
                time.sleep(0.1)  # Simulate real device timing
            
            print("--- End of cycle ---")
            time.sleep(2)  # Pause between cycles
            
    except KeyboardInterrupt:
        print("\nTest data generator stopped.")

if __name__ == "__main__":
    main()
