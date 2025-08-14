#!/usr/bin/env python3
"""
Simple GPIO test script for Raspberry Pi 5
This script tests basic GPIO functionality before running the full alarm system
"""

import time
from gpiozero import Device, LED, Button, OutputDevice, InputDevice

# For Raspberry Pi 5, use lgpio pin factory (preferred) or fallback
try:
    from gpiozero.pins.lgpio import LGPIOFactory
    Device.pin_factory = LGPIOFactory()
    print("Using LGPIO pin factory for Raspberry Pi 5")
except ImportError:
    try:
        from gpiozero.pins.rpigpio import RPiGPIOFactory
        Device.pin_factory = RPiGPIOFactory()
        print("Using RPi.GPIO pin factory (legacy)")
    except ImportError:
        print("No compatible GPIO library found")
        exit(1)

# Pin definitions (same as in alarm.py)
REDLEDOUT = 12  # Board pin 32 -> GPIO12
BLUELEDOUT = 19  # Board pin 35 -> GPIO19
BUZZEROUT = 22  # Board pin 15 -> GPIO22
HORNOUT = 27    # Board pin 13 -> GPIO27

REDBUTTONIN = 6   # Board pin 31 -> GPIO6
BLUEBUTTONIN = 13 # Board pin 33 -> GPIO13
PIRSENSORIN = 5   # Board pin 29 -> GPIO5

def test_outputs():
    """Test output devices (LEDs, buzzer, horn)"""
    print("\n=== Testing Output Devices ===")
    
    try:
        # Test LEDs
        red_led = LED(REDLEDOUT)
        blue_led = LED(BLUELEDOUT)
        print("+ LEDs initialized")
        
        # Test buzzer and horn
        buzzer = OutputDevice(BUZZEROUT)
        horn = OutputDevice(HORNOUT)
        print("+ Buzzer and horn initialized")
        
        # Blink test
        print("Testing LED blink (5 seconds)...")
        for i in range(5):
            red_led.on()
            blue_led.off()
            time.sleep(0.5)
            red_led.off()
            blue_led.on()
            time.sleep(0.5)
        
        red_led.off()
        blue_led.off()
        print("+ LED test completed")
        
        # Brief buzzer test (comment out if too loud)
        print("Brief buzzer test (1 second)...")
        buzzer.on()
        time.sleep(1)
        buzzer.off()
        print("+ Buzzer test completed")
        
        return True
        
    except Exception as e:
        print(f"- Output test failed: {e}")
        return False

def test_inputs():
    """Test input devices (buttons, PIR sensor)"""
    print("\n=== Testing Input Devices ===")
    
    try:
        # Test buttons
        red_button = Button(REDBUTTONIN, pull_up=True)
        blue_button = Button(BLUEBUTTONIN, pull_up=True)
        pir_sensor = InputDevice(PIRSENSORIN, pull_up=True)
        print("+ Input devices initialized")
        
        print("Testing inputs for 10 seconds...")
        print("Press red button (GPIO6) or blue button (GPIO13)")
        print("Move in front of PIR sensor (GPIO5)")
        
        start_time = time.time()
        while time.time() - start_time < 10:
            status = []
            if red_button.is_pressed:
                status.append("RED")
            if blue_button.is_pressed:
                status.append("BLUE")
            if pir_sensor.is_active:
                status.append("PIR")
            
            if status:
                print(f"Active: {', '.join(status)}")
            
            time.sleep(0.1)
        
        print("+ Input test completed")
        return True
        
    except Exception as e:
        print(f"- Input test failed: {e}")
        return False

def main():
    print("Raspberry Pi 5 GPIO Test for Alarm System")
    print("=" * 45)
    
    # Test outputs first
    output_ok = test_outputs()
    
    # Test inputs
    input_ok = test_inputs()
    
    print("\n=== Test Summary ===")
    print(f"Output devices: {'+ PASS' if output_ok else '- FAIL'}")
    print(f"Input devices:  {'+ PASS' if input_ok else '- FAIL'}")
    
    if output_ok and input_ok:
        print("\nAll tests passed! Your RPi 5 is ready for the alarm system.")
    else:
        print("\nSome tests failed. Check connections and permissions.")
        print("Make sure you're running as root or with GPIO permissions.")

if __name__ == "__main__":
    main()
