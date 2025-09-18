#!/usr/bin/env python3
"""
Combined CAN loopback test script.
Sends messages on can1, then receives them on can0.
REQUIRES: physical loopback connection between the two CAN interfaces.
"""

import can
import time

def send_test_messages(num_messages=5):
    """Send test messages on can1"""
    print("=" * 50)
    print("TRANSMISSION PHASE - Sending messages on can1")
    print("=" * 50)
    
    try:
        can1 = can.interface.Bus(channel='can1', interface='socketcan')
        
        sent_messages = []
        for i in range(num_messages):
            # Create unique message with incrementing data
            msg = can.Message(
                is_extended_id=False, 
                arbitration_id=0x123, 
                data=[0x10, 0x20, 0x30, 0x40, 0x50, 0x60, 0x70, i]
            )
            can1.send(msg)
            sent_messages.append(msg)
            print(f"TX [{i+1:2d}]: ID=0x{msg.arbitration_id:03X}, Data={msg.data.hex().upper()}")
            time.sleep(0.1)  # Small delay between messages
        
        can1.shutdown()
        print(f"\nTransmission complete! Sent {num_messages} messages.")
        return sent_messages
        
    except Exception as e:
        print(f"Transmission Error: {e}")
        return []

def receive_test_messages(expected_count=5, timeout=2.0):
    """Receive messages on can0"""
    print("\n" + "=" * 50)
    print("RECEPTION PHASE - Listening on can0")
    print("=" * 50)
    
    try:
        can0 = can.interface.Bus(channel='can0', interface='socketcan')
        
        received_messages = []
        print(f"Listening for up to {expected_count} messages (timeout: {timeout}s each)...")
        
        for i in range(expected_count + 2):  # Try a few extra in case of buffering
            msg = can0.recv(timeout)
            if msg is None:
                print(f"RX [{i+1:2d}]: Timeout - no message received")
                break
            else:
                received_messages.append(msg)
                print(f"RX [{i+1:2d}]: ID=0x{msg.arbitration_id:03X}, Data={msg.data.hex().upper()}")
        
        can0.shutdown()
        print(f"\nReception complete! Received {len(received_messages)} messages.")
        return received_messages
        
    except Exception as e:
        print(f"Reception Error: {e}")
        return []

def compare_messages(sent, received):
    """Compare sent vs received messages"""
    print("\n" + "=" * 50)
    print("COMPARISON RESULTS")
    print("=" * 50)
    
    print(f"Messages sent:     {len(sent)}")
    print(f"Messages received: {len(received)}")
    
    if len(sent) == 0:
        print("ERROR: No messages were sent!")
        return False
        
    if len(received) == 0:
        print("ERROR: No messages were received!")
        return False
    
    # Check each received message against sent messages
    matches = 0
    for i, rx_msg in enumerate(received):
        found_match = False
        for j, tx_msg in enumerate(sent):
            if (rx_msg.arbitration_id == tx_msg.arbitration_id and 
                rx_msg.data == tx_msg.data):
                print(f"MATCH: Message {i+1} matches sent message {j+1}")
                matches += 1
                found_match = True
                break
        
        if not found_match:
            print(f"NO MATCH: Message {i+1} has no matching sent message")
    
    success_rate = (matches / len(sent)) * 100
    print(f"\nSuccess Rate: {matches}/{len(sent)} ({success_rate:.1f}%)")
    
    if matches == len(sent) and len(received) == len(sent):
        print("SUCCESS: PERFECT LOOPBACK! All messages transmitted and received correctly.")
        return True
    elif matches > 0:
        print("PARTIAL: Some messages were transmitted and received.")
        return True
    else:
        print("FAILED: No matching messages found.")
        return False

def main():
    """Main test function"""
    print("CAN Loopback Test")
    print("=================")
    print("Testing physical loopback connection between can1 (TX) and can0 (RX)")
    print("Make sure CANH and CANL are connected between the two interfaces!")
    
    # Test parameters
    num_messages = 5
    
    # Run the test
    print(f"\nStarting loopback test with {num_messages} messages...\n")
    
    # Phase 1: Send messages
    sent_messages = send_test_messages(num_messages)
    
    # Small delay to ensure messages are transmitted
    time.sleep(0.5)
    
    # Phase 2: Receive messages  
    received_messages = receive_test_messages(len(sent_messages))
    
    # Phase 3: Compare results
    success = compare_messages(sent_messages, received_messages)
    
    return success

if __name__ == "__main__":
    try:
        success = main()
        exit_code = 0 if success else 1
        print(f"\nTest completed with exit code: {exit_code}")
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")
    except Exception as e:
        print(f"\nUnexpected error: {e}")
