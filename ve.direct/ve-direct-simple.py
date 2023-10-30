import serial
import time

# Configuration
serial_port = '/dev/ttyAMA0'
baud_rate = 19200

def decode_ve_direct_message(data):
    # Implement your VE.Direct message decoding logic here
    # This is where you parse the data and extract meaningful information
    # For example, you can refer to Victron's VE.Direct Protocol documentation

    # Sample decoding logic:
    decoded_data = {}  # Store decoded data in a dictionary
    # Implement your decoding logic and populate the dictionary
    # Example: decoded_data['battery_voltage'] = int(data[5:10], 16) / 100

    return decoded_data

def main():
    # Open the serial port
    try:
        print(serial.__version__)
        ser = serial.Serial(serial_port, baudrate=baud_rate, timeout=1)
        print(f"Serial port {serial_port} opened successfully.")
    except Exception as e:
        print(f"Failed to open serial port: {e}")
        return

    try:
        while True:
            # Read data from the serial port
            data = ser.readline().decode().strip()

            if data:
                print(f"Received data: {data}")
                #decoded_data = decode_ve_direct_message(data)
                #print(f"Decoded data: {decoded_data}")

            # Add a delay before reading the next message (adjust as needed)
            time.sleep(1)
    except KeyboardInterrupt:
        print("Program terminated by user.")
    finally:
        # Close the serial port when the program exits
        ser.close()
        print("Serial port closed.")

if __name__ == "__main__":
    main()
