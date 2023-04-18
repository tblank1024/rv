# -*- coding: utf-8 -*-

from operator import truediv
import sys
import time 
import json
import asyncio
import platform

from bleak import BleakClient
import atexit
import time
import os
import paho.mqtt.client as mqtt
from pprint import pprint

import logging
import mqttclient
import random

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
Debug = 0



def notification_handler_battery(sender, data):
    """Simple notification handler which prints the data received.
    Note: data from device comes back as binary array of data representing the data
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
    
    global LastMessage, LastAmps, LastVolt, Debug
    global file_ptr
    
    # raw print of all data
    if Debug >1:
        #print(" {0}: {1} {2} {3}".format(sender, len(LastMessage), hex(data[0]), data))
        print(" {0} {1} {2} {3} decoded: {4} ".format(len(LastMessage), len(data), data[19], data, data.decode("utf-8")))

    LastMessage += data.decode("utf-8")
    if data[19] == 0x0A:
        if len(LastMessage) == 40:          # end of complete record with 40 bytes
            FieldData = LastMessage.split(",")
            CurTime = int(time.time())
            Volt    = float(FieldData[0])/100
            Temp    = int(FieldData[5])
            Amps    = int(FieldData[7])
            Full    = int(FieldData[8])
            Stat    = FieldData[9][0:6]

            #Now publish to MQTT           
            """  target topic copied from json file provides easy tag IDs
            "BATTERY_STATUS":{                         
                    "instance":1,
                    "name":"BATTERY_STATUS",
                    "DC_voltage":                                               "_var18Batt_voltage",
                    "DC_current":                                               "_var19Batt_current",
                    "State_of_charge":                                          "_var20Batt_charge",
                    "Status":                                                    ""},
            """ 
            #create dictionary with new data and publish
            AllData = {}
            AllData["instance"] = 1
            AllData["name"] = "BATTERY_STATUS"
            AllData["DC_voltage"] = Volt
            AllData["DC_current"] = Amps
            AllData["State_of_charge"] = Full
            AllData["Status"] = Stat
            mqttpubclient.pub(AllData)

            if Debug > 0:
                if LastVolt == Volt and LastAmps == Amps:
                    # No change from last measurement
                    print("{},{},{},{},{},{}".format(CurTime, Volt, Temp, Amps,Full,Stat))
                else:
                    print("{},{},{},{},{},{}<".format(CurTime, Volt, Temp, Amps,Full,Stat))
                    file_ptr.write("{},{},{},{},{},{}\n".format(CurTime, Volt, Temp, Amps,Full,Stat))
                LastVolt = Volt
                LastAmps = Amps


        #Reset Vars
        else:
            LastMessage = ""
        

async def OneClient(address1, char_uuid):  # need unique address and service address for each  todo
    global file_ptr

    #make sure BLE stack isn't hung on this MAC address
    print('OneClient BLE watcher starting')
    stream = os.popen('bluetoothctl disconnect ' + address1)
    output = stream.read()
    print(output)
    time.sleep(2)

    client1 = BleakClient(address1)
    try:
        await client1.connect()
        print(f"Connectted: {client1.is_connected}")
    except:
        print("BLE device not found; Exiting!")
        return

    try:
        await client1.start_notify(char_uuid, notification_handler_battery)
        while True:
            await asyncio.sleep(5.0)
    finally: 
        file_ptr.close()
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
    Debug = 1
    mqttpubclient = mqttclient.mqttclient("pub","localhost", 1883, "dgn_variables.json",'_var', 'RVC', Debug-1)
    if Debug > 0:
            file_ptr = open("batterylog.txt","w")
    asyncio.run( OneClient(DEV_MAC1,CHARACTERISTIC_UUID ) )
    