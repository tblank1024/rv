#!/usr/bin/env python3
"""
Real-time CAN loopback test script.
Sends a message on can1, then immediately checks for it on can0.
"""

import can
import time

def test_realtime_loopback():
    """Test sending and receiving messages in real-time"""
    print("Real-time CAN Loopback Test")
    print("===========================")
    
    try:
        # Open both buses
        print("Opening CAN interfaces...")
        can1 = can.interface.Bus(channel='can1', interface='socketcan')
        can0 = can.interface.Bus(channel='can0', interface='socketcan') 
        
        print("Interfaces opened successfully!")
        print("Starting real-time loopback test...\n")
        
        success_count = 0
        total_tests = 5
        
        for i in range(total_tests):
            print(f"Test {i+1}/{total_tests}:")
            
            # Create test message
            test_data = [0x10, 0x20, 0x30, 0x40, 0x50, 0x60, 0x70, i]
            msg_to_send = can.Message(
                is_extended_id=False,
                arbitration_id=0x123,
                data=test_data
            )
            
            # Send message
            print(f"  TX: Sending ID=0x{msg_to_send.arbitration_id:03X}, Data={msg_to_send.data.hex().upper()}")
            can1.send(msg_to_send)
            
            # Try to receive immediately  
            print(f"  RX: Listening for message...")
            received_msg = can0.recv(timeout=1.0)
            
            if received_msg is None:
                print(f"  TIMEOUT: No message received")
            else:
                print(f"  SUCCESS: Received ID=0x{received_msg.arbitration_id:03X}, Data={received_msg.data.hex().upper()}")
                
                # Verify it matches
                if (received_msg.arbitration_id == msg_to_send.arbitration_id and 
                    received_msg.data == msg_to_send.data):
                    print(f"  VERIFIED: Message matches perfectly!")
                    success_count += 1
                else:
                    print(f"  MISMATCH: Received message doesn't match sent message")
            
            print()  # Empty line between tests
            time.sleep(0.5)  # Brief pause between tests
        
        # Cleanup
        can0.shutdown()
        can1.shutdown()
        
        # Results
        print("=" * 40)
        print("FINAL RESULTS")
        print("=" * 40)
        print(f"Tests completed: {total_tests}")
        print(f"Successful:      {success_count}")
        print(f"Success rate:    {(success_count/total_tests)*100:.1f}%")
        
        if success_count == total_tests:
            print("PERFECT: All messages successfully looped back!")
            return True
        elif success_count > 0:
            print("PARTIAL: Some messages successfully looped back.")
            return True
        else:
            print("FAILED: No messages successfully looped back.")
            return False
            
    except Exception as e:
        print(f"Error during test: {e}")
        return False

if __name__ == "__main__":
    success = test_realtime_loopback()
    exit_code = 0 if success else 1
    print(f"\nExit code: {exit_code}")
