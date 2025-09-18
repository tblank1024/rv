import os
import can
import time

# can1 should already be configured and up
# os.system('sudo ip link set can1 type can bitrate 250000')
# os.system('sudo ifconfig can1 up')

try:
    can1 = can.interface.Bus(channel = 'can1', interface = 'socketcan')  # Updated API
    
    print("Sending test messages on can1...")
    
    # Send multiple test messages
    for i in range(20):
        msg = can.Message(is_extended_id=False, arbitration_id=0x123, data=[0, 1, 2, 3, 4, 5, 6, i])
        can1.send(msg)
        print(f"TX: Sent message {i+1}: {msg}")
        time.sleep(0.1)  # Small delay between messages
    
    can1.shutdown()
    print("Transmission complete!")
    
except Exception as e:
    print(f"Error: {e}")

# Don't bring down the interface for loopback testing
# os.system('sudo ifconfig can1 down')
