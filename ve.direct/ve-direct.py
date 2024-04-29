import serial
import time
import threading
from  rvglue import MQTTClient
from rvglue import MasterDict



# Victron protocol dictionary sets
charger_status = {
    "0": "Off",
    "1": "Low power (MPPT not used)",
    "2": "Fault",
    "3": "Bulk",
    "4": "Absorption",
    "5": "Float",
    "6": "Storage (MPPT not used)",
    "7": "Equalize (manual)",
    "9": "Inverting (MPPT not used)",
    "11": "Power supply (MPPT not used)",
    "245": "Starting-up",
    "246": "Repeated absorption (MPPT not used)",
    "247": "Auto equalize",
    "248": "BatterySafe (MPPT not used)",
    "252": "External control"
}

mppt_status = {
    "0": "Off",
    "1": "Voltage or current limited",
    "2": "MPPT active"
}

error_status = {
    "0": "No error",
    "2": "Battery voltage too high",
    "17": "Charger temperature too high",
    "18": "Charger over current",
    "19": "Charger current reversed",
    "20": "Bulk time limit exceeded",
    "21": "Current sensor issue (sensor bias/sensor broken)",
    "26": "Terminals overheated",
    "28": "Converter issue (dual converter models only)",
    "33": "Input voltage too high (solar panel)",
    "34": "Input current too high (solar panel)",
    "38": "Input shutdown (due to excessive battery voltage)",
    "39": "Input shutdown (due to current flow during off mode)",
    "65": "Lost communication with one of devices",
    "66": "Synchronised charging device configuration issue",
    "67": "BMS connection lost",
    "116": "Factory calibration data lost",
    "117": "Invalid/incompatible firmware",
    "119": "User settings invalid"
}
    
def decode_ve_direct_message(data, debug):
    # VE.Direct message decoding logic
    lst = str(data).split('\\t')
    if len(lst) != 2:
        # ignore non-variable updates e.g. history data
        return None
    lst[0] = lst[0].lstrip("b'")
    lst[1] = lst[1].rstrip("\\r\\n'")
    decoded_data = {'op': lst[0]}
    match lst[0]:
        case 'V':            
            decoded_data.update({'value': 'Batttery(V)= ' + str(float(lst[1])/1000)})
        case 'VPV':                        
            decoded_data.update({'value': 'Panel(V)=    ' + str(float(lst[1])/1000)})
        case 'I':
            decoded_data.update({'value': 'Batttery(I)= ' + str(float(lst[1])/1000)})
        case 'IL':
            decoded_data.update({'value': 'Load(I)=     ' + str(float(lst[1])/1000)})
        case 'PPV':
            decoded_data.update({'value': 'Panel(W)=    ' + str(float(lst[1]))})
        case 'CS':
            if lst[1] in charger_status:
                decoded_data.update({'value': 'Charger State= ' + charger_status[lst[1]]})
            else:
                decoded_data.update({'value': "Unknown CS code " + lst[1]})
        case 'MPPT':
            if lst[1] in mppt_status:
               decoded_data.update({'value': 'MPPT State= ' + mppt_status[lst[1]]})
            else:
                decoded_data.update({'value': 'MPPT State= ' + "Unknown MPPT code " + lst[1]})
        case 'ERR':
            if lst[1] == '0':       # No error so don't bother reporting
                decoded_data = None
            elif lst[1] in error_status:
                decoded_data.update({'value': 'ERROR= ' + error_status[lst[1]]})
            else:
                decoded_data.update({'value': "Unknown ERR code " + lst[1]})
        case _:  # Default case
            if debug > 1:
                print(f"Cmd not tracked: {lst[0]} {lst[1]}")
                decoded_data.update({'value': 'Cmd not tracked: ' + lst[0] + ' ' + lst[1]})
            else:
                decoded_data = None
    return decoded_data

def read_serial_data(ser, debug):
    try:
        while True:
            data = ser.readline()
            if data:
                #print(f"Received data: {data}")
                decoded_data = decode_ve_direct_message(data, debug)
                if decoded_data != None:
                    #print(decoded_data['value'])
                    #Update Solar record dictionary in MasterDict
                    MasterDict['SOLAR_CONTROLLER_STATUS/1'][decoded_data['op']] = decoded_data['value']
                                        
    except KeyboardInterrupt:
        print("Thread terminated.")

def InitializeSolarMQTTRecord(Client):
    #Initialize the Solar record dictionary in MasterDict and update MQTT
    MasterDict['SOLAR_CONTROLLER_STATUS/1']['VPV'] =    -1
    MasterDict['SOLAR_CONTROLLER_STATUS/1']['PPW'] =    -1
    MasterDict['SOLAR_CONTROLLER_STATUS/1']['V'] =      -1
    MasterDict['SOLAR_CONTROLLER_STATUS/1']['I'] =      -1
    MasterDict['SOLAR_CONTROLLER_STATUS/1']['IL'] =     -1
    MasterDict['SOLAR_CONTROLLER_STATUS/1']['CS'] =     'OFF'
    MasterDict['SOLAR_CONTROLLER_STATUS/1']['MPPT'] =   'OFF'
    MasterDict['SOLAR_CONTROLLER_STATUS/1']['ERR'] =    'No Error'
    MasterDict['SOLAR_CONTROLLER_STATUS/1']['timestamp'] = time.time()
    Client.pub(MasterDict['SOLAR_CONTROLLER_STATUS/1'])

def main(serial_port:str, baud_rate:int, mode:str, broker:str, port:int, varprefix:str, mqttTopic:str, debug:int)->None:

    #setup MQTT client
    RVC_Client = MQTTClient(mode,broker, port, varprefix, mqttTopic, debug-1)

    #Initialize the Solar record dictionary in MasterDict and pub to MQTT
    InitializeSolarMQTTRecord(RVC_Client)

    # Open the serial port
    try:
        ser = serial.Serial(serial_port, baud_rate, timeout=1, inter_byte_timeout=0.1)
        if debug > 0:
            print(f"VE-Direct serial port {serial_port} opened successfully.")
    except Exception as e:
        print(f"Failed to open serial port: {e}")
        return
    try:
        # Start a separate thread for reading serial data
        thread = threading.Thread(target=read_serial_data, args=(ser, debug,))
        thread.start()
        print(f"VE-Direct/Solar to MQTT Running")
        # Main loop
        while True:
            #update MQTT record every 2 seconds
            time.sleep(2) 
            MasterDict['SOLAR_CONTROLLER_STATUS/1']['timestamp'] = time.time()
            RVC_Client.pub(MasterDict['SOLAR_CONTROLLER_STATUS/1'])
            if debug > 0:
                print(MasterDict['SOLAR_CONTROLLER_STATUS/1'])
                print('---------------------------------------------------------------------------------------------')

    except KeyboardInterrupt:
        print("Program terminated by user.")
    finally:
        # Close the serial port and wait for the thread to finish
        ser.close()
        thread.join()
        print("Serial port closed.")

if __name__ == "__main__":

    main(
        serial_port='/dev/ttyAMA0',
        baud_rate=19200,
        mode='pub',
        broker='localhost', 
        port=1883, 
        varprefix='_var', 
        mqttTopic='RVC', 
        debug=0,    # 0 - no debug, 1 - print MQTT record, 2 - print MQTT record, all serial data, and rvglue debug
    )
