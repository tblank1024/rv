# -*- coding: utf-8 -*-
"""
Notifications
-------------

Example showing how to add notifications to a characteristic and handle the responses.

Updated on 2019-07-03 by hbldh <henrik.blidh@gmail.com>

"""

from operator import truediv
import sys
import asyncio
import platform

from bleak import BleakClient
import atexit
import time
import os

import logging

logging.basicConfig()
logging.getLogger('BLEAK_LOGGING').setLevel(logging.DEBUG)

#CONSTANTS
DEV_MAC1 = 'F8:33:31:56:ED:16'
DEV_MAC2 = 'F8:33:31:56:FB:8E'
CHARACTERISTIC_UUID = '0000ffe1-0000-1000-8000-00805f9b34fb'          #GATT Characteristic UUID

#variables
LastMessage = ""
LastVolt = 0
LastAmps = 0



def notification_handler_battery(sender, data):
    """Simple notification handler which prints the data received.
    Note data from device comes back as binary array of data representing the data
    in a BCD format seperated by commas.  The end of record termination is \r.
    Data is comma seperated BCD ASCII values; Not necessarily in a fixed position but close
    CSV datafields are:
    1 - Battery voltage (assume 2 decimal positions)
    2 - Battery cell 1 status
    3 - Battery cell 2 status
    4 - Battery cell 3 status
    5 - Battery cell 4 status
    6 - Battery Temp in F
    7 - Battery Mgmnt Sys Temp in F
    8 - Current in amps +/-
    9 - Percent Battery full
    10 - Battery Status
    (Total number of bytes seems constant at 40 across 3 messsages)

    Each return provides 20 bytes in the following format (that changes a little depending on result values)
    4 bytes - providing the battery voltage 13.50 (note the decimal point is assumed)
    1 byte  - comma
    3 bytes - Battery cell 1 status  (don't know number meaning)
    1 byte  - comma
    3 bytes - Battery cell 2 status
    1 byte  - comma
    3 bytes - Battery cell 3 status
    1 byte  - comma
    3 bytes - Battery cell 4 status
    ************  new record starts here
    1 byte  - comma
    2 bytes - Battery Temp in F (Not sure of neg values)
    1 byte  - comma
    2 bytes - BMS in F (Not sure of neg values)
    1 byte  - comma
    1 byte  - current in amps +/-
    3 bytes - Percent battery full (0 - 100%)
    1 byte  - comma
    6 bytes - Status Code (all 0's is good)
    1 bytes - record termination char 0x0d CR
    ************  new record starts here
    1 byte  - record termination char 0x0a  LF
     """
    
    global LastMessage, LastAmps, LastVolt
    global fp
    
    # raw print of all data
    #print(" {0}: {1}".format(sender, data))

        
    if data[0] == 0x0a:                   # now sync'd to end of a record at start
        if len(LastMessage) == 40:          # end of complete record with 40 bytes
            """TimeString = str(time.time())
            while not TimeString:                   #prevents random null return
                TimeString = str(time.time())
            print(TimeString + ","+ LastMessage)
            fp.write(TimeString + ","+ LastMessage)
                """

            FieldData = LastMessage.split(",")

            CurTime = int(time.time())
            Volt    = int(FieldData[0])
            Temp    = int(FieldData[5])
            Amps    = int(FieldData[7])
            Full    = int(FieldData[8])
            Stat    = FieldData[9]

            if LastVolt == Volt and LastAmps == Amps:
                # No change from last measurement
                print("{},{},{},{},{},{}".format(CurTime, Volt, Temp, Amps,Full,Stat))
            else:
                print("{},{},{},{},{},{}<".format(CurTime, Volt, Temp, Amps,Full,Stat))
                fp.write("{},{},{},{},{},{}\n".format(CurTime, Volt, Temp, Amps,Full,Stat))


            LastVolt = Volt
            LastAmps = Amps

            """
            Volt = " + LastMessage[0:4])
            Cell1= " + LastMessage[5:8])
            Cell2= " + LastMessage[9:12])
            Cell3= " + LastMessage[13:16])
            Cell4= " + LastMessage[17:20])
            Temp = " + LastMessage[21:23])
            BMS  = " + LastMessage[24:26])
            Amps = " + LastMessage[27])
            Full = " + LastMessage[29:32])
            Stat = " + LastMessage[33:39])
            """

        #Reset Vars
        LastMessage = ""

    else:
        LastMessage += data.decode("utf-8")

        """
    hexdata = data.hex()
    print(hexdata)
    strdata = data[0:4].decode('utf-8')    
    print(strdata)
    """
    

 
    
    


#deptricated original from example
async def main1(address, char_uuid):
    async with BleakClient(address) as client:
        print(f"Connectted: {client.is_connected}")
        await client.start_notify(char_uuid, notification_handler_battery)
        while True:
            await asyncio.sleep(5.0)
        print(f"Disconnecting: {client.is_connected}")
        await client.stop_notify(char_uuid)

        

async def OneClient(address1, char_uuid):  # need unique address and service address for each  todo
    global fp

    #make sure BLE stack isn't hung on this MAC address
    stream = os.popen('bluetoothctl disconnect ' + address1)
    output = stream.read()
    print(output)
    time.sleep(2)

    client1 = BleakClient(address1)
    await client1.connect()
    print(f"Connectted: {client1.is_connected}")

    try:
        await client1.start_notify(char_uuid, notification_handler_battery)

        while True:
            await asyncio.sleep(5.0)
    finally: 
        
        fp.close()
        print(f"Disconnecting: {client1.is_connected}")       
        await client1.stop_notify(char_uuid)
        await client1.disconnect()  
        print(f"Disconnect2: {client1.is_connected}")
        

async def TwoClient(address1, address2, char_uuid):  # need unique address and service address for each  todo
    client1 = BleakClient(address1)
    await client1.connect()
    print(f"Connectted: {client1.is_connected}")

    client2 = BleakClient(address2)
    await client2.connect()
    print(f"Connectted: {client2.is_connected}")

    try:
        await client1.start_notify(char_uuid, notification_handler_battery)
        await client2.start_notify(char_uuid, notification_handler_battery)

        while True:
            await asyncio.sleep(5.0)
    except KeyboardInterrupt:
        print("Caught KyBd interrupt")
    finally: 
        print(f"Disconnecting all clients")
        await client1.stop_notify(char_uuid)
        await client1.disconnect()  
        await client2.stop_notify(char_uuid)
        await client2.disconnect()  
        print(f"Disconnect:  Clients 1 & 2 connected?: {client1.is_connected} {client2.is_connected}")


if __name__ == "__main__":
    fp = open("batterylog.txt","w")
    asyncio.run( OneClient(DEV_MAC1,CHARACTERISTIC_UUID ) )
    # asyncio.run( main3(DEV_MAC1, DEV_MAC2,CHARACTERISTIC_UUID )
