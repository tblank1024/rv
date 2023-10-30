import serial
import time
import threading

# Configuration

serial_port = '/dev/ttyAMA0'
baud_rate = 19200

def charger_status(status):
    match status:
        case '0':
            outstr = "Off"
        case '1':
            outstr = "Low power (MPPT not used)"
        case '2':
            outstr = "Fault"
        case '3':
            outstr = "Bulk"
        case '4':
            outstr = "Absorption"
        case '5':
            outstr = "Float"
        case '6':
            outstr = "Storage (MPPT not used)"
        case '7':
            outstr = "Equalize (manual)"
        case '9':
            outstr = "Inverting (MPPT not used)"
        case '11':
            outstr = "Power supply (MPPT not used)"
        case '245':
            outstr = "Starting-up"
        case '246':
            outstr = "Repeated absorption (MPPT not used)"
        case '247':
            outstr = "Auto equalize"
        case '248':
            outstr = "BatterySafe (MPPT not used)"
        case '252':
            outstr = "External control"
        case _:
            outstr = "Unknown"
    return outstr

def mppt_status(status):
    match status:
        case '0':
            return("Off")
        case '1':
            return("Voltage or current limited")
        case '2':
            return("MPPT active")
        case _:
            return("Unknown")
    

def error_status(status):
    match status:
        case '0':
            outstr = "No error"
        case '2':
            outstr = "Battery voltage too high"
        case '17':
            outstr = "Charger temperature too high"
        case '18':
            outstr = "Charger over current"
        case '19':
            outstr = "Charger current reversed"
        case '20':
            outstr = "Bulk time limit exceeded"
        case '21':
            outstr = "Current sensor issue (sensor bias/sensor broken)"
        case '26':
            outstr = "Terminals overheated"
        case '28':
            outstr = "Converter issue (dual converter models only)"
        case '33':
            outstr = "Input voltage too high (solar panel)"
        case '34':
            outstr = "Input current too high (solar panel)"
        case '38':
            outstr = "Input shutdown (due to excessive battery voltage)"
        case '39':
            outstr = "Input shutdown (due to current flow during off mode)"
        case '65':
            outstr = "Lost communication with one of devices"
        case '66':
            outstr = "Synchronised charging device configuration issue"
        case '67':
            outstr = "BMS connection lost"
        case '116':
            outstr = "Factory calibration data lost"
        case '117':
            outstr = "Invalid/incompatible firmware"
        case '119':
            outstr = "User settings invalid"
        case _:
            outstr = "Unknown"
    return outstr

def decode_ve_direct_message(data):
    # VE.Direct message decoding logic
    lst = str(data).split('\\t')
    if len(lst) != 2:
        return None
    lst[0] = lst[0].lstrip("b'")
    lst[1] = lst[1].rstrip("\\r\\n'")
    match lst[0]:
        case 'V':
            print(f"Battery V: {float(lst[1])/1000}")
        case 'VPV':
            print(f"Panel V: {float(lst[1])/1000}")
        case 'I':
            print(f"Battery I: {float(lst[1])/1000}")
        case 'IL':
            print(f"Load I: {float(lst[1])/1000}")
        case 'PPV':
            print(f"Panel Watts: {lst[1]}")
        case 'CS':
            outstr = charger_status(lst[1])
            print(f"Charger state: {outstr}")
        case 'MPPT':
            outstr = mppt_status(lst[1])
            print(f"MPPT: {outstr}")
        case 'ERR':
            outstr = error_status(lst[1])
            print(f"Error: {outstr}")
        case _:  # Default case
            #print(f"Unknown: {lst[0], lst[1]}")
            return None
        
    decoded_data = {}  # Store decoded data in a dictionary
    return decoded_data

def read_serial_data(ser):
    try:
        while True:
            data = ser.readline()
            if data:
                #print(f"Received data: {data}")
                decoded_data = decode_ve_direct_message(data)
                #print(f"Decoded data: {decoded_data}")
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
