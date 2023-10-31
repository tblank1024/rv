import serial
import time
import threading
import rvglue

# Configuration

serial_port = '/dev/ttyAMA0'
baud_rate = 19200

debug = 0

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
    



def decode_ve_direct_message(data):
    # VE.Direct message decoding logic
    lst = str(data).split('\\t')
    if len(lst) != 2:
        return None
    lst[0] = lst[0].lstrip("b'")
    lst[1] = lst[1].rstrip("\\r\\n'")
    decoded_data = {}  # Store decoded data in a dictionary
    decoded_data = {'op': lst[0]}
    match lst[0]:
        case 'V':            
            decoded_data = {'value': 'Batttery(V)= ' + str(float(lst[1])/1000)}
        case 'VPV':                        
            decoded_data = {'value': 'Panel(V)= ' + str(float(lst[1])/1000)}
        case 'I':
            decoded_data = {'value': 'Batttery(I)= ' + str(float(lst[1])/1000)}
        case 'IL':
            decoded_data = {'value': 'Load(I)= ' + str(float(lst[1])/1000)}
        case 'PPV':
            decoded_data = {'value': 'Panel(W) ' + str(float(lst[1])/1000)}
        case 'CS':
            if lst[1] in charger_status:
                decoded_data = {'value': 'Charger State= ' + charger_status[lst[1]]}
            else:
                decoded_data = {'value': "Unknown CS code " + lst[1]}
        case 'MPPT':
            if lst[1] in mppt_status:
               decoded_data = {'value': 'MPPT State= ' + mppt_status[lst[1]]}
            else:
                decoded_data = {'value': 'MPPT State= ' + "Unknown MPPT code " + lst[1]}
        case 'ERR':
            if lst[1] == '0':       # No error so don't bother reporting
                decoded_data = None
            elif lst[1] in error_status:
                decoded_data = {'value': 'ERROR= ' + error_status[lst[1]]}
            else:
                decoded_data = {'value': "Unknown ERR code " + lst[1]}
        case _:  # Default case
            if debug > 0:
                print(f"Cmd not tracked: {lst[0]} {lst[1]}")
                decoded_data = {'value': 'Cmd not tracked: ' + lst[0] + ' ' + lst[1]}
            else:
                decoded_data = None
    return decoded_data

def read_serial_data(ser):
    try:
        while True:
            data = ser.readline()
            if data:
                #print(f"Received data: {data}")
                decoded_data = decode_ve_direct_message(data)
                if decoded_data != None:
                    print(decoded_data['value'])
    except KeyboardInterrupt:
        print("Thread terminated.")

def main():
    # Open the serial port
    try:
        ser = serial.Serial(serial_port, baud_rate, timeout=1, inter_byte_timeout=0.1)
        print(f"Serial port {serial_port} opened successfully.")
    except Exception as e:
        print(f"Failed to open serial port: {e}")
        return

    try:
        # Start a separate thread for reading serial data
        thread = threading.Thread(target=read_serial_data, args=(ser,))
        thread.start()

        # Main program loop (can be empty as the reading is handled in a separate thread)
        while True:
            time.sleep(10)  # Add any additional processing or logic here

    except KeyboardInterrupt:
        print("Program terminated by user.")
    finally:
        # Close the serial port and wait for the thread to finish
        ser.close()
        thread.join()
        print("Serial port closed.")

if __name__ == "__main__":
    main()
