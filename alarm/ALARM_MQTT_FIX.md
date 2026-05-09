# MQTT Alarm Integration Fix

This document describes the fix for the webpage alarm buttons not connecting to alarm.py using MQTT.

## Problem
The web interface alarm buttons were not communicating with the physical alarm system running in the alarm Docker container. The alarm system was running independently with physical button controls working, but web commands were not reaching it.

## Solution
Added MQTT communication bridge between the web interface and the alarm system.

### Changes Made

#### 1. alarm.py Changes
- **Added MQTT client support**: Imported `paho.mqtt.client` and `json`
- **MQTT initialization**: Added `setup_mqtt()` method in `__init__`
- **Command listening**: Subscribed to `rv/alarm/bike/command` and `rv/alarm/interior/command` topics
- **Status publishing**: Publishes current state to:
  - `rv/alarm/bike/status` (simple on/off)
  - `rv/alarm/interior/status` (simple on/off) 
  - `rv/alarm/status` (detailed JSON with state names and timestamp)
- **State synchronization**: Calls `publish_status()` whenever alarm state changes
- **Cleanup handling**: Added proper MQTT cleanup on shutdown

#### 2. alarm/requirements.txt Changes
- **Added**: `paho-mqtt==1.6.1` for MQTT communication

#### 3. server.py Changes
- **Improved MQTT client**: Enhanced `set_alarm_via_mqtt()` with better error handling and timing
- **Status reading**: Implemented `get_alarm_status_via_mqtt()` to read actual alarm state via MQTT
- **API endpoint**: Updated `/api/alarmget` to include MQTT status when available
- **Better timeouts**: Added timeouts and connection validation

## MQTT Topics

### Command Topics (Web → Alarm)
- `rv/alarm/bike/command` - Send "on" or "off" to control bike alarm
- `rv/alarm/interior/command` - Send "on" or "off" to control interior alarm

### Status Topics (Alarm → Web)
- `rv/alarm/bike/status` - Current bike alarm state ("on"/"off")
- `rv/alarm/interior/status` - Current interior alarm state ("on"/"off")
- `rv/alarm/status` - Detailed JSON status with state names

## Testing

### Prerequisites
1. MQTT broker (mosquitto) must be running
2. Alarm container must be built with latest changes
3. Both webserver and alarm containers should have `network_mode: host`

### Manual Testing
```bash
# Run the test script
cd /home/tblank/code/tblank1024/rv
python3 test_mqtt_alarm.py
```

### Manual MQTT Testing
```bash
# Subscribe to status topics
mosquitto_sub -h localhost -t "rv/alarm/+/status"

# Send commands
mosquitto_pub -h localhost -t "rv/alarm/bike/command" -m "on"
mosquitto_pub -h localhost -t "rv/alarm/bike/command" -m "off"
```

### Web Interface Testing
1. Open the RV Security web interface
2. Try the alarm buttons for bike and interior
3. Check if the physical alarm system responds
4. Verify status is synchronized between web and physical

## Docker Setup

### Building with Changes
```bash
# Rebuild alarm container with MQTT support
cd /home/tblank/code/tblank1024/rv/alarm
docker build -t alarm:latest .

# Rebuild webserver if needed
cd /home/tblank/code/Joram/RVSecurity
docker build -t webserver:latest .
```

### Running Services
```bash
# Start all services
cd /home/tblank/code/tblank1024/rv/docker
docker-compose up -d

# Check alarm container logs
docker logs alarm

# Check webserver logs  
docker logs webserver
```

## Troubleshooting

### No MQTT Communication
1. Check if MQTT broker is running: `docker logs broker`
2. Check if alarm container started: `docker logs alarm`
3. Verify network connectivity: `docker network ls`
4. Check firewall settings

### Partial Communication
1. Check alarm container logs for MQTT connection errors
2. Verify all containers use `network_mode: host`
3. Test MQTT manually with mosquitto tools
4. Check for timing issues in connection setup

### State Synchronization Issues
1. Check if status messages are being published
2. Verify web interface is reading MQTT status
3. Look for timeout issues in status requests
4. Check for conflicts between direct GPIO and MQTT modes

## Architecture

```
Web Interface (server.py)
    ↓ HTTP POST /api/alarm
    ↓ set_alarm() function
    ↓ set_alarm_via_mqtt()
    ↓ MQTT publish to rv/alarm/{type}/command
    
MQTT Broker (mosquitto)
    ↓ Topic: rv/alarm/{type}/command
    
Alarm System (alarm.py)
    ↓ on_mqtt_message()
    ↓ set_state() 
    ↓ Physical GPIO control
    ↓ publish_status()
    ↓ MQTT publish to rv/alarm/{type}/status
    
MQTT Broker (mosquitto)
    ↓ Topic: rv/alarm/{type}/status
    
Web Interface (server.py)
    ↓ HTTP GET /api/alarmget
    ↓ get_alarm_status_via_mqtt()
    ↓ Displays current state
```

The system now provides bidirectional communication between the web interface and physical alarm system, with the MQTT broker acting as the communication bridge between Docker containers.
