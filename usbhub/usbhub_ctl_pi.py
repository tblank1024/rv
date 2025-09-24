import serial
import time
import sys

# --- CoolGearUSBHub Class Implementation (MODIFIED - Version 18.0) ---

class CoolGearUSBHub:
    """
    Class for controlling the CoolGear 4-Port USB Hub using serial commands.
    Version 18.0: Optimized for Linux/Raspberry Pi. Reduced COMMAND_DELAY 
    and reverted to reliable read_until('\\r') logic.
    """

    PROGRAM_VERSION = "18.0 (Pi Optimized)"
    FIXED_BAUDRATE = 115200
    READ_TIMEOUT = 0.5   
    WRITE_TIMEOUT = 0.5
    # Reduced delay, assuming better OS buffering than Windows COM driver
    COMMAND_DELAY = 0.05 
    HANDSHAKE_DELAY = 0.05
    
    MAX_RESPONSE_LENGTH = 32 

    def __init__(self, port):
        self.port = port
        self.baudrate = self.FIXED_BAUDRATE
        self.timeout = self.READ_TIMEOUT
        self.ser = None

        self.BASE_COMMAND = "SPpass    "
        self.TERMINATOR = "\r"

        self.PORT_ON_CMDS = { 1: "FFFEFFFF", 2: "FFFFFEFF", 3: "FFFFFEEF", 4: "FFFFFEEF" }
        self.PORT_OFF_CMDS = { 1: "FFEFFEFF", 2: "FEFFFFFF", 3: "FFFEFFFF", 4: "FFFEFFFF" }

        self._connect()
        if self.ser and self.ser.is_open:
            self._initialize_hub()
        else:
            print("🛑 Hub initialization skipped due to connection failure.")


    def _connect(self):
        """Establishes the serial connection, using the provided Linux device path."""
        print(f"Attempting to open {self.port}...")
        try:
            self.ser = serial.Serial(
                port=self.port, 
                baudrate=self.baudrate, 
                timeout=self.READ_TIMEOUT,             
                write_timeout=self.WRITE_TIMEOUT, 
                bytesize=8, 
                parity=serial.PARITY_NONE, 
                stopbits=serial.STOPBITS_ONE,
                # Flow control is None, but explicitly turn off control lines initially
                xonxoff=False, rtscts=False, dsrdtr=False 
            )
            time.sleep(0.1) 
            
            print(f"Port opened. Reported baud rate: {self.ser.baudrate}")
            
            # Explicitly ensure correct baud rate (safer in embedded environments)
            if self.ser.baudrate != self.FIXED_BAUDRATE:
                 print(f"⚠️ Warning: Forcing baud rate to {self.FIXED_BAUDRATE}...")
                 self.ser.baudrate = self.FIXED_BAUDRATE
                 time.sleep(0.1)
                 self.ser.timeout = self.READ_TIMEOUT 

            self._apply_initial_handshake_state()
            
            print(f"✅ Successfully connected to {self.port} at {self.ser.baudrate} baud (8N1, No Flow).")
            
        except serial.SerialException as e:
            # On Linux, COM port errors are typically "No such file or directory" if path is wrong.
            print(f"❌ Error opening serial port {self.port}: {e}")
            print(f"HINT: On Pi, check if you need to use '/dev/ttyACM0' or '/dev/ttyUSB0'.")
            self.ser = None
        except Exception as e:
            print(f"❌ An unexpected critical error occurred during connection: {e}")
            self.ser = None


    def _apply_initial_handshake_state(self):
        if not self.ser or not self.ser.is_open: return

        self.ser.setRTS(False)
        self.ser.setDTR(False)
        time.sleep(self.HANDSHAKE_DELAY)


    def _read_response(self):
        """Helper to wait, and read the response. Using fixed short delay + reliable read_until('\r')."""
        # 1. Wait a very short time (COMMAND_DELAY) for the response to arrive in the buffer
        time.sleep(self.COMMAND_DELAY) 
        
        raw_response = b''
        
        try:
            # 2. Perform a single read, blocking up to the port's READ_TIMEOUT (0.5s)
            raw_response = self.ser.read_until(self.TERMINATOR.encode('ascii'), size=self.MAX_RESPONSE_LENGTH)
        except serial.SerialTimeoutException:
            pass # Timeout is expected if no response
        except Exception as e:
            print(f"⚠️ Read error: {e}")
        
        # 3. Decode and clean up
        response = raw_response.decode('ascii', errors='ignore').strip()
        
        return response
            
    def _execute_command(self, raw_command):
        if not self.ser or not self.ser.is_open:
            return ""

        try:
            # 1. Clear ALL buffers before sending a command
            self.ser.flush()  
            
            # 2. Write the command
            self.ser.write(raw_command.encode('ascii'))
            
            # 3. Clear output buffer *after* writing
            self.ser.flushOutput() 
            
            # 4. Read the response
            response = self._read_response()
            return response
            
        except serial.SerialException as e:
            print(f"❌ Error during command execution: {e}")
            return ""

            
    def _send_command(self, status_string):
        if not self.ser or not self.ser.is_open:
            print("❌ Error: Serial connection is not open. Cannot send command.")
            return False
            
        full_command = f"{self.BASE_COMMAND}{status_string}{self.TERMINATOR}"
        
        self._apply_initial_handshake_state()
        
        response = self._execute_command(full_command)
        
        if response:
            print(f"Sent: {full_command.strip()} | Hub Response: {response}")
        else:
            print(f"Sent: {full_command.strip()} | Hub Response: [None] (Command was sent).")
        return True
            
    def _initialize_hub(self):
        if not self.ser or not self.ser.is_open:
            return

        print(f"\n⚙️ Running mandatory hub initialization sequence...")
        
        self._apply_initial_handshake_state()
        
        # --- 1. Send Device ID/Query Command: ?Q\r ---
        query_cmd = f"?Q{self.TERMINATOR}"
        print(f"Sending Query: {query_cmd.strip()}")
        
        response_q = self._execute_command(query_cmd) 
        
        if not response_q:
            print(f"Initial Query Response was blank. Retrying...")
            self._apply_initial_handshake_state()
            response_q = self._execute_command(query_cmd)

        print(f"✅ Query Response: {response_q or '[None]'}")


        # --- 2. Send Get Port Status Command: GP\r ---
        status_cmd = f"GP{self.TERMINATOR}"
        print(f"Sending Status Check: {status_cmd.strip()}")
        
        response_gp = self._execute_command(status_cmd)
        
        print(f"✅ Status Response: {response_gp or '[None]'}")
        
        print("Initialization complete. Hub is ready for commands.\n")

    def __del__(self):
        if self.ser and self.ser.is_open:
            self.ser.setDTR(False) 
            self.ser.close()

    # --- Public Control Methods (Unchanged) ---
    def all_on(self):
        print("💡 Command: All ports ON")
        return self._send_command("FFFFFFFF")

    def all_off(self):
        print("🌑 Command: All ports OFF")
        return self._send_command("EEEEEEEE")

    def reset_hub(self):
        print("🔄 Command: Hub Reset (All ON)")
        return self.all_on()

    def port_on(self, port_number):
        if not 1 <= port_number <= 4:
            print("❌ Error: Port number must be between 1 and 4.")
            return False
        status_string = self.PORT_ON_CMDS.get(port_number, "FFFFFFFF")
        print(f"⬆️ Command: Port {port_number} ON")
        return self._send_command(status_string)

    def port_off(self, port_number):
        if not 1 <= port_number <= 4:
            print("❌ Error: Port number must be between 1 and 4.")
            return False
        status_string = self.PORT_OFF_CMDS.get(port_number, "EEEEEEEE")
        print(f"⬇️ Command: Port {port_number} OFF")
        return self._send_command(status_string)

# ----------------------------------------------------------------------
# --- Command Line Interface (CLI) Function (Unchanged) ---

def run_cli(hub):
    """Handles the command-line interaction."""
    
    if not hub.ser or not hub.ser.is_open:
        print("\nExiting due to connection error.")
        return

    print(f"\n--- USB Hub CLI Ready (v{hub.PROGRAM_VERSION}) ---")
    print("Commands: [port] [action] (e.g., '1 on', 'all off', 'reset')")
    print("Type 'exit' or 'quit' to close.")

    while True:
        try:
            user_input = input(f"HUB_CTL({hub.port})> ").strip().lower()
            
            if user_input in ['exit', 'quit']:
                break

            parts = user_input.split()
            if not parts:
                continue

            target = parts[0]
            action = parts[1] if len(parts) > 1 else None

            if target == 'all':
                if action == 'on':
                    hub.all_on()
                elif action == 'off':
                    hub.all_off()
                else:
                    print("Usage: 'all on' or 'all off'")
            
            elif target == 'reset':
                hub.reset_hub()
            
            elif target.isdigit():
                port_num = int(target)
                if not 1 <= port_num <= 4:
                    print("Invalid port number. Use 1, 2, 3, or 4.")
                    continue

                if action == 'on':
                    hub.port_on(port_num)
                elif action == 'off':
                    hub.port_off(port_num)
                else:
                    print(f"Usage: '{port_num} on' or '{port_num} off'")
            
            else:
                print(f"Unknown command or format: '{user_input}'")
                print("Hint: Try '1 on', 'all off', or 'reset'")

        except EOFError:
            print("\nExiting...")
            break
        except Exception as e:
            print(f"An unexpected error occurred: {e}")

# ----------------------------------------------------------------------
# --- Main Program Entry Point (MODIFIED for Linux) ---

if __name__ == '__main__':
    # Default to the most common Linux USB-to-Serial path for microcontrollers
    DEFAULT_PORT = '/dev/ttyACM0' 
    
    # Alternatively, use '/dev/ttyUSB0' if your adapter is based on a chip like FTDI/CH340
    
    if len(sys.argv) == 2:
        com_port = sys.argv[1] # Keep case as Linux paths are case sensitive
    elif len(sys.argv) == 1:
        com_port = DEFAULT_PORT
        print(f"No COM port specified. Using default: {com_port}")
    else:
        print("Usage: python your_program_name.py [SERIAL_PORT_PATH]")
        print(f"Example: python coolgear_ctl.py /dev/ttyACM0")
        sys.exit(1)

    hub_controller = CoolGearUSBHub(com_port)
    run_cli(hub_controller)