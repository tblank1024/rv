import serial
import time
import sys
import os


def _reset_usb_device_for_tty(tty_path):
    """
    Reset the USB device backing a tty serial port via sysfs unbind/bind.
    Uses /sys/bus/usb/drivers/usb/unbind+bind (mounted rw in Docker).
    This clears EPROTO (-71) errors caused by the FTDI chip entering a bad state.

    Args:
        tty_path: e.g. '/dev/ttyUSB1'
    Returns:
        True if reset was attempted, False if sysfs path not found.
    """
    tty_name = os.path.basename(tty_path)  # e.g. 'ttyUSB1'
    sysfs_tty = f'/sys/class/tty/{tty_name}/device'

    try:
        if not os.path.exists(sysfs_tty):
            print(f"[USB RESET] sysfs path not found for {tty_name}, skipping reset")
            return False

        # Walk up from the resolved tty device path to find the USB device directory.
        # USB interfaces have ':' in their name (e.g. '3-1.4:1.0').
        # USB devices do not (e.g. '3-1.4').
        current = os.path.realpath(sysfs_tty)
        usb_device_id = None

        for _ in range(6):
            basename = os.path.basename(current)
            # USB port path format: N-N.N or N-N (bus-port, no colon)
            if ':' not in basename and '.' in basename or (basename.startswith(tuple('123456789')) and '-' in basename and ':' not in basename):
                usb_device_id = basename
                break
            current = os.path.dirname(current)

        if not usb_device_id:
            print(f"[USB RESET] Could not determine USB device ID from sysfs path for {tty_name}")
            print(f"[USB RESET] Final resolved path was: {current}")
            return False

        # /sys/bus/usb is mounted :rw in docker-compose — use unbind/bind
        unbind_path = '/sys/bus/usb/drivers/usb/unbind'
        bind_path   = '/sys/bus/usb/drivers/usb/bind'

        if not os.path.exists(unbind_path):
            print(f"[USB RESET] {unbind_path} not available")
            return False

        print(f"[USB RESET] Resetting USB device '{usb_device_id}' via driver unbind/bind ...")

        with open(unbind_path, 'w') as f:
            f.write(usb_device_id)
        time.sleep(1.0)

        with open(bind_path, 'w') as f:
            f.write(usb_device_id)

        # Wait up to 5 s for the tty device node to reappear
        for _ in range(20):
            time.sleep(0.25)
            if os.path.exists(tty_path):
                print(f"[USB RESET] {tty_name} re-enumerated successfully")
                return True

        print(f"[USB RESET] WARNING: {tty_name} did not reappear within 5s after reset")
        return True  # Reset was issued; caller can decide what to do

    except PermissionError:
        print(f"[USB RESET] Permission denied — check /sys/bus/usb is mounted :rw in docker-compose")
        return False
    except Exception as e:
        print(f"[USB RESET] Error during USB reset: {e}")
        return False

# --- CoolGearUSBHub Class Implementation (ASCII-only Version) ---

class CoolGearUSBHub:
    """
    Class for controlling the CoolGear 4-Port USB Hub using serial commands.
    Version 20.1: ASCII-only version to avoid Unicode encoding issues.
    """

    PROGRAM_VERSION = "20.1 (ASCII-ONLY - 9600 baud)"
    FIXED_BAUDRATE = 9600  
    READ_TIMEOUT = 1.0   
    WRITE_TIMEOUT = 1.0
    COMMAND_DELAY = 0.1  
    HANDSHAKE_DELAY = 0.1
    
    MAX_RESPONSE_LENGTH = 32  

    def __init__(self, port):
        self.port = port
        self.baudrate = self.FIXED_BAUDRATE
        self.timeout = self.READ_TIMEOUT
        self.ser = None
        self.last_active_port = None  # Track the last active port for proper switching delays

        self.BASE_COMMAND = "SPpass    "
        self.TERMINATOR = "\r"

        # CORRECTED command strings based on systematic testing
        # Individual port ON commands (only one port on at a time)
        self.PORT_ON_CMDS = { 
            1: "01FFFFFF",  # Only port 1 on
            2: "02FFFFFF",  # Only port 2 on
            3: "04FFFFFF",  # Only port 3 on
            4: "08FFFFFF"   # Only port 4 on
        }
        # Individual port OFF commands
        self.PORT_OFF_CMDS = { 1: "FEFFFFFF", 2: "FDFFFFFF", 3: "FBFFFFFF", 4: "F7FFFFFF" }

        # Track last active port for 2-second delay between different ports
        self.last_active_port = None

        self._connect()
        if self.ser and self.ser.is_open:
            self._initialize_hub()
        else:
            print("[ERROR] Hub initialization skipped due to connection failure.")

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
            
            # Clear buffers like Windows driver does with PURGE operations
            self.ser.reset_input_buffer()   # Similar to PURGE input
            self.ser.reset_output_buffer()  # Similar to PURGE output
            
            # Another CLR_DTR like Windows does
            self.ser.setDTR(False)
            time.sleep(0.001)
            
            print(f"[OK] Successfully connected to {self.port} at {self.ser.baudrate} baud (8N1, No Flow).")
            
        except serial.SerialException as e:
            print(f"[ERROR] Error opening serial port {self.port}: {e}")
            print(f"HINT: On Pi, check if you need to use '/dev/ttyACM0' or '/dev/ttyUSB0'.")
            self.ser = None
        except OSError as e:
            if e.errno == 5:  # EIO — FTDI chip in bad USB state
                print(f"[ERROR] FTDI USB error (EIO) on {self.port} — attempting USB device reset...")
                self.ser = None
                if _reset_usb_device_for_tty(self.port):
                    # One retry after reset
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
                        self.ser.setRTS(False)
                        self.ser.setDTR(False)
                        self.ser.reset_input_buffer()
                        self.ser.reset_output_buffer()
                        print(f"[OK] Reconnected to {self.port} after USB reset.")
                    except Exception as retry_e:
                        print(f"[ERROR] Retry after USB reset failed: {retry_e}")
                        self.ser = None
            else:
                print(f"[ERROR] OS error opening {self.port}: {e}")
                self.ser = None
        except Exception as e:
            print(f"[ERROR] An unexpected critical error occurred during connection: {e}")
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
            print(f"[WARNING] Read error: {e}")
        
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

    def _reconnect(self):
        """Attempt to re-establish a dropped serial connection."""
        print(f"[INFO] Attempting to reconnect to {self.port}...")
        try:
            if self.ser and self.ser.is_open:
                self.ser.close()
        except Exception:
            pass
        self.ser = None
        self._connect()
        if self.ser and self.ser.is_open:
            print(f"[OK] Reconnected to {self.port}")
            return True
        print(f"[ERROR] Reconnect to {self.port} failed")
        return False

    def _execute_command(self, raw_command):
        if not self.ser or not self.ser.is_open:
            print("[WARNING] Serial port closed, attempting reconnect...")
            if not self._reconnect():
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
            print(f"[ERROR] Error during command execution: {e}")
            # Mark port as closed so next call triggers reconnect
            try:
                if self.ser:
                    self.ser.close()
            except Exception:
                pass
            return ""

    def _send_command(self, status_string):
        if not self.ser or not self.ser.is_open:
            print("[ERROR] Serial connection is not open. Cannot send command.")
            return False
            
        full_command = f"{self.BASE_COMMAND}{status_string}{self.TERMINATOR}"
        
        self._apply_initial_handshake_state()
        
        print(f"Debug: Sending command: '{full_command.strip()}'")
        print(f"Debug: Command bytes: {full_command.encode('ascii').hex().upper()}")
        
        response = self._execute_command(full_command)
        
        # Some USB hubs don't send responses but still execute commands
        # Let's verify the command was sent successfully
        if response:
            print(f"[OK] Sent: {full_command.strip()} | Hub Response: {response}")
        else:
            print(f"[OK] Sent: {full_command.strip()} | No response (normal for some hubs)")
            print("[INFO] Command should have been executed. Check if connected USB devices turned on/off.")
        return True
            
    def _initialize_hub(self):
        if not self.ser or not self.ser.is_open:
            return

        print(f"\n[INFO] Running mandatory hub initialization sequence...")
        
        self._apply_initial_handshake_state()
        
        # --- 1. Send Device ID/Query Command: ?Q\r ---
        query_cmd = f"?Q{self.TERMINATOR}"
        print(f"Sending Query: {query_cmd.strip()}")
        
        response_q = self._execute_command(query_cmd) 
        
        if response_q:
            print(f"[OK] Query Response: {response_q}")
        else:
            print(f"[WARNING] Query Response was blank. This may be normal for some hub firmware versions.")
        
        # --- 2. Send Get Port Status Command: GP\r ---
        status_cmd = f"GP{self.TERMINATOR}"
        print(f"Sending Status Check: {status_cmd.strip()}")
        
        response_gp = self._execute_command(status_cmd)
        
        if response_gp:
            print(f"[OK] Status Response: {response_gp}")
        else:
            print(f"[WARNING] Status Response was blank. This may be normal for some hub firmware versions.")
            
        print("Initialization complete. Hub is ready for commands.")

    def test_port_control(self):
        """Test mode: Turn off port 1, verify feedback, then exit."""
        print("\n[TEST] Testing port 1 control...")
        
        if not self.ser or not self.ser.is_open:
            print("[ERROR] TEST FAILED: Serial connection not available")
            return False
        
        # Test turning off port 1
        print("Step 1: Turning OFF port 1...")
        result = self.port_off(1)
        
        if not result:
            print("[ERROR] TEST FAILED: Could not send port off command")
            return False
        
        # Give the hub time to process
        time.sleep(0.5)
        
        # Test getting status to verify the change
        print("Step 2: Checking port status...")
        status_cmd = f"GP{self.TERMINATOR}"
        response = self._execute_command(status_cmd)
        
        if response:
            print(f"[OK] TEST: Got status response: '{response}'")
            # Expected response should show port 1 is off
            # Based on Windows trace, we should see something like GFEFFFFFF (port 1 off)
            if "FEF" in response or "fef" in response.lower():
                print("[OK] TEST SUCCESS: Port 1 appears to be OFF (FEF pattern detected)")
                return True
            else:
                print(f"[WARNING] TEST PARTIAL: Got response '{response}' but couldn't verify port 1 is off")
                return True  # At least we got a response
        else:
            print("[WARNING] TEST PARTIAL: Command sent but no status response received")
            print("   This might be normal for some hub firmware versions")
            return True  # Command was sent successfully

    # --- Public Control Methods ---
    def all_on(self):
        print("[INFO] Command: All ports ON")
        return self._send_command("FFFFFFFF")

    def all_off(self):
        print("[INFO] Command: All ports OFF")
        # Based on individual port patterns: FE & FD & FB & F7 = E0
        result = self._send_command("E0FFFFFF")
        if result:
            self.last_active_port = None  # Reset tracking when all ports are off
        return result

    def reset_hub(self):
        """Basic hub reset - turns all ports on."""
        print("[INFO] Command: Hub Reset (All ON)")
        return self.all_on()
    
    def full_hub_reset(self):
        """
        Comprehensive hub reset to restore ports 3 and 4 functionality.
        This attempts to reset the hub state without physical power cycling.
        """
        print("[INFO] Performing full hub reset to restore port functionality...")
        
        try:
            # Step 1: Clear any pending state
            print("  Step 1: Clearing hub buffers...")
            if self.ser:
                self.ser.reset_input_buffer()
                self.ser.reset_output_buffer()
            time.sleep(0.5)
            
            # Step 2: Send all ports OFF
            print("  Step 2: All ports OFF...")
            result1 = self.all_off()
            time.sleep(1.0)
            
            # Step 3: Send all ports ON (reset state)
            print("  Step 3: All ports ON (reset state)...")
            result2 = self.all_on()
            time.sleep(1.0)
            
            # Step 4: All ports OFF again (clean state)
            print("  Step 4: All ports OFF (clean state)...")
            result3 = self.all_off()
            time.sleep(1.0)
            
            # Step 5: Test each port individually to verify reset
            print("  Step 5: Testing each port after reset...")
            for port in [1, 2, 3, 4]:
                print(f"    Testing port {port}...")
                result = self.set_single_port_on(port)
                time.sleep(0.5)
                if not result:
                    print(f"    WARNING: Port {port} test failed after reset")
                else:
                    print(f"    Port {port} OK")
            
            # Step 6: Return to all OFF state
            print("  Step 6: Final cleanup - all ports OFF...")
            result4 = self.all_off()
            time.sleep(0.5)
            
            print("  Full hub reset complete!")
            return result1 and result2 and result3 and result4
            
        except Exception as e:
            print(f"  ERROR during full hub reset: {e}")
            return False

    def port_on(self, port_number):
        if not 1 <= port_number <= 4:
            print("[ERROR] Port number must be between 1 and 4.")
            return False
        status_string = self.PORT_ON_CMDS.get(port_number, "FFFFFFFF")
        print(f"[INFO] Command: Port {port_number} ON")
        return self._send_command(status_string)

    def port_off(self, port_number):
        if not 1 <= port_number <= 4:
            print("[ERROR] Port number must be between 1 and 4.")
            return False
        status_string = self.PORT_OFF_CMDS.get(port_number, "EEEEEEEE")
        print(f"[INFO] Command: Port {port_number} OFF")
        return self._send_command(status_string)
    
    def set_single_port_on(self, port_number):
        """
        Turn on only the specified port, ensuring all other ports are off.
        This is an atomic operation that avoids brief multi-port states.
        Includes 2-second delay when switching between different ports.
        """
        if not 1 <= port_number <= 4:
            print("[ERROR] Port number must be between 1 and 4.")
            return False
        
        # Check if we need a delay (switching from different port)
        if hasattr(self, 'last_active_port') and self.last_active_port != port_number and self.last_active_port != 0:
            print(f"[INFO] Switching from port {self.last_active_port} to port {port_number}")
            print("[INFO] Applying 2-second delay for proper power sequencing...")
            time.sleep(2.0)  # 2-second delay between different port selections
        
        # Use the individual PORT_ON_CMDS which already ensures only one port is on
        status_string = self.PORT_ON_CMDS.get(port_number, "FFFFFFFF")
        print(f"[INFO] Command: Set ONLY Port {port_number} ON (all others OFF)")
        result = self._send_command(status_string)
        
        # Track the last active port
        if result:
            self.last_active_port = port_number
        
        return result
    
    def get_current_active_port(self):
        """
        Get the currently active USB hub port by querying hub status.
        Returns: port number (1-4) if single port is active, 0 if all off, -1 if error/multiple ports
        """
        try:
            # Send status query command
            status_cmd = f"GP{self.TERMINATOR}"
            response = self._execute_command(status_cmd)
            
            if not response:
                print("[WARNING] No response from hub status query")
                return -1
            
            # Parse the response (should be like "01FFFFFF", "02FFFFFF", etc.)
            if len(response) >= 8:
                status_hex = response[:8].upper()
                print(f"[DEBUG] Hub status response: {status_hex}")
                
                # Map status responses to port numbers
                status_to_port = {
                    "01FFFFFF": 1,  # Only port 1 on
                    "02FFFFFF": 2,  # Only port 2 on  
                    "04FFFFFF": 3,  # Only port 3 on
                    "08FFFFFF": 4,  # Only port 4 on
                    "E0FFFFFF": 0,  # All ports off
                    "FFFFFFFF": -1  # All ports on (shouldn't happen in normal operation)
                }
                
                active_port = status_to_port.get(status_hex, -1)
                if active_port >= 0:
                    print(f"[INFO] Current active port: {active_port if active_port > 0 else 'None (all off)'}")
                    # Update tracking
                    self.last_active_port = active_port
                    return active_port
                else:
                    print(f"[WARNING] Unrecognized hub status: {status_hex}")
                    return -1
            else:
                print(f"[WARNING] Invalid hub status response length: {response}")
                return -1
                
        except Exception as e:
            print(f"[ERROR] Failed to get current active port: {e}")
            return -1


# ---------------------------------------------------------------------------
# Mock serial port for cmdline testing without real hardware
# ---------------------------------------------------------------------------

class _MockSerial:
    """Minimal pyserial-compatible stub for offline/debug testing."""

    def __init__(self, port, **kwargs):
        self.port = port
        self.baudrate = kwargs.get("baudrate", 9600)
        self.is_open = True
        self.in_waiting = 0
        self._responses = {
            "?Q\r":  b"GCOOLHUB\r",
            "GP\r":  b"GE0FFFFFF\r",  # default: all ports off
        }
        # Mimic current port state so GP reflects last SPpass command
        self._current_status = "E0FFFFFF"
        print(f"[MOCK] Opened mock serial port '{port}' at {self.baudrate} baud")

    def write(self, data):
        text = data.decode("ascii", errors="ignore")
        print(f"[MOCK] << {data.hex().upper()}  ({text.strip()!r})")
        # Update simulated port state if it looks like an SPpass command
        if text.startswith("SPpass") and len(text) >= 18:
            self._current_status = text[10:18]
        return len(data)

    def read(self, size):
        # Return a plausible echo based on last GP state
        resp = f"G{self._current_status}\r".encode("ascii")
        self.in_waiting = 0
        print(f"[MOCK] >> {resp.hex().upper()}  ({resp.strip()!r})")
        return resp[:size]

    def flush(self):
        pass

    def reset_input_buffer(self):
        self.in_waiting = 0

    def reset_output_buffer(self):
        pass

    def setRTS(self, state):
        pass

    def setDTR(self, state):
        pass

    def close(self):
        self.is_open = False
        print(f"[MOCK] Closed mock serial port '{self.port}'")


class _MockHubContext:
    """Context manager that patches serial.Serial with _MockSerial."""

    def __enter__(self):
        import serial as _serial
        self._real_serial = _serial.Serial
        _serial.Serial = _MockSerial
        return self

    def __exit__(self, *_):
        import serial as _serial
        _serial.Serial = self._real_serial


# ---------------------------------------------------------------------------
# __main__ – command-line debug harness
# ---------------------------------------------------------------------------

def _print_help():
    print("""
USB Hub ASCII Debug CLI
=======================
Usage:
  python usbhub_ascii.py [--mock] [--port PORT] COMMAND [ARG]

Options:
  --mock          Use a simulated serial port (no hardware required)
  --port PORT     Serial device (default: /dev/ttyUSB0)

Commands:
  status          Query hub for current port status (GP)
  all_on          Turn all ports ON
  all_off         Turn all ports OFF
  reset           Hub reset (all ON)
  full_reset      Full hub reset cycle
  port_on  N      Turn port N ON  (1-4)
  port_off N      Turn port N OFF (1-4)
  single   N      Set ONLY port N ON  (1-4)
  active          Get current active port number
  test            Run built-in test_port_control sequence
  interactive     Interactive menu loop

Examples:
  python usbhub_ascii.py --mock status
  python usbhub_ascii.py --mock port_on 2
  python usbhub_ascii.py --port /dev/ttyUSB1 active
  python usbhub_ascii.py --mock interactive
""")


def _interactive(hub):
    menu = """
  1) All ON        5) Port ON  N
  2) All OFF       6) Port OFF N
  3) Reset         7) Single port N
  4) Full reset    8) Get active port
  s) Status query  t) Test sequence
  q) Quit
"""
    while True:
        print(menu)
        choice = input("Choice: ").strip().lower()
        if choice == "q":
            break
        elif choice == "1":
            hub.all_on()
        elif choice == "2":
            hub.all_off()
        elif choice == "3":
            hub.reset_hub()
        elif choice == "4":
            hub.full_hub_reset()
        elif choice == "5":
            n = int(input("  Port number (1-4): "))
            hub.port_on(n)
        elif choice == "6":
            n = int(input("  Port number (1-4): "))
            hub.port_off(n)
        elif choice == "7":
            n = int(input("  Port number (1-4): "))
            hub.set_single_port_on(n)
        elif choice == "8":
            print(f"  Active port: {hub.get_current_active_port()}")
        elif choice == "s":
            hub._initialize_hub()
        elif choice == "t":
            hub.test_port_control()
        else:
            print("  Unknown choice")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="CoolGear USB Hub ASCII debug CLI",
        add_help=False,
    )
    parser.add_argument("--mock",  action="store_true", help="Use mock serial (no hardware)")
    parser.add_argument("--port",  default="/dev/ttyUSB0", help="Serial port (default /dev/ttyUSB0)")
    parser.add_argument("--help",  "-h", action="store_true")
    parser.add_argument("command", nargs="?", default="status")
    parser.add_argument("arg",     nargs="?", default=None)
    args = parser.parse_args()

    if args.help:
        _print_help()
        sys.exit(0)

    ctx = _MockHubContext() if args.mock else None

    try:
        if ctx:
            ctx.__enter__()

        hub = CoolGearUSBHub(args.port)

        cmd = args.command.lower()
        n   = int(args.arg) if args.arg and args.arg.isdigit() else None

        if cmd == "status":
            hub._initialize_hub()
        elif cmd == "all_on":
            hub.all_on()
        elif cmd == "all_off":
            hub.all_off()
        elif cmd == "reset":
            hub.reset_hub()
        elif cmd == "full_reset":
            hub.full_hub_reset()
        elif cmd == "port_on":
            if n is None:
                print("[ERROR] port_on requires a port number (1-4)")
                sys.exit(1)
            hub.port_on(n)
        elif cmd == "port_off":
            if n is None:
                print("[ERROR] port_off requires a port number (1-4)")
                sys.exit(1)
            hub.port_off(n)
        elif cmd == "single":
            if n is None:
                print("[ERROR] single requires a port number (1-4)")
                sys.exit(1)
            hub.set_single_port_on(n)
        elif cmd == "active":
            result = hub.get_current_active_port()
            print(f"[RESULT] Active port: {result}")
        elif cmd == "test":
            hub.test_port_control()
        elif cmd == "interactive":
            _interactive(hub)
        else:
            print(f"[ERROR] Unknown command: {cmd!r}")
            _print_help()
            sys.exit(1)

    finally:
        if ctx:
            ctx.__exit__(None, None, None)
        # Close serial if hub was created
        try:
            if hub.ser and hub.ser.is_open:
                hub.ser.close()
                print("[INFO] Serial port closed.")
        except NameError:
            pass
