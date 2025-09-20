#!/usr/bin/env python3
"""
Super-simplified bat2mqtt with persistent gatttool process
Single gatttool process + simple reader thread = much simpler!
"""

import subprocess
import threading
import time
import json
import re
import sys
import os
import signal
import queue

# Configuration
DEV_MAC = 'F8:33:31:56:ED:16'
NOTIFICATION_HANDLE = '0x0013'
DATA_HANDLE = '0x0012'
ADAPTER = 'hci1'
MQTT_HOST = 'localhost'
MQTT_PORT = 1883
DEBUG = int(os.environ.get('DEBUG_LEVEL', '0'))

# Global state
running = True
mqtt_client = None
message_queue = queue.Queue()

def log(message):
    """Simple logging with timestamp"""
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    print(f"[{timestamp}] {message}", flush=True)

def signal_handler(signum, frame):
    """Handle shutdown signals"""
    global running
    log(f"Received signal {signum}, shutting down...")
    running = False

def setup_mqtt():
    """Initialize MQTT client"""
    global mqtt_client
    
    try:
        import paho.mqtt.client as mqtt
        
        # Create MQTT client with compatibility for different paho-mqtt versions
        try:
            mqtt_client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
        except (AttributeError, TypeError):
            mqtt_client = mqtt.Client()
            
        mqtt_client.connect(MQTT_HOST, MQTT_PORT, 60)
        mqtt_client.loop_start()
        log("MQTT connected")
        return True
        
    except ImportError:
        log("Warning: paho-mqtt not installed, MQTT disabled")
        return False
    except Exception as e:
        log(f"MQTT connection failed: {e}")
        return False

def publish_battery_data(voltage, current, temperature, charge, status):
    """Publish battery data to MQTT"""
    if not mqtt_client:
        return
        
    try:
        data = {
            "instance": 1,
            "name": "BATTERY_STATUS",
            "DC_voltage": voltage,
            "DC_current": current,
            "State_of_charge": charge,
            "Status": status,
            "timestamp": int(time.time())
        }
        
        topic = "RVC/BATTERY_STATUS/1"
        result = mqtt_client.publish(topic, json.dumps(data))
        
        if DEBUG > 1:
            log(f"Published: V={voltage:.2f}, A={current}, SOC={charge}%")
            
    except Exception as e:
        log(f"MQTT publish error: {e}")

def detect_usb_bluetooth_adapter():
    """Find USB Bluetooth adapter"""
    try:
        result = subprocess.run(['hciconfig'], capture_output=True, text=True, timeout=5)
        if result.returncode != 0:
            return None
            
        for line in result.stdout.split('\n'):
            if line.startswith('hci') and 'Type: Primary  Bus: USB' in line:
                adapter = line.split(':')[0].strip()
                log(f"Found USB Bluetooth adapter: {adapter}")
                return adapter
                
        log("No USB Bluetooth adapter found")
        return None
        
    except Exception as e:
        log(f"Bluetooth detection failed: {e}")
        return None

def configure_bluetooth():
    """Configure Bluetooth adapter"""
    global ADAPTER
    
    usb_adapter = detect_usb_bluetooth_adapter()
    if usb_adapter:
        ADAPTER = usb_adapter
        log(f"Using adapter: {ADAPTER}")
    else:
        log(f"Using default adapter: {ADAPTER}")
    
    try:
        subprocess.run(['hciconfig', ADAPTER, 'up'], capture_output=True, timeout=5)
        log(f"Bluetooth adapter {ADAPTER} configured")
        return True
        
    except Exception as e:
        log(f"Bluetooth configuration failed: {e}")
        return False

def parse_battery_data(raw_data):
    """Parse battery data from raw message"""
    try:
        cleaned = raw_data.strip().replace('\n', '').replace('\r', '')
        fields = cleaned.split(',')
        
        if len(fields) < 9:
            if DEBUG:
                log(f"Incomplete data: {len(fields)} fields")
            return None
        
        voltage = float(fields[0]) / 100
        temperature = int(fields[5])
        current = 2 * int(fields[7])
        charge = int(fields[8])
        status = fields[9][:6] if len(fields) > 9 else "000000"
        
        return {
            'voltage': voltage,
            'current': current,
            'temperature': temperature,
            'charge': charge,
            'status': status
        }
        
    except (ValueError, IndexError) as e:
        if DEBUG:
            log(f"Parse error: {e} - Data: {raw_data}")
        return None

def gatttool_reader_thread(gatttool_process):
    """
    Thread that reads from gatttool and puts complete messages in queue
    This runs once and handles all messages - much simpler!
    """
    message_buffer = ""
    
    try:
        log("Reader thread started")
        
        while running and gatttool_process.poll() is None:
            line = gatttool_process.stdout.readline()
            if not line:
                time.sleep(0.1)
                continue
                
            line = line.strip()
            
            if DEBUG >= 3:
                log(f"gatttool: {line}")
            
            # Look for notification data from handle 0x0012
            if 'Notification handle' in line and '0x0012' in line and 'value:' in line:
                hex_match = re.search(r'value:\s*([0-9a-fA-F\s]+)', line)
                if hex_match:
                    hex_data = hex_match.group(1).strip()
                    hex_values = hex_data.split()
                    
                    try:
                        byte_data = bytes([int(h, 16) for h in hex_values])
                        message_part = byte_data.decode("utf-8", errors='ignore')
                        message_buffer += message_part
                        
                        # Check for end of message (LF = 0x0A)
                        if byte_data[-1] == 0x0A:
                            if len(message_buffer) > 30:
                                # Put complete message in queue for main thread
                                message_queue.put(message_buffer)
                            message_buffer = ""
                            
                    except (ValueError, UnicodeDecodeError):
                        pass
            
            elif 'connect error' in line.lower() or 'connection refused' in line.lower():
                log(f"Connection error: {line}")
                break
            elif 'characteristic value was written successfully' in line.lower():
                log("Notifications enabled")
                
    except Exception as e:
        log(f"Reader thread error: {e}")
    finally:
        log("Reader thread stopped")

def main():
    """Main program - much simpler with persistent gatttool!"""
    global running
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    log("=== bat2mqtt Super-Simple Implementation ===")
    log(f"Target device: {DEV_MAC}")
    log(f"Debug level: {DEBUG}")
    
    # Configure Bluetooth
    if not configure_bluetooth():
        log("Bluetooth configuration failed")
        sys.exit(1)
    
    # Setup MQTT
    setup_mqtt()
    
    # Start single long-running gatttool process
    cmd = [
        'gatttool',
        '-i', ADAPTER,
        '-b', DEV_MAC,
        '--char-write-req',
        f'--handle={NOTIFICATION_HANDLE}',
        '--value=0100',
        '--listen'
    ]
    
    log("Starting persistent gatttool process...")
    if DEBUG >= 2:
        log(f"Command: {' '.join(cmd)}")
    
    gatttool_process = None
    reader_thread = None
    
    try:
        gatttool_process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )
        
        # Start the reader thread - this handles all the complex BLE stuff
        reader_thread = threading.Thread(
            target=gatttool_reader_thread, 
            args=(gatttool_process,),
            daemon=True
        )
        reader_thread.start()
        
        log("Waiting for battery messages...")
        
        # Counter for initial status messages
        published_count = 0
        
        # Super simple main loop: just process messages from queue!
        while running:
            try:
                # Wait for complete message from reader thread
                message = message_queue.get(timeout=1)
                
                # Parse and publish
                battery_data = parse_battery_data(message)
                if battery_data:
                    publish_battery_data(
                        battery_data['voltage'],
                        battery_data['current'], 
                        battery_data['temperature'],
                        battery_data['charge'],
                        battery_data['status']
                    )
                    
                    published_count += 1
                    
                    # For DEBUG=0: Show first 2 published values, then confirmation message
                    if DEBUG == 0:
                        if published_count <= 2:
                            log(f"Published: V={battery_data['voltage']:.2f}, A={battery_data['current']}, SOC={battery_data['charge']}%")
                        elif published_count == 3:
                            log("Continuing to Receive & Publish Data")
                    else:
                        # For DEBUG>0: Show all messages as before
                        log(f"Battery: {battery_data['voltage']:.2f}V, "
                            f"{battery_data['current']}A, "
                            f"{battery_data['charge']}% SOC")
                        
            except queue.Empty:
                # No message in last second, check if process still alive
                if gatttool_process and gatttool_process.poll() is not None:
                    log("gatttool process died, exiting")
                    break
                continue
                
    except KeyboardInterrupt:
        log("Keyboard interrupt")
    except Exception as e:
        log(f"Main error: {e}")
    finally:
        running = False
        
        # Cleanup
        if gatttool_process:
            try:
                gatttool_process.terminate()
                gatttool_process.wait(timeout=5)
            except:
                try:
                    gatttool_process.kill()
                except:
                    pass
        
        if reader_thread and reader_thread.is_alive():
            reader_thread.join(timeout=2)
        
        if mqtt_client:
            try:
                mqtt_client.loop_stop()
                mqtt_client.disconnect()
            except:
                pass
    
    log("Shutdown complete")

if __name__ == "__main__":
    main()
