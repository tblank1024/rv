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

# Clean up any existing GPIO state first
try:
    Device.pin_factory.reset()
    print("GPIO state reset successfully")
except:
    print("GPIO reset failed (this is usually okay)")

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
            print("Red on; Blue off")
            blue_led.off()
            time.sleep(1)
            red_led.off()
            blue_led.on()
            print("Blue On;  Red off")
            time.sleep(1)
        
        red_led.on()
        blue_led.on()
        time.sleep(1)
        red_led.off()
        blue_led.off()
        print("+ LED test completed")
        time.sleep(5)

        # Brief buzzer test (comment out if too loud)
        print("Brief buzzer test (1 second)...")
        buzzer.on()
        time.sleep(1)
        buzzer.off()
        print("+ Buzzer test completed")
        time.sleep(5)
        return True
        
    except Exception as e:
        print(f"- Output test failed: {e}")
        return False

def test_inputs():
    """Test input devices (buttons, PIR sensor)"""
    print("\n=== Testing Input Devices ===")
    
    try:
        red_led  = LED(REDLEDOUT)
        blue_led = LED(BLUELEDOUT)
        # Test buttons
        red_button = Button(REDBUTTONIN, pull_up=True)
        blue_button = Button(BLUEBUTTONIN, pull_up=True)
        pir_sensor = InputDevice(PIRSENSORIN, pull_up=True)
        print("+ Input devices initialized")
        
        print("Testing inputs for 20 seconds...")
        print("Press red button (GPIO6) or blue button (GPIO13)")
        print("Move in front of PIR sensor (GPIO5)")
        
        start_time = time.time()
        while time.time() - start_time < 20:
            status = []
            if red_button.is_pressed:
                status.append("RED")
                red_led.on()
            else:
                red_led.off()
            if blue_button.is_pressed:
                status.append("BLUE")
                blue_led.on()
            else:
                blue_led.off()
            if not pir_sensor.is_active:    # With pull_up=True, is_active=False means movement detected
                status.append("PIR")
            
            if status:
                print(f"Active: {', '.join(status)}")
            
            time.sleep(0.1)
        
        #make sure all inputs toggled
        if "PIR" in status and "RED" in status and "BLUE" in status:
            print("+ All inputs toggled successfully")
        else:
            print("- Not all inputs toggled, check connections")
            return False
        return True
        
    except Exception as e:
        print(f"- Input test failed: {e}")
        return False

def test_inputs_with_active_state_false():
    """Test input devices using active_state=False approach"""
    print("\n=== Testing Input Devices with active_state=False ===")
    
    try:
        red_led  = LED(REDLEDOUT)
        blue_led = LED(BLUELEDOUT)
        
        # Try the cleaner active_state=False approach
        print("Attempting to initialize with active_state=False...")
        red_button = Button(REDBUTTONIN, pull_up=True, active_state=False)
        blue_button = Button(BLUEBUTTONIN, pull_up=True, active_state=False)
        pir_sensor = InputDevice(PIRSENSORIN, pull_up=True, active_state=False)
        print("+ Input devices initialized with active_state=False!")
        
        print("Testing inputs for 20 seconds...")
        print("Press red button (GPIO6) or blue button (GPIO13)")
        print("Move in front of PIR sensor (GPIO5)")
        print("With active_state=False, is_pressed/is_active should return True when activated")
        
        start_time = time.time()
        status = []
        while time.time() - start_time < 20:
            status = []
            if red_button.is_pressed:
                status.append("RED")
                red_led.on()
            else:
                red_led.off()
            if blue_button.is_pressed:
                status.append("BLUE")
                blue_led.on()
            else:
                blue_led.off()
            if pir_sensor.is_active:    # With active_state=False, is_active=True means movement detected
                status.append("PIR")
            
            if status:
                print(f"Active: {', '.join(status)}")
            
            time.sleep(0.1)
        
        print("+ active_state=False approach worked!")
        return True
        
    except Exception as e:
        print(f"- active_state=False approach failed: {e}")
        print("Falling back to pull_up=True with inverted logic...")
        return False

def main():
    print("Raspberry Pi 5 GPIO Test for Alarm System")
    print("=" * 45)
    
    # Test outputs first
    output_ok = test_outputs()
    
    # Try the cleaner active_state=False approach first
    active_state_ok = test_inputs_with_active_state_false()
    
    if not active_state_ok:
        # Fall back to the inverted logic approach
        input_ok = test_inputs()
    else:
        input_ok = True
    
    print("\n=== Test Summary ===")
    print(f"Output devices: {'+ PASS' if output_ok else '- FAIL'}")
    if active_state_ok:
        print(f"Input devices (active_state=False): {'+ PASS'}")
        print("You can use the cleaner active_state=False approach in alarm.py!")
    else:
        print(f"Input devices (inverted logic): {'+ PASS' if input_ok else '- FAIL'}")
        print("You'll need to use pull_up=True with inverted logic in alarm.py")
    
    if output_ok and input_ok:
        print("\nYour RPi 5 is ready for the alarm system.")
    else:
        print("\nSome tests failed. Check connections and permissions.")
        print("Make sure you're running as root or with GPIO permissions.")

if __name__ == "__main__":
    main()
