import os
import can

os.system('sudo ip link set can1 type can bitrate 250000')
os.system('sudo ifconfig can1 up')

can1 = can.interface.Bus(channel = 'can1', bustype = 'socketcan')# socketcan_native

msg = can.Message(is_extended_id=False, arbitration_id=0x123, data=[0, 1, 2, 3, 4, 5, 6, 7])
can1.send(msg)

os.system('sudo ifconfig can1 down')
