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
from queue import Queue, Empty

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# CONSTANTS
DEV_MAC1 = 'F8:33:31:56:ED:16'
DEV_MAC2 = 'F8:33:31:56:FB:8E'
CHARACTERISTIC_UUID = '0000ffe1-0000-1000-8000-00805f9b34fb'
NOTIFICATION_HANDLE = '0x0013'  # The handle that worked in manual testing
DATA_HANDLE = '0x0012'  # The actual data handle (discovered from testing!)
ADAPTER = 'hci1'  # USB adapter

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
                if self.debug_level > 0:
                    logger.info(f"Published to {topic}: {data}")
                return True
            else:
                logger.error(f"MQTT publish failed: {result.rc}")
                return False
                
        except Exception as e:
            logger.error(f"MQTT publish error: {e}")
            return False

def configure_bluetooth():
    """Configure Bluetooth adapters for optimal operation"""
    logger.info("=== Configuring Bluetooth Adapters ===")
    
    try:
        # Stop bluetooth service
        logger.info("Stopping bluetooth service...")
        subprocess.run(['systemctl', 'stop', 'bluetooth'], 
                      capture_output=True, timeout=10)
        time.sleep(2)
        
        # Unblock bluetooth
        subprocess.run(['rfkill', 'unblock', 'bluetooth'], 
                      capture_output=True, timeout=5)
        
        # Configure adapters
        logger.info("Configuring adapters...")
        subprocess.run(['hciconfig', 'hci0', 'down'], 
                      capture_output=True, timeout=5)
        subprocess.run(['hciconfig', 'hci1', 'down'], 
                      capture_output=True, timeout=5)
        time.sleep(1)
        subprocess.run(['hciconfig', 'hci1', 'up'], 
                      capture_output=True, timeout=5)
        time.sleep(2)
        
        # Restart bluetooth service
        logger.info("Restarting bluetooth service...")
        subprocess.run(['systemctl', 'start', 'bluetooth'], 
                      capture_output=True, timeout=10)
        time.sleep(3)
        
        # Verify configuration
        result = subprocess.run(['hciconfig'], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            if 'hci1:' in result.stdout and 'UP RUNNING' in result.stdout:
                logger.info("✓ USB adapter (hci1) is UP and RUNNING")
                return True
            else:
                logger.warning("USB adapter (hci1) not in optimal state")
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
# -*- coding: utf-8 -*-
"""
Alternative bat2mqtt implementation using pygatt for better reliability
pygatt provides more direct BlueZ integration and better connection stability
"""

import logging
import os
import subprocess
import sys
import time
import threading
from queue import Queue, Empty

try:
    import pygatt
except ImportError:
    print("pygatt not installed. Install with: pip install pygatt")
    sys.exit(1)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Device constants
BATTERY_DEVICES = {
    'DEV_MAC1': 'F8:33:31:56:ED:16',
    'DEV_MAC2': 'F8:33:31:56:FB:8E'
}
CHARACTERISTIC_UUID = '0000ffe1-0000-1000-8000-00805f9b34fb'

# Connection settings
MAX_CONNECTION_ATTEMPTS = 10
CONNECTION_TIMEOUT = 30
SCAN_TIMEOUT = 15
RETRY_DELAY = 10

# Global variables
adapter = None
device = None
LastMessage = ""
MsgCount = 0
Debug = 0
DataReceived = False
mqtt_client = None
shutdown_event = threading.Event()
message_queue = Queue()

def reset_bluetooth_stack():
    """Reset Bluetooth stack to clear any stuck states"""
    logger.info("Performing Bluetooth stack reset...")
    try:
        # Run the reset script
        result = subprocess.run(['./bt_stack_reset.sh', '-s'], 
                              capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            logger.info("✓ Bluetooth stack reset successful")
            return True
        else:
            logger.warning(f"Reset script returned {result.returncode}: {result.stderr}")
            return False
    except Exception as e:
        logger.warning(f"Reset script failed: {e}")
        return False

def configure_bluetooth_for_pygatt():
    """Configure Bluetooth specifically for pygatt usage"""
    logger.info("=== Bluetooth Configuration for pygatt ===")
    
    try:
        # In container, we're already root, so no sudo needed
        # Stop bluetooth service
        subprocess.run(['systemctl', 'stop', 'bluetooth'], 
                      capture_output=True, timeout=10)
        time.sleep(2)
        
        # Unblock bluetooth
        subprocess.run(['rfkill', 'unblock', 'bluetooth'], 
                      capture_output=True, timeout=5)
        
        # Reset USB adapter if available
        result = subprocess.run(['hciconfig'], capture_output=True, text=True)
        if 'hci1:' in result.stdout:
            logger.info("Resetting USB adapter...")
            subprocess.run(['hciconfig', 'hci1', 'down'], capture_output=True)
            subprocess.run(['hciconfig', 'hci1', 'up'], capture_output=True)
            time.sleep(2)
            adapter_name = 'hci1'
        elif 'hci0:' in result.stdout:
            logger.info("Using built-in adapter...")
            subprocess.run(['hciconfig', 'hci0', 'down'], capture_output=True)
            subprocess.run(['hciconfig', 'hci0', 'up'], capture_output=True)
            time.sleep(2)
            adapter_name = 'hci0'
        else:
            logger.error("No Bluetooth adapter found")
            return None
        
        # Start bluetooth service
        subprocess.run(['systemctl', 'start', 'bluetooth'], 
                      capture_output=True, timeout=10)
        time.sleep(3)
        
        logger.info(f"✓ Bluetooth configured for adapter: {adapter_name}")
        return adapter_name
        
    except Exception as e:
        logger.error(f"Bluetooth configuration failed: {e}")
        return None

def discover_battery_devices(adapter):
    """Discover available battery devices using pygatt"""
    logger.info("=== Battery Device Discovery ===")
    
    try:
        logger.info(f"Scanning for devices (timeout: {SCAN_TIMEOUT}s)...")
        devices = adapter.scan(timeout=SCAN_TIMEOUT)
        
        # Reset adapter after scan when running as root (required by pygatt)
        try:
            adapter.reset()
            logger.debug("✓ Adapter reset after scan")
        except Exception as e:
            logger.warning(f"Adapter reset warning: {e}")
        
        logger.info(f"Found {len(devices)} devices")
        
        available_batteries = []
        
        for device_info in devices:
            device_address = device_info['address'].upper()
            device_name = device_info.get('name', 'Unknown')
            
            for battery_id, battery_mac in BATTERY_DEVICES.items():
                if device_address == battery_mac.upper():
                    available_batteries.append({
                        'id': battery_id,
                        'mac': device_info['address'],
                        'name': device_name,
                        'rssi': device_info.get('rssi', 'N/A')
                    })
                    logger.info(f"*** FOUND BATTERY: {battery_id} ***")
                    logger.info(f"    MAC: {device_info['address']}")
                    logger.info(f"    Name: {device_name}")
                    logger.info(f"    RSSI: {device_info.get('rssi', 'N/A')} dBm")
        
        return available_batteries
        
    except Exception as e:
        logger.error(f"Device discovery failed: {e}")
        return []

def notification_callback(handle, value):
    """Callback for battery data notifications"""
    global LastMessage, MsgCount, DataReceived, mqtt_client
    
    try:
        if not DataReceived:
            logger.info("✓ Receiving battery data...")
            DataReceived = True
        
        # Add to message queue for processing
        message_queue.put(value)
        
    except Exception as e:
        logger.error(f"Notification callback error: {e}")

def process_battery_data():
    """Process battery data from the message queue"""
    global LastMessage, MsgCount, mqtt_client, Debug
    
    while not shutdown_event.is_set():
        try:
            # Get data with timeout
            data = message_queue.get(timeout=1.0)
            
            if Debug > 2:
                logger.debug(f"Raw data: {data}")
            
            LastMessage += data.decode("utf-8", errors='ignore')
            
            # Check for end of message
            if LastMessage.endswith('\n'):
                if Debug > 0:
                    logger.info(f"Complete message: {repr(LastMessage.strip())}")
                
                # Parse and process battery data
                if len(LastMessage) > 30:  # Valid message length
                    try:
                        parts = LastMessage.split(',')
                        if len(parts) >= 4:
                            volt_str = parts[0].strip()
                            if volt_str.replace('.', '').isdigit():
                                volt = float(volt_str)
                                
                                # Publish to MQTT if available and not in debug mode
                                if Debug < 2 and mqtt_client:
                                    try:
                                        mqtt_client.publish_single("battery/voltage", volt)
                                        MsgCount += 1
                                        if MsgCount % 10 == 0:
                                            logger.info(f"Published {MsgCount} battery messages")
                                    except Exception as e:
                                        logger.error(f"MQTT publish failed: {e}")
                    
                    except (ValueError, IndexError) as e:
                        logger.warning(f"Data parsing error: {e}")
                
                LastMessage = ""  # Reset for next message
            
            message_queue.task_done()
            
        except Empty:
            continue  # Timeout, check shutdown event
        except Exception as e:
            logger.error(f"Data processing error: {e}")

def connect_to_battery(adapter, battery_mac):
    """Connect to battery and setup notifications using pygatt"""
    global device
    
    logger.info(f"=== Connecting to Battery ===")
    logger.info(f"Target: {battery_mac}")
    
    for attempt in range(MAX_CONNECTION_ATTEMPTS):
        try:
            logger.info(f"Connection attempt {attempt + 1}/{MAX_CONNECTION_ATTEMPTS}")
            
            # Disconnect any existing connection
            if device:
                try:
                    device.disconnect()
                except:
                    pass
                device = None
            
            # Connect to device
            device = adapter.connect(battery_mac, timeout=CONNECTION_TIMEOUT)
            logger.info(f"✓ Connected to {battery_mac}")
            
            # Setup notifications
            logger.info(f"Setting up notifications for {CHARACTERISTIC_UUID}")
            device.subscribe(CHARACTERISTIC_UUID, callback=notification_callback)
            logger.info("✓ Notifications setup complete")
            
            return True
            
        except pygatt.exceptions.NotConnectedError:
            logger.error(f"Connection failed - device not reachable")
        except pygatt.exceptions.BLEError as e:
            logger.error(f"BLE error: {e}")
        except Exception as e:
            logger.error(f"Connection error: {e}")
        
        # Perform Bluetooth reset after 3 failed attempts
        if attempt == 2:  # After 3rd attempt (0-indexed)
            logger.info("Multiple connection failures - attempting Bluetooth reset...")
            reset_bluetooth_stack()
            time.sleep(5)  # Give reset time to take effect
        
        if attempt < MAX_CONNECTION_ATTEMPTS - 1:
            logger.info(f"Retrying in {RETRY_DELAY} seconds...")
            time.sleep(RETRY_DELAY)
    
    logger.error("All connection attempts failed")
    return False

def monitor_connection():
    """Monitor connection health and handle reconnections"""
    global device, adapter
    
    logger.info("=== Connection Monitor Started ===")
    
    while not shutdown_event.is_set():
        try:
            if device:
                # Simple connection check - try to read a characteristic
                try:
                    # This will raise an exception if disconnected
                    device.char_read(CHARACTERISTIC_UUID)
                    time.sleep(30)  # Check every 30 seconds
                    continue
                except:
                    logger.warning("Connection lost - attempting reconnection")
                    device = None
            
            # Need to reconnect
            logger.info("Attempting to reconnect...")
            
            # Rediscover devices
            batteries = discover_battery_devices(adapter)
            if batteries:
                battery = batteries[0]  # Use first available
                if connect_to_battery(adapter, battery['mac']):
                    logger.info("✓ Reconnection successful")
                else:
                    logger.error("Reconnection failed")
                    time.sleep(60)  # Wait before trying again
            else:
                logger.error("No battery devices found for reconnection")
                time.sleep(60)
        
        except Exception as e:
            logger.error(f"Connection monitor error: {e}")
            time.sleep(30)

def _mqtt_connect():
    """Connect to MQTT broker"""
    global mqtt_client
    
    try:
        from mqttclient import MqttPubClient
        
        max_attempts = 5
        for attempt in range(max_attempts):
            try:
                mqtt_client = MqttPubClient()
                logger.info(f"✓ MQTT connected")
                return True
            except Exception as e:
                logger.warning(f"MQTT connection attempt {attempt + 1} failed: {e}")
                if attempt < max_attempts - 1:
                    time.sleep(5)
        
        logger.error("MQTT connection failed")
        return False
        
    except ImportError:
        logger.error("mqttclient module not found")
        return False

def main():
    """Main function using pygatt"""
    global Debug, adapter, device
    
    # Get debug level
    Debug = int(os.environ.get('DEBUG_LEVEL', '0'))
    
    logger.info("=== pygatt bat2mqtt Starting ===")
    logger.info(f"Debug level: {Debug}")
    
    try:
        # Configure Bluetooth
        adapter_name = configure_bluetooth_for_pygatt()
        if not adapter_name:
            logger.error("Bluetooth configuration failed")
            return False
        
        # Create pygatt adapter
        logger.info("Initializing pygatt adapter...")
        adapter = pygatt.GATTToolBackend()
        adapter.start()
        logger.info("✓ pygatt adapter started")
        
        # Wait for MQTT broker
        logger.info("Waiting for MQTT broker...")
        time.sleep(10)
        
        # Connect to MQTT
        if Debug < 2:
            _mqtt_connect()
        
        # Start data processing thread
        processing_thread = threading.Thread(target=process_battery_data, daemon=True)
        processing_thread.start()
        
        # Discover and connect to battery
        batteries = discover_battery_devices(adapter)
        if not batteries:
            logger.error("No battery devices found")
            return False
        
        # Use first available battery
        battery = batteries[0]
        logger.info(f"Selected battery: {battery['id']} ({battery['mac']})")
        
        if not connect_to_battery(adapter, battery['mac']):
            logger.error("Initial connection failed")
            return False
        
        # Start connection monitor
        monitor_thread = threading.Thread(target=monitor_connection, daemon=True)
        monitor_thread.start()
        
        # Main loop
        logger.info("=== Main Loop Started ===")
        logger.info("Press Ctrl+C to stop")
        
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Shutdown requested")
        
    except Exception as e:
        logger.error(f"Main function error: {e}")
        return False
    
    finally:
        # Cleanup
        logger.info("Cleaning up...")
        shutdown_event.set()
        
        if device:
            try:
                device.disconnect()
            except:
                pass
        
        if adapter:
            try:
                adapter.stop()
            except:
                pass
        
        logger.info("pygatt bat2mqtt shutdown complete")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)
