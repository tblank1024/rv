import os
import can

print("Starting CAN receiver on can0...")
can0 = can.interface.Bus(channel= 'can0', interface = 'socketcan')  # Updated API

print("Listening for messages... (Ctrl+C to stop)")
timeout = 5.0
for x in range(600):
    msg = can0.recv(timeout)  
    if msg is None:
        print(f'Rcvr: +++ Timeout {x+1}: no message.')
    else:
        print(f"Rcvr: Message {x+1}: {msg}")

