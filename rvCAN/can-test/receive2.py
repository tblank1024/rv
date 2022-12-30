import os
import can


can0 = can.interface.Bus(channel = 'can0', bustype = 'socketcan')# socketcan_nativewdocker

#msg = can.Message(arbitration_id=0x123, data=[0, 1, 2, 3, 4, 5, 6, 7], extended_id=False)
for x in range(600):
    msg = can0.recv(10.0)
    if msg is None:
        print('+++ Timeout occurred, no message.')
    else:
        print (msg)

