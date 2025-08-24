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
import subprocess
import re

logging.basicConfig()
logging.getLogger('BLEAK_LOGGING').setLevel(logging.DEBUG)

def configure_bluetooth_adapters():
    """
    Comprehensive Bluetooth adapter configuration.
    Ensures USB adapter is enabled and built-in adapter is disabled.
    Returns True if configuration was successful.
    """
    print("=== Comprehensive Bluetooth Configuration ===")
    
    try:
        # Stop bluetooth service for clean configuration
        print("Stopping bluetooth service for clean configuration...")
        subprocess.run(['sudo', 'systemctl', 'stop', 'bluetooth'], capture_output=True)
        time.sleep(2)
        
        # Unblock all bluetooth devices
        print("Unblocking all Bluetooth devices...")
        subprocess.run(['sudo', 'rfkill', 'unblock', 'bluetooth'], capture_output=True)
        
        # Check what adapters exist
        print("Checking available adapters...")
        result = subprocess.run(['hciconfig'], capture_output=True, text=True)
        
        has_hci0 = 'hci0:' in result.stdout
        has_hci1 = 'hci1:' in result.stdout
        
        print(f"Built-in adapter (hci0): {'Found' if has_hci0 else 'Not found'}")
        print(f"USB adapter (hci1): {'Found' if has_hci1 else 'Not found'}")
        
        # Disable built-in adapter if it exists
        if has_hci0:
            print("Disabling built-in adapter (hci0)...")
            subprocess.run(['sudo', 'hciconfig', 'hci0', 'down'], capture_output=True)
        
        # Configure USB adapter if it exists
        if has_hci1:
            print("Configuring USB adapter (hci1)...")
            # Down first to reset
            subprocess.run(['sudo', 'hciconfig', 'hci1', 'down'], capture_output=True)
            time.sleep(1)
            # Bring it up
            subprocess.run(['sudo', 'hciconfig', 'hci1', 'up'], capture_output=True)
            time.sleep(2)
        else:
            print("[ERROR] USB adapter (hci1) not found - check USB connection")
            return False
        
        # Restart bluetooth service
        print("Restarting bluetooth service...")
        subprocess.run(['sudo', 'systemctl', 'start', 'bluetooth'], capture_output=True)
        time.sleep(3)
        
        # Force disable hci0 again after service restart (it tends to come back up)
        if has_hci0:
            print("Force disabling hci0 again (post-service restart)...")
            subprocess.run(['sudo', 'hciconfig', 'hci0', 'down'], capture_output=True)
            time.sleep(1)
        
        # Verify final configuration
        result = subprocess.run(['hciconfig'], capture_output=True, text=True)
        
        hci0_running = has_hci0 and 'hci0:' in result.stdout and 'UP RUNNING' in result.stdout
        hci1_running = has_hci1 and 'hci1:' in result.stdout and 'UP RUNNING' in result.stdout
        
        print("=== Configuration Results ===")
        if has_hci0:
            print(f"Built-in adapter (hci0): {'RUNNING (conflict!)' if hci0_running else 'DISABLED (good)'}")
        if has_hci1:
            print(f"USB adapter (hci1): {'RUNNING (good)' if hci1_running else 'FAILED'}")
        
        success = hci1_running and (not has_hci0 or not hci0_running)
        print(f"Overall configuration: {'SUCCESS' if success else 'PARTIAL SUCCESS' if hci1_running else 'FAILED'}")
        
        return hci1_running  # Return success if hci1 is running, even if hci0 is still up
        
    except Exception as e:
        print(f"[ERROR] Configuration failed: {e}")
        return False


def get_bluetooth_adapter():
    """
    Detect available Bluetooth adapters and return the preferred one.
    Prioritizes USB adapters over built-in UART adapters.
    """
    print("=== Bluetooth Adapter Detection ===")
    
    try:
        # Run hciconfig to get adapter info
        result = subprocess.run(['hciconfig'], capture_output=True, text=True)
        if result.returncode != 0:
            print("ERROR: Could not run hciconfig - is bluetoothctl installed?")
            return None
            
        output = result.stdout
        print("Current adapter status:")
        print(output)
        print("=" * 40)
        
        adapters = []
        
        # Parse hciconfig output block by block
        adapter_blocks = output.split('\n\n')
        for block in adapter_blocks:
            if not block.strip() or 'hci' not in block:
                continue
                
            lines = block.split('\n')
            adapter_name = None
            bus_type = 'UNKNOWN'
            is_up = False
            is_running = False
            
            for line in lines:
                line = line.strip()
                if line.startswith('hci') and ':' in line:
                    # Extract adapter name from first line
                    adapter_name = line.split(':')[0].strip()
                elif 'Bus:' in line:
                    if 'USB' in line:
                        bus_type = 'USB'
                    elif 'UART' in line:
                        bus_type = 'UART'
                elif 'UP' in line and 'RUNNING' in line:
                    is_up = True
                    is_running = True
                elif 'DOWN' in line:
                    is_up = False
            
            if adapter_name:
                adapters.append((adapter_name, bus_type, is_up, is_running))
                status = "UP and RUNNING" if (is_up and is_running) else "DOWN or not running"
                print(f"Found adapter: {adapter_name} (Bus: {bus_type}, Status: {status})")
        
        if not adapters:
            print("ERROR: No Bluetooth adapters found!")
            return None
        
        print(f"\nTotal adapters found: {len(adapters)}")
        
        # Prioritize USB adapters that are running
        running_usb_adapters = [a for a in adapters if a[1] == 'USB' and a[2] and a[3]]
        if running_usb_adapters:
            selected = running_usb_adapters[0][0]
            print(f"[OK] Selected running USB adapter: {selected}")
            return selected
        
        # Check if USB adapter exists but isn't running
        usb_adapters = [a for a in adapters if a[1] == 'USB']
        if usb_adapters:
            selected = usb_adapters[0][0]
            print(f"[WARN] USB adapter found but not running: {selected}")
            return selected
            
        # Last resort - any running adapter
        running_adapters = [a for a in adapters if a[2] and a[3]]
        if running_adapters:
            selected = running_adapters[0][0]
            print(f"[WARN] Selected fallback adapter: {selected} (type: {running_adapters[0][1]})")
            return selected
        
        print("[ERROR] No suitable Bluetooth adapters found!")
        return None
        
    except Exception as e:
        print(f"ERROR in Bluetooth adapter detection: {e}")
        return None

#CONSTANTS
DEV_MAC1 = 'F8:33:31:56:ED:16'
DEV_MAC2 = 'F8:33:31:56:FB:8E'
CHARACTERISTIC_UUID = '0000ffe1-0000-1000-8000-00805f9b34fb'          #GATT Characteristic UUID

# Bluetooth adapter configuration - prioritize USB adapter
PREFERRED_ADAPTER = "hci1"  # USB adapter
FALLBACK_ADAPTER = "hci0"   # Built-in adapter (fallback only)

#global variables
LastMessage = ""
MsgCount = 0  # Initialize MsgCount
LastVolt = 0
LastAmps = 0
Debug = 0
SELECTED_ADAPTER = None  # Will be set at startup
DataReceived = False  # Flag to log "Receiving Battery Data" only once

def _MqttConnect():
    global MqttPubClient

    #Keep trying to connect to mqtt broker until it is up
    while True:
        try:
            print('Trying connect to mqtt broker')
            MqttPubClient = mqttclient.mqttclient("pub","localhost", 1883, '_var', 'RVC', Debug-1)
            break
        except:
            time.sleep(10)


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
    
    global LastMessage, LastAmps, LastVolt, Debug, MsgCount
    global file_ptr, DataReceived
    
    # raw print of all data
    if Debug > 2:
        #print(" {0}: {1} {2} {3}".format(sender, len(LastMessage), hex(data[0]), data))
        if len(data) == 20:
            print(" {0} {1} {2} {3} decoded: {4} ".format(len(LastMessage), len(data), data[19], data, data.decode("utf-8")))
        else:
            print(" {0} {1} {2} {3} decoded: {4} ".format(len(LastMessage), len(data), data[0], data, data.decode("utf-8")))

    LastMessage += data.decode("utf-8")
    if data[len(data)-1] == 0x0A:  # end of record with 0x0A LF
        if len(LastMessage) < 45:          # end of complete record with 40 or so bytes
            # Clean the message and split by comma
            cleaned_message = LastMessage.strip().replace('\n', '').replace('\r', '')
            FieldData = cleaned_message.split(",")
            
            # Validate we have enough fields
            if len(FieldData) < 9:
                if Debug > 1:
                    print(f"Warning: Incomplete data - only {len(FieldData)} fields: {cleaned_message}")
                LastMessage = ""
                return
            
            # Log "Receiving Battery Data" only once when first valid data arrives
            if not DataReceived:
                print("Receiving Battery Data")
                DataReceived = True
                
            try:
                CurTime = int(time.time())
                Volt    = float(FieldData[0])/100
                Temp    = int(FieldData[5])
                
                # Debug: Print field parsing details
                if Debug > 2:
                    print(f"Raw message: {LastMessage}")
                    print(f"Cleaned message: {cleaned_message}")
                    print(f"Field 7 (current): '{FieldData[7]}' = {int(FieldData[7])}")
                    print(f"Before 2x multiplication: {int(FieldData[7])}")
                
                Amps    = 2 * int(FieldData[7])  # 2x since only monitoring 1 of 2 batteries
                
                if Debug > 2:
                    print(f"After 2x multiplication: {Amps}")
                
                #NOTE: positive amps => charging and negative amps => discharging
                Full    = int(FieldData[8])
                Stat    = FieldData[9][0:6] if len(FieldData) > 9 else "000000"

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
                AllData["timestamp"] = CurTime
                
                if Debug < 2:
                    (RtnCode, MsgCount) = MqttPubClient.pub(AllData)
                    if RtnCode != 0:
                        print("MQTT pubclient error = ", RtnCode)
                        _MqttConnect()  #wait until reconnected to mqtt broker
                if Debug > 0:
                    if MsgCount % 20 == 0:
                        print("Time     \tVolt\tTemp\tAmps\tFull\tStat")
                    if LastVolt == Volt and LastAmps == Amps:
                        # No change from last measurement
                        print("{}\t{}\t{}\t{}\t{}\t{}".format(CurTime, Volt, Temp, Amps,Full,Stat))
                    else:
                        print("{}\t{}\t{}\t{}\t{}\t{}<".format(CurTime, Volt, Temp, Amps,Full,Stat))
                        if 'file_ptr' in globals():
                            file_ptr.write("{},{},{},{},{},{}\n".format(CurTime, Volt, Temp, Amps,Full,Stat))
                    LastVolt = Volt
                    LastAmps = Amps
                
            except (ValueError, IndexError) as e:
                if Debug > 0:
                    print(f"Error parsing battery data: {e}")
                    print(f"Raw message: '{LastMessage}'")
                    print(f"Cleaned message: '{cleaned_message}'")
                    print(f"Fields: {FieldData}")
                LastMessage = ""
                return


        #Reset Vars
        else:
            LastMessage = ""
    
        

async def OneClient(address1, char_uuid):  # need unique address and service address for each  todo
    global file_ptr

    async def cleanup():
        print(f"Disconnecting: {client1.is_connected}")
        await client1.stop_notify(char_uuid)
        await client1.disconnect()
        print(f"Disconnect client1: {client1.is_connected}")
        if Debug > 0:
            file_ptr.close()

    #make sure BLE stack isn't hung on this MAC address
    print('=== OneClient BLE Connection Starting ===')
    print(f"Target device MAC: {address1}")
    print(f"Selected Bluetooth adapter: {SELECTED_ADAPTER}")
    
    if Debug > 1:  # Only show bluetoothctl output in verbose debug mode
        stream = os.popen('bluetoothctl disconnect ' + address1)
        output = stream.read()
        print('Bluetoothctl disconnect output:', output)
    else:
        # Silent cleanup
        os.popen('bluetoothctl disconnect ' + address1).read()
    time.sleep(2)

    connection_attempts = 0
    max_attempts = 10
    
    while connection_attempts < max_attempts:
        connection_attempts += 1
        print(f"\n--- Connection attempt {connection_attempts}/{max_attempts} ---")
        
        # Use the globally selected adapter
        if SELECTED_ADAPTER:
            print(f"Creating BleakClient with adapter: {SELECTED_ADAPTER}")
            client1 = BleakClient(address1, adapter=SELECTED_ADAPTER)
        else:
            print("Creating BleakClient with system default adapter")
            client1 = BleakClient(address1)
            
        try:
            print(f"Attempting to connect to {address1}...")
            await client1.connect()
            atexit.register(cleanup)
            print(f"[OK] OneClient Connected: {client1.is_connected}")
            
            # Verify which adapter we're actually using
            try:
                # Try to get device info to confirm connection
                if hasattr(client1, '_device'):
                    print(f"Connected device info: {client1._device}")
                if hasattr(client1, '_backend') and hasattr(client1._backend, '_adapter'):
                    print(f"Backend adapter: {client1._backend._adapter}")
            except Exception as e:
                print(f"Could not get detailed connection info: {e}")
                
            break
            
        except Exception as e:
            print(f"[ERROR] Connection attempt {connection_attempts} failed: {e}")
            
            if connection_attempts < max_attempts:
                print("Cleaning up and retrying...")
                time.sleep(5)
                
                # Try to disconnect any hanging connections
                stream = os.popen('bluetoothctl disconnect ' + address1)
                output = stream.read()
                if Debug > 1:
                    print('Bluetoothctl cleanup output:', output)
                    
                # If we're having trouble and this is a later attempt, try reconfiguring
                if connection_attempts >= 3:
                    print("Multiple failures - attempting to reconfigure Bluetooth...")
                    try:
                        subprocess.run(['sudo', 'hciconfig', 'hci0', 'down'], capture_output=True)
                        subprocess.run(['sudo', 'hciconfig', 'hci1', 'up'], capture_output=True)
                        time.sleep(3)
                    except Exception as config_e:
                        print(f"Could not reconfigure adapters: {config_e}")
            else:
                print(f"[ERROR] All {max_attempts} connection attempts failed!")
                raise e

    print(f"Starting notifications on characteristic: {char_uuid}")
    await client1.start_notify(char_uuid, notification_handler_battery)
    print("[OK] Notifications started successfully")
    
    print("Entering main loop - waiting for battery data...")
    while True:
        await asyncio.sleep(5.0)
    
        

async def TwoClient(address1, address2, char_uuid):  # need unique address and service address for each  todo
    #note: TwoClient is not as resiliant as the OneClient version;  could be updated to be more like OneClient todo
    if SELECTED_ADAPTER:
        client1 = BleakClient(address1, adapter=SELECTED_ADAPTER)
        client2 = BleakClient(address2, adapter=SELECTED_ADAPTER)
    else:
        client1 = BleakClient(address1)
        client2 = BleakClient(address2)
        
    await client1.connect()
    print(f"Connectted 1: {client1.is_connected}")

    await client2.connect()
    print(f"Connectted 2: {client2.is_connected}")

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
        print(f"Disconnect:  Clients 1 & 2 connected?: {client1.is_connected} {client2.is_connected}")



if __name__ == "__main__":
    # Debug values
    # 0 - Silently transmists data to mqtt
    # 1 - logs all data to batterylot.txt (overwrites previous log) and prints output
    # 2 - does not log to mqtt and all of #1
    # 3 - #2 plus outputs raw packets received
    
    Debug = 0  # Production mode
    print("=== bat2mqtt Starting ===")
    print(f"Debug level: {Debug}")
    print(f"Target device MAC: {DEV_MAC1}")
    print(f"Characteristic UUID: {CHARACTERISTIC_UUID}")

    # Detect and select the best Bluetooth adapter
    print("\n=== Bluetooth Adapter Configuration ===")
    
    # First, try to detect current state
    SELECTED_ADAPTER = get_bluetooth_adapter()
    
    # If no USB adapter is running, try comprehensive configuration
    if not SELECTED_ADAPTER or SELECTED_ADAPTER != 'hci1':
        print("\nUSB adapter not optimal - attempting comprehensive configuration...")
        if configure_bluetooth_adapters():
            print("Configuration successful - re-detecting adapters...")
            SELECTED_ADAPTER = get_bluetooth_adapter()
        else:
            print("Configuration failed - proceeding with current state...")
    
    # Force preference for hci1 if available
    if SELECTED_ADAPTER != 'hci1':
        print("Checking for USB adapter (hci1) availability...")
        try:
            result = subprocess.run(['hciconfig', 'hci1'], capture_output=True, text=True)
            if result.returncode == 0:
                print("Found hci1 (USB adapter)")
                if 'UP RUNNING' in result.stdout:
                    SELECTED_ADAPTER = 'hci1'
                    print("[OK] Forcing use of USB adapter: hci1")
                else:
                    print("[WARN] hci1 exists but is not UP RUNNING")
            else:
                print("[INFO] hci1 (USB adapter) not found")
        except Exception as e:
            print(f"[WARN] Error checking hci1: {e}")
    
    
    if SELECTED_ADAPTER:
        print(f"[OK] Final selected adapter: {SELECTED_ADAPTER}")
        
        # Verify the selected adapter is actually working
        try:
            result = subprocess.run(['hciconfig', SELECTED_ADAPTER], capture_output=True, text=True)
            if result.returncode == 0:
                print(f"Adapter status for {SELECTED_ADAPTER}:")
                print(result.stdout)
                if 'UP RUNNING' in result.stdout:
                    print(f"[OK] Adapter {SELECTED_ADAPTER} is UP and RUNNING")
                else:
                    print(f"[WARN]  Adapter {SELECTED_ADAPTER} is not in optimal state")
            else:
                print(f"[ERROR] Could not query adapter {SELECTED_ADAPTER}")
        except Exception as e:
            print(f"[WARN]  Could not verify adapter status: {e}")
    else:
        print("[ERROR] CRITICAL: No suitable Bluetooth adapter found!")
        print("Please ensure:")
        print("1. USB Bluetooth adapter is connected")
        print("2. Run the configure_bluetooth.sh script")
        print("3. Bluetooth services are running")
        sys.exit(1)

    # Initialize file_ptr
    file_ptr = None

    print(f"\nWaiting 10 seconds for MQTT broker to start...")
    time.sleep(10)  # wait for mqtt broker to start:
    
    if Debug < 2:       #only pub to mqtt if debug is less than 2
        try:
            print("Connecting to MQTT broker...")
            _MqttConnect()
            print("[OK] MQTT connection established")
        except Exception as e:
            print(f"[ERROR] MQTT connection failed: {e}")
            if Debug > 0:
                print("Continuing in debug mode without MQTT...")
            else:
                print("MQTT is required for normal operation. Set Debug > 0 to continue without MQTT.")
                sys.exit(1)

    if Debug > 0:
        try:
            file_ptr = open("battery_raw.log","w")
            print("[OK] Opened log file: battery_raw.log")
        except Exception as e:
            print(f"[WARN]  Failed to open log file: {e}")
    
    print(f"\n=== Starting Bluetooth Connection ===")
    print(f"Connecting to device: {DEV_MAC1}")
    print(f"Using adapter: {SELECTED_ADAPTER}")
    
    try:
        asyncio.run( OneClient(DEV_MAC1,CHARACTERISTIC_UUID ) )
    except KeyboardInterrupt:
        print("\n[STOP] Keyboard interrupt received - shutting down gracefully")
    except Exception as e:
        print(f"[ERROR] Bluetooth connection failed: {e}")
        print("\nTroubleshooting steps:")
        print("1. Verify the Bluetooth device is powered on and in range")
        print("2. Check that the MAC address is correct:", DEV_MAC1)
        print("3. Run configure_bluetooth.sh to ensure proper adapter configuration")
        print("4. Try running with Debug = 1 for more detailed output")
        sys.exit(1)
