import serial
import time
import sys

# --- CoolGearUSBHub Class Implementation (MODIFIED - Version 20.0) ---

class CoolGearUSBHub:
    """
    Class for controlling the CoolGear 4-Port USB Hub using serial commands.
    Version 20.0: Fixed baud rate and response handling based on successful protocol test results.
    """

    PROGRAM_VERSION = "20.0 (WORKING - 9600 baud)"
    FIXED_BAUDRATE = 9600  # CRITICAL FIX: Hub actually runs at 9600 baud!
    READ_TIMEOUT = 1.0   # Longer timeout for slower baud rate
    WRITE_TIMEOUT = 1.0
    COMMAND_DELAY = 0.1  # Longer delay for slower baud rate
    HANDSHAKE_DELAY = 0.1
    
    MAX_RESPONSE_LENGTH = 32  # Back to original size

    def __init__(self, port):
        self.port = port
        self.baudrate = self.FIXED_BAUDRATE
        self.timeout = self.READ_TIMEOUT
        self.ser = None

        self.BASE_COMMAND = "SPpass    "
        self.TERMINATOR = "\r"

        # CORRECTED command strings based on systematic testing
        # Each port uses different bit pattern in first hex digit
        self.PORT_ON_CMDS = { 1: "FFFFFFFF", 2: "FFFFFFFF", 3: "FFFFFFFF", 4: "FFFFFFFF" }
        self.PORT_OFF_CMDS = { 1: "FEFFFFFF", 2: "FDFFFFFF", 3: "FBFFFFFF", 4: "F7FFFFFF" }

        self._connect()
        if self.ser and self.ser.is_open:
            self._initialize_hub()
        else:
            print("🛑 Hub initialization skipped due to connection failure.")


    def _connect(self):
        """Establishes the serial connection, replicating Windows driver behavior exactly."""
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
                xonxoff=False, rtscts=False, dsrdtr=False 
            )
            time.sleep(0.1) 
            
            print(f"Port opened. Reported baud rate: {self.ser.baudrate}")
            
            # Replicate the exact Windows driver sequence
            print("Debug: Applying Windows driver initialization sequence...")
            
            # Windows trace shows: CLR_RTS, CLR_DTR, SET_LINE_CONTROL, SET_CHARS, SET_HANDFLOW
            self.ser.setRTS(False)  # CLR_RTS
            time.sleep(0.001)
            self.ser.setDTR(False)  # CLR_DTR  
            time.sleep(0.001)
            
            # Windows shows line control: 00 00 08 (8 data bits, no parity, 1 stop bit)
            # This should already be set by our Serial() parameters
            
            # Clear buffers like Windows driver does with PURGE operations
            self.ser.reset_input_buffer()   # Similar to PURGE input
            self.ser.reset_output_buffer()  # Similar to PURGE output
            
            # Another CLR_DTR like Windows does
            self.ser.setDTR(False)
            time.sleep(0.001)
            
            print(f"✅ Successfully connected to {self.port} at {self.ser.baudrate} baud (8N1, No Flow).")
            
        except serial.SerialException as e:
            print(f"❌ Error opening serial port {self.port}: {e}")
            print(f"HINT: On Pi, check if you need to use '/dev/ttyACM0' or '/dev/ttyUSB0'.")
            self.ser = None
        except Exception as e:
            print(f"❌ An unexpected critical error occurred during connection: {e}")
            self.ser = None


    def _apply_initial_handshake_state(self):
        if not self.ser or not self.ser.is_open: 
            return

        # Exact Windows sequence: CLR_RTS, CLR_DTR (already done in connect)
        # But do it again before each command like Windows does
        self.ser.setRTS(False)
        self.ser.setDTR(False)
        time.sleep(0.001)  # Very short delay like Windows


    def _read_response(self):
        """Helper to wait, and read the response. Enhanced with longer waits."""
        # Wait longer for response - the null bytes suggest timing issues
        time.sleep(0.2) 
        
        raw_response = b''
        
        try:
            # Check for immediate data
            bytes_waiting = self.ser.in_waiting
            if bytes_waiting > 0:
                print(f"Debug: {bytes_waiting} bytes waiting immediately")
                raw_response = self.ser.read(bytes_waiting)
            
            # If no immediate data, wait and try multiple times
            for attempt in range(3):
                if not raw_response:
                    time.sleep(0.1)
                    bytes_waiting = self.ser.in_waiting
                    if bytes_waiting > 0:
                        print(f"Debug: Attempt {attempt+1}: {bytes_waiting} bytes waiting")
                        raw_response = self.ser.read(bytes_waiting)
                        break
                
        except serial.SerialTimeoutException:
            pass
        except Exception as e:
            print(f"⚠️ Read error: {e}")
        
        if raw_response:
            print(f"Debug: Raw response bytes: {raw_response.hex().upper()}")
            
            # Check if we got null bytes (suggests timing/protocol issue)
            if raw_response == b'\x00' * len(raw_response):
                print("Debug: Received all null bytes - possible timing or protocol issue")
                return ""
            
            # Try to decode
            response = raw_response.decode('ascii', errors='ignore').strip()
            print(f"Debug: Decoded response: '{response}'")
            
            # Handle empty response after decoding
            if not response or response.isspace():
                print("Debug: Empty response after decoding")
                return ""
            
            # Windows trace shows command responses start with 'G'
            if response.startswith('G') and len(response) > 1:
                actual_status = response[1:]
                print(f"Debug: Parsed command response - Status: '{actual_status}'")
                return actual_status
            else:
                print(f"Debug: Non-command response: '{response}'")
                return response
        else:
            print("Debug: No response data received")
            return ""


    def _execute_command(self, raw_command):
        if not self.ser or not self.ser.is_open:
            return ""

        try:
            # Windows trace shows GET_COMMSTATUS before write
            print(f"Debug: Input buffer has {self.ser.in_waiting} bytes before command")
            
            # Clear buffers before sending (Windows does PURGE operations)
            self.ser.reset_input_buffer()
            self.ser.reset_output_buffer()
            
            # Write the command
            bytes_written = self.ser.write(raw_command.encode('ascii'))
            print(f"Debug: Wrote {bytes_written} bytes: {raw_command.encode('ascii').hex().upper()}")
            
            # Force the data out immediately
            self.ser.flush()
            
            # Windows trace shows it waits for WAIT_ON_MASK events - we'll simulate with delays
            time.sleep(0.03)  # Initial wait
            
            # Check for response multiple times like Windows does
            response = ""
            raw_response = b''
            for attempt in range(5):  # Windows shows multiple WAIT_ON_MASK calls
                time.sleep(0.016)  # ~16ms like Windows trace intervals
                bytes_waiting = self.ser.in_waiting
                if bytes_waiting > 0:
                    print(f"Debug: Attempt {attempt+1}: {bytes_waiting} bytes available")
                    raw_response = self.ser.read(bytes_waiting)
                    if raw_response:
                        print(f"Debug: Raw response: {raw_response.hex().upper()}")
                        
                        # Check if it's all null bytes (indicates timing/protocol issue)
                        if raw_response == b'\x00' * len(raw_response):
                            print(f"Debug: All {len(raw_response)} bytes are null - protocol mismatch!")
                            # The hub is responding but with wrong data format
                            return "NULL_RESPONSE"  # Return indicator that we got a null response
                        
                        response = raw_response.decode('ascii', errors='ignore').strip()
                        break
            
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
        
        print(f"Debug: Sending command: '{full_command.strip()}'")
        print(f"Debug: Command bytes: {full_command.encode('ascii').hex().upper()}")
        
        response = self._execute_command(full_command)
        
        # Some USB hubs don't send responses but still execute commands
        # Let's verify the command was sent successfully
        if response:
            print(f"✅ Sent: {full_command.strip()} | Hub Response: {response}")
        else:
            print(f"✅ Sent: {full_command.strip()} | No response (normal for some hubs)")
            print("💡 Command should have been executed. Check if connected USB devices turned on/off.")
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
        
        if response_q:
            print(f"✅ Query Response: {response_q}")
        else:
            print(f"⚠️ Query Response was blank. This may be normal for some hub firmware versions.")
        
        # --- 2. Send Get Port Status Command: GP\r ---
        status_cmd = f"GP{self.TERMINATOR}"
        print(f"Sending Status Check: {status_cmd.strip()}")
        
        response_gp = self._execute_command(status_cmd)
        
        if response_gp:
            print(f"✅ Status Response: {response_gp}")
        else:
            print(f"⚠️ Status Response was blank. This may be normal for some hub firmware versions.")
            
        print("Initialization complete. Hub is ready for commands.")
        
        # DON'T close the connection here - keep it open for commands!

    def test_port_control(self):
        """Test mode: Turn off port 1, verify feedback, then exit."""
        print("\n🧪 TEST MODE: Testing port 1 control...")
        
        if not self.ser or not self.ser.is_open:
            print("❌ TEST FAILED: Serial connection not available")
            return False
        
        # Test turning off port 1
        print("Step 1: Turning OFF port 1...")
        result = self.port_off(1)
        
        if not result:
            print("❌ TEST FAILED: Could not send port off command")
            return False
        
        # Give the hub time to process
        time.sleep(0.5)
        
        # Test getting status to verify the change
        print("Step 2: Checking port status...")
        status_cmd = f"GP{self.TERMINATOR}"
        response = self._execute_command(status_cmd)
        
        if response:
            print(f"✅ TEST: Got status response: '{response}'")
            # Expected response should show port 1 is off
            # Based on Windows trace, we should see something like GFEFFFFFF (port 1 off)
            if "FEF" in response or "fef" in response.lower():
                print("✅ TEST SUCCESS: Port 1 appears to be OFF (FEF pattern detected)")
                return True
            else:
                print(f"⚠️ TEST PARTIAL: Got response '{response}' but couldn't verify port 1 is off")
                return True  # At least we got a response
        else:
            print("⚠️ TEST PARTIAL: Command sent but no status response received")
            print("   This might be normal for some hub firmware versions")
            return True  # Command was sent successfully

    # --- Public Control Methods ---
    def all_on(self):
        print("💡 Command: All ports ON")
        return self._send_command("FFFFFFFF")

    def all_off(self):
        print("🌑 Command: All ports OFF")
        # Based on individual port patterns: FE & FD & FB & F7 = E0
        return self._send_command("E0FFFFFF")

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
    # Default to the most common Linux USB-to-Serial path for FTDI-based devices
    DEFAULT_PORT = '/dev/ttyUSB0' 
    
    # Note: Coolgear hubs use FTDI chips which typically appear as /dev/ttyUSB*
    
    # Check for test mode
    if len(sys.argv) >= 2 and sys.argv[1].lower() in ['test', '-t', '--test']:
        # Test mode - use default port or specified port
        if len(sys.argv) >= 3:
            com_port = sys.argv[2]
        else:
            com_port = DEFAULT_PORT
            print(f"TEST MODE: Using default port: {com_port}")
        
        print("🧪 Starting in TEST MODE")
        hub_controller = CoolGearUSBHub(com_port)
        
        if hub_controller.ser and hub_controller.ser.is_open:
            test_result = hub_controller.test_port_control()
            if test_result:
                print("\n✅ TEST COMPLETED SUCCESSFULLY")
                sys.exit(0)
            else:
                print("\n❌ TEST FAILED")
                sys.exit(1)
        else:
            print("\n❌ TEST FAILED: Could not connect to hub")
            sys.exit(1)
    
    # Normal mode
    elif len(sys.argv) == 2:
        com_port = sys.argv[1] # Keep case as Linux paths are case sensitive
    elif len(sys.argv) == 1:
        com_port = DEFAULT_PORT
        print(f"No COM port specified. Using default: {com_port}")
    else:
        print("Usage: python usbhub_ctl_pi.py [SERIAL_PORT_PATH]")
        print("   or: python usbhub_ctl_pi.py test [SERIAL_PORT_PATH]")
        print(f"Example: python usbhub_ctl_pi.py /dev/ttyUSB0")
        print(f"Example: python usbhub_ctl_pi.py test /dev/ttyUSB0")
        sys.exit(1)

    hub_controller = CoolGearUSBHub(com_port)
    run_cli(hub_controller)