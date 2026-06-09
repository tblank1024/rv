import serial
import sys
import time
import threading
from  rvglue import MQTTClient
from rvglue import MasterDict

_last_serial_ts = [0.0]  # updated each time a valid frame is decoded

# Candidate ports in priority order; /dev/ttyAMA0 is the Pi5 UART the solar controller is wired to.
_CANDIDATE_PORTS = ['/dev/ttyAMA0', '/dev/ttyAMA10', '/dev/ttyAMA1', '/dev/ttyS0', '/dev/ttyUSB0']


def find_serial_port(baud_rate):
    """Return the first candidate port that opens successfully, or None."""
    for port in _CANDIDATE_PORTS:
        try:
            s = serial.Serial(port, baud_rate, timeout=0.1)
            s.close()
            return port
        except (serial.SerialException, FileNotFoundError, PermissionError):
            pass
    return None



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
    # Strip embedded control/non-printable characters from serial noise
    lst[1] = ''.join(c for c in lst[1] if c.isprintable())
    decoded_data = {'op': lst[0]}
    match lst[0]:
        case 'V':            
            decoded_data.update({'value': float(lst[1])/1000})
        case 'VPV':                        
            decoded_data.update({'value': 'Panel(V)=    ' + str(float(lst[1])/1000)})
        case 'I':
            decoded_data.update({'value': float(lst[1])/1000})
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

def read_serial_data(ser, debug, stop_event):
    while not stop_event.is_set():
        try:
            data = ser.readline()
            if data:
                decoded_data = decode_ve_direct_message(data, debug)
                if decoded_data != None:
                    _last_serial_ts[0] = time.time()
                    MasterDict['SOLAR_CONTROLLER_STATUS/1'][decoded_data['op']] = decoded_data['value']
        except KeyboardInterrupt:
            break
        except Exception as e:
            # Log bad serial data but keep thread alive
            print(f"Warning: serial decode error (skipping): {e}")

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

    _SERIAL_TIMEOUT_SEC = 30

    try:
        while True:  # reconnect loop — restarts on serial timeout without exiting
            port_to_use = find_serial_port(baud_rate) or serial_port
            try:
                ser = serial.Serial(port_to_use, baud_rate, timeout=1, inter_byte_timeout=0.1)
                print(f"VE-Direct serial port {port_to_use} opened.")
            except Exception as e:
                print(f"Failed to open serial port {port_to_use}: {e} — retrying in 10s")
                time.sleep(10)
                continue

            _last_serial_ts[0] = time.time()
            stop_event = threading.Event()
            thread = threading.Thread(target=read_serial_data, args=(ser, debug, stop_event))
            thread.start()
            print("VE-Direct/Solar to MQTT Running")

            try:
                while True:
                    time.sleep(2)
                    if time.time() - _last_serial_ts[0] > _SERIAL_TIMEOUT_SEC:
                        print(f"No VE.Direct data for {_SERIAL_TIMEOUT_SEC}s — reconnecting serial port")
                        break  # drop to reconnect
                    MasterDict['SOLAR_CONTROLLER_STATUS/1']['timestamp'] = time.time()
                    RVC_Client.pub(MasterDict['SOLAR_CONTROLLER_STATUS/1'])
                    if debug > 0:
                        print(MasterDict['SOLAR_CONTROLLER_STATUS/1'])
                        print('---------------------------------------------------------------------------------------------')
            finally:
                stop_event.set()
                ser.close()
                thread.join(timeout=5)
                print("Serial port closed.")

            print("Reconnecting in 5s...")
            time.sleep(5)

    except KeyboardInterrupt:
        print("Program terminated by user.")

if __name__ == "__main__":

    main(
        serial_port='/dev/ttyAMA0',
        baud_rate=19200,
        mode='pub',
        broker='localhost', 
        port=1883, 
        varprefix='_var', 
        mqttTopic='RVC', 
        debug = 0,    # 0 - no debug, 1 - print MQTT record, 2 - print MQTT record, all serial data, and rvglue debug
    )
