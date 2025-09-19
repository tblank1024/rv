#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fixed bat2mqtt implementation using direct gatttool subprocess approach
Replicates the exact successful manual command:
sudo gatttool -i hci1 -b F8:33:31:56:ED:16 --char-write-req --handle=0x0013 --value=0100 --listen

"""

import subprocess
import threading
import time
import sys
import os
import logging
import signal
import re
import json

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# CONSTANTS
DEV_MAC1 = 'F8:33:31:56:ED:16'
DEV_MAC2 = 'F8:33:31:56:FB:8E'
CHARACTERISTIC_UUID = '0000ffe1-0000-1000-8000-00805f9b34fb'
NOTIFICATION_HANDLE = '0x0013'  # The handle that worked in manual testing
DATA_HANDLE = '0x0012'  # The actual data handle (discovered from testing!)
ADAPTER = 'hci1'  # Default USB adapter - will be auto-detected and updated

# Global variables
debug_level = 0
mqtt_client = None
data_received = False
shutdown_event = threading.Event()
gatttool_process = None
last_volt = 0
last_amps = 0
msg_count = 0

class MqttClient:
    """Simple MQTT client wrapper"""
    def __init__(self, host="localhost", port=1883, debug_level=0):
        self.host = host
        self.port = port
        self.connected = False
        self.msg_count = 0
        self.debug_level = debug_level
        
        try:
            import paho.mqtt.client as mqtt
            self.client = mqtt.Client()
            self.mqtt = mqtt
        except ImportError:
            logger.error("paho-mqtt not installed")
            self.client = None
            self.mqtt = None
        
    def connect(self):
        """Connect to MQTT broker with retry logic"""
        if not self.client:
            return False
            
        max_attempts = 5
        for attempt in range(max_attempts):
            try:
                logger.info(f"Connecting to MQTT broker at {self.host}:{self.port} (attempt {attempt + 1})")
                self.client.connect(self.host, self.port, 60)
                self.client.loop_start()
                self.connected = True
                logger.info("✓ MQTT connection established")
                return True
            except Exception as e:
                logger.warning(f"MQTT connection attempt {attempt + 1} failed: {e}")
                if attempt < max_attempts - 1:
                    time.sleep(5)
        
        logger.error("MQTT connection failed after all attempts")
        return False
    
    def publish_battery_data(self, volt, amps, temp, charge, status):
        """Publish battery data to MQTT"""
        if not self.connected or not self.client:
            return False
            
        try:
            timestamp = int(time.time())
            data = {
                "instance": 1,
                "name": "BATTERY_STATUS",
                "DC_voltage": volt,
                "DC_current": amps,
                "State_of_charge": charge,
                "Status": status,
                "timestamp": timestamp
            }
            
            # Publish to the topic format expected by watcher
            topic = "RVC/BATTERY_STATUS/1"
            result = self.client.publish(topic, json.dumps(data))
            
            if result.rc == self.mqtt.MQTT_ERR_SUCCESS:
                self.msg_count += 1
                if self.debug_level > 1:
                    logger.info(f"Published to {topic}: {data}")
                return True
            else:
                logger.error(f"MQTT publish failed: {result.rc}")
                return False
                
        except Exception as e:
            logger.error(f"MQTT publish error: {e}")
            return False

def detect_usb_bluetooth_adapter():
    """
    Automatically detect which Bluetooth adapter is USB-connected.
    Returns the adapter name (e.g., 'hci1') or None if not found.
    """
    logger.info("=== Detecting USB Bluetooth Adapters ===")
    
    try:
        # Method 1: Check hciconfig output for Bus type
        result = subprocess.run(['hciconfig'], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            usb_adapters = []
            lines = result.stdout.split('\n')
            current_adapter = None
            
            for line in lines:
                # Look for adapter lines like "hci1:   Type: Primary  Bus: USB"
                if line.startswith('hci') and ':' in line:
                    current_adapter = line.split(':')[0].strip()
                    # Check if the bus type is on the same line
                    if 'Type: Primary  Bus: USB' in line:
                        usb_adapters.append(current_adapter)
                        logger.info(f"✓ Found USB Bluetooth adapter: {current_adapter}")
                elif current_adapter and 'Bus: USB' in line:
                    usb_adapters.append(current_adapter)
                    logger.info(f"✓ Found USB Bluetooth adapter: {current_adapter}")
            
            if usb_adapters:
                # Return the first USB adapter found
                selected_adapter = usb_adapters[0]
                
                # Method 2: Double-check by examining sysfs uevent
                try:
                    uevent_path = f"/sys/class/bluetooth/{selected_adapter}/device/uevent"
                    with open(uevent_path, 'r') as f:
                        uevent_content = f.read()
                    
                    if 'DEVTYPE=usb_interface' in uevent_content or 'DRIVER=btusb' in uevent_content:
                        logger.info(f"✓ Verified {selected_adapter} is USB-connected via sysfs")
                        
                        # Method 3: Cross-reference with lsusb
                        lsusb_result = subprocess.run(['lsusb'], capture_output=True, text=True, timeout=5)
                        if lsusb_result.returncode == 0 and 'bluetooth' in lsusb_result.stdout.lower():
                            logger.info("✓ USB Bluetooth device confirmed via lsusb")
                        
                        return selected_adapter
                    else:
                        logger.warning(f"Adapter {selected_adapter} not confirmed as USB via sysfs")
                        
                except (IOError, OSError) as e:
                    logger.warning(f"Could not verify {selected_adapter} via sysfs: {e}")
                    # Still return the adapter if hciconfig shows it as USB
                    return selected_adapter
            
            else:
                logger.error("No USB Bluetooth adapters found")
                return None
                
        else:
            logger.error("Failed to run hciconfig")
            return None
            
    except subprocess.TimeoutExpired:
        logger.error("Bluetooth adapter detection timed out")
        return None
    except Exception as e:
        logger.error(f"Bluetooth adapter detection failed: {e}")
        return None

def verify_adapter_is_usb(adapter_name):
    """
    Verify that the specified adapter is actually USB-connected.
    Returns True if confirmed USB, False otherwise.
    """
    try:
        # Check hciconfig output
        result = subprocess.run(['hciconfig', adapter_name], capture_output=True, text=True, timeout=5)
        if result.returncode == 0 and ('Bus: USB' in result.stdout or 'Type: Primary  Bus: USB' in result.stdout):
            logger.info(f"✓ {adapter_name} confirmed as USB adapter via hciconfig")
            
            # Double-check via sysfs
            try:
                uevent_path = f"/sys/class/bluetooth/{adapter_name}/device/uevent"
                with open(uevent_path, 'r') as f:
                    uevent_content = f.read()
                
                if 'DEVTYPE=usb_interface' in uevent_content or 'DRIVER=btusb' in uevent_content:
                    logger.info(f"✓ {adapter_name} USB connection verified via sysfs")
                    return True
                else:
                    logger.warning(f"✗ {adapter_name} is NOT a USB adapter (found: {uevent_content.split('DRIVER=')[1].split()[0] if 'DRIVER=' in uevent_content else 'unknown driver'})")
                    return False
                    
            except (IOError, OSError) as e:
                logger.warning(f"Could not verify {adapter_name} via sysfs: {e}")
                # Fall back to hciconfig result
                return True
                
        else:
            logger.warning(f"✗ {adapter_name} is not a USB adapter or not available")
            return False
            
    except subprocess.TimeoutExpired:
        logger.error(f"Verification of {adapter_name} timed out")
        return False
    except Exception as e:
        logger.error(f"Failed to verify {adapter_name}: {e}")
        return False

def configure_bluetooth():
    """Configure Bluetooth adapters for optimal operation"""
    logger.info("=== Configuring Bluetooth Adapters ===")
    
    # Auto-detect the USB Bluetooth adapter
    usb_adapter = detect_usb_bluetooth_adapter()
    if not usb_adapter:
        logger.error("No USB Bluetooth adapter found - cannot continue")
        return False
    
    logger.info(f"Using USB adapter: {usb_adapter}")
    
    try:
        # Stop bluetooth service
        logger.info("Stopping bluetooth service...")
        subprocess.run(['systemctl', 'stop', 'bluetooth'], 
                      capture_output=True, timeout=10)
        time.sleep(2)
        
        # Unblock bluetooth
        subprocess.run(['rfkill', 'unblock', 'bluetooth'], 
                      capture_output=True, timeout=5)
        
        # Configure adapters - shut down all first
        logger.info("Configuring adapters...")
        # Get all available adapters
        hci_result = subprocess.run(['hciconfig'], capture_output=True, text=True, timeout=5)
        if hci_result.returncode == 0:
            # Extract all adapter names
            adapters = []
            for line in hci_result.stdout.split('\n'):
                if line.startswith('hci') and ':' in line:
                    adapter_name = line.split(':')[0].strip()
                    adapters.append(adapter_name)
            
            # Shut down all adapters
            for adapter in adapters:
                subprocess.run(['hciconfig', adapter, 'down'], 
                              capture_output=True, timeout=5)
        
        time.sleep(1)
        
        # Bring up only the USB adapter
        subprocess.run(['hciconfig', usb_adapter, 'up'], 
                      capture_output=True, timeout=5)
        time.sleep(2)
        
        # Restart bluetooth service
        logger.info("Restarting bluetooth service...")
        subprocess.run(['systemctl', 'start', 'bluetooth'], 
                      capture_output=True, timeout=10)
        time.sleep(3)
        
        # Verify configuration
        result = subprocess.run(['hciconfig', usb_adapter], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            if 'UP RUNNING' in result.stdout:
                logger.info(f"✓ USB adapter ({usb_adapter}) is UP and RUNNING")
                # Update the global ADAPTER variable
                global ADAPTER
                ADAPTER = usb_adapter
                logger.info(f"✓ Updated ADAPTER to: {ADAPTER}")
                return True
            else:
                logger.warning(f"USB adapter ({usb_adapter}) not in optimal state")
                return False
        else:
            logger.error("Failed to query adapter status")
            return False
            
    except subprocess.TimeoutExpired:
        logger.error("Bluetooth configuration timed out")
        return False
    except Exception as e:
        logger.error(f"Bluetooth configuration failed: {e}")
        return False

def parse_battery_data(raw_data):
    """Parse raw battery data from BLE characteristic"""
    try:
        # Clean the data
        cleaned = raw_data.strip().replace('\n', '').replace('\r', '')
        fields = cleaned.split(',')
        # print(f"Debug: Parsed fields: {fields}")
        if len(fields) < 9:
            logger.warning(f"Incomplete data - only {len(fields)} fields: {cleaned}")
            return None
        
        # Parse fields according to the original bat2mqtt.py format
        volt = float(fields[0]) / 100  # Voltage with assumed decimal
        temp = int(fields[5])          # Battery temperature in F
        amps = 2 * int(fields[7])      # Current (2x for monitoring 1 of 2 batteries)
        charge = int(fields[8])        # State of charge percentage
        status = fields[9][:6] if len(fields) > 9 else "000000"  # Status code
        
        return {
            'voltage': volt,
            'temperature': temp,
            'current': amps,
            'charge': charge,
            'status': status
        }
        
    except (ValueError, IndexError) as e:
        logger.error(f"Error parsing battery data: {e}")
        logger.error(f"Raw data: '{raw_data}'")
        return None

def connect_and_monitor_direct(target_mac):
    """
    Direct gatttool connection replicating the exact successful manual command:
    sudo gatttool -i hci1 -b F8:33:31:56:ED:16 --char-write-req --handle=0x0013 --value=0100 --listen
    """
    global gatttool_process, data_received, last_volt, last_amps, msg_count
    
    logger.info(f"=== Starting Direct gatttool Connection ===")
    logger.info(f"Target device: {target_mac}")
    logger.info(f"Adapter: {ADAPTER}")
    logger.info(f"Notification handle: {NOTIFICATION_HANDLE}")
    
    message_buffer = ""
    
    # Open log file if debugging
    log_file = None
    if debug_level > 0:
        try:
            log_file = open("battery_direct_gatttool.log", "w")
            logger.info("✓ Opened log file: battery_direct_gatttool.log")
        except Exception as e:
            logger.warning(f"Failed to open log file: {e}")
    
    try:
        while not shutdown_event.is_set():
            logger.info("Starting direct gatttool connection...")
            
            # Build the exact command that worked manually
            cmd = [
                'gatttool',
                '-i', ADAPTER,
                '-b', target_mac,
                '--char-write-req',
                '--handle=' + NOTIFICATION_HANDLE,
                '--value=0100',
                '--listen'
            ]
            
            if debug_level >= 2:
                logger.info(f"Executing command: {' '.join(cmd)}")
            
            try:
                # Start gatttool process - exactly like the successful manual command
                gatttool_process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    universal_newlines=True
                )
                
                logger.info("gatttool process started, waiting for data...")
                
                # Main data processing loop
                connection_start = time.time()
                last_data_time = time.time()
                
                while not shutdown_event.is_set() and gatttool_process.poll() is None:
                    try:
                        # Read output line by line
                        line = gatttool_process.stdout.readline()
                        if not line:
                            time.sleep(0.1)
                            continue
                            
                        line = line.strip()
                        if debug_level >= 3:
                            logger.debug(f"gatttool output: {line}")
                        
                        # Look for notification data - handle 0x0012 is the data handle
                        if 'Notification handle' in line and '0x0012' in line and 'value:' in line:
                            # Extract hex values
                            hex_match = re.search(r'value:\s*([0-9a-fA-F\s]+)', line)
                            if hex_match:
                                hex_data = hex_match.group(1).strip()
                                hex_values = hex_data.split()
                                
                                try:
                                    # Convert hex to bytes
                                    byte_data = bytes([int(h, 16) for h in hex_values])
                                    
                                    # Decode to string
                                    message_part = byte_data.decode("utf-8", errors='ignore')
                                    message_buffer += message_part
                                    
                                    if debug_level >= 3:
                                        logger.debug(f"Decoded data: {repr(message_part)}")
                                    
                                    # Check for end of message (0x0A LF)
                                    if byte_data[-1] == 0x0A:
                                        if not data_received:
                                            logger.info("✓ Receiving battery data!")
                                            data_received = True
                                        
                                        # Process complete message
                                        if len(message_buffer) > 30:  # Valid message length
                                            battery_data = parse_battery_data(message_buffer)
                                            
                                            if battery_data:
                                                current_time = int(time.time())
                                                volt = battery_data['voltage']
                                                temp = battery_data['temperature']
                                                amps = battery_data['current']
                                                charge = battery_data['charge']
                                                status = battery_data['status']
                                                
                                                if debug_level > 0:
                                                    if msg_count % 20 == 0:
                                                        print("Time     \tVolt\tTemp\tAmps\tFull\tStat")
                                                    
                                                    if last_volt == volt and last_amps == amps:
                                                        print(f"{current_time}\t{volt}\t{temp}\t{amps}\t{charge}\t{status}")
                                                    else:
                                                        print(f"{current_time}\t{volt}\t{temp}\t{amps}\t{charge}\t{status} <-- CHANGED")
                                                        
                                                    last_volt = volt
                                                    last_amps = amps
                                                    msg_count += 1
                                                    
                                                    if log_file:
                                                        log_file.write(f"{current_time},{volt},{temp},{amps},{charge},{status}\n")
                                                        log_file.flush()
                                                
                                                # Publish to MQTT if connected and not in debug mode
                                                if mqtt_client and debug_level < 2:
                                                    mqtt_client.publish_battery_data(
                                                        volt, amps, temp, charge, status
                                                    )
                                        
                                        # Reset message buffer
                                        message_buffer = ""
                                        last_data_time = time.time()
                                
                                except (ValueError, UnicodeDecodeError) as e:
                                    logger.warning(f"Error processing notification data: {e}")
                        
                        elif 'connect error' in line.lower() or 'connection refused' in line.lower():
                            logger.error(f"Connection error: {line}")
                            break
                        elif 'characteristic value was written successfully' in line.lower():
                            logger.info("✓ Notification subscription successful")
                    
                    except Exception as e:
                        logger.error(f"Error processing gatttool output: {e}")
                        break
                
                # Check if we lost the process
                if gatttool_process.poll() is not None:
                    logger.error("gatttool process terminated unexpectedly")
                
            except Exception as e:
                logger.error(f"gatttool execution failed: {e}")
            
            finally:
                # Clean up process
                if gatttool_process:
                    try:
                        gatttool_process.terminate()
                        gatttool_process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        gatttool_process.kill()
                    except Exception as e:
                        logger.error(f"Error terminating gatttool process: {e}")
                    gatttool_process = None
            
            if not shutdown_event.is_set():
                logger.info("Connection lost, retrying in 10 seconds...")
                time.sleep(10)
            
    finally:
        if log_file:
            log_file.close()

def signal_handler(signum, frame):
    """Handle shutdown signals"""
    logger.info(f"Received signal {signum}, shutting down...")
    shutdown_event.set()
    
    if gatttool_process:
        try:
            gatttool_process.terminate()
            time.sleep(1)
            if gatttool_process.poll() is None:
                gatttool_process.kill()
        except Exception as e:
            logger.error(f"Error terminating process: {e}")
    
    # Force exit if signal received multiple times
    import os
    os._exit(1)

def main():
    global debug_level, mqtt_client
    
    # Setup signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Get debug level from environment
    debug_level = int(os.environ.get('DEBUG_LEVEL', '0'))

    logger.info("=== bat2mqtt Direct gatttool Implementation ===")
    logger.info(f"Debug level: {debug_level}")
    logger.info(f"Target device: {DEV_MAC1}")
    logger.info(f"Using adapter: {ADAPTER}")
    logger.info("Replicating successful manual command:")
    logger.info(f"gatttool -i {ADAPTER} -b {DEV_MAC1} --char-write-req --handle={NOTIFICATION_HANDLE} --value=0100 --listen")
    
    # Configure Bluetooth
    if not configure_bluetooth():
        logger.error("Bluetooth configuration failed")
        sys.exit(1)
    
    # Setup MQTT if not in debug mode
    if debug_level < 2:
        logger.info("Setting up MQTT connection...")
        mqtt_client = MqttClient(debug_level=debug_level)
        if not mqtt_client.connect():
            logger.warning("MQTT connection failed - continuing without MQTT")
    
    # Start monitoring using the exact approach that worked manually
    try:
        connect_and_monitor_direct(DEV_MAC1)
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")
        shutdown_event.set()
    except Exception as e:
        logger.error(f"Monitoring failed: {e}")
        shutdown_event.set()
    
    logger.info("Shutdown complete")

if __name__ == "__main__":
    main()
