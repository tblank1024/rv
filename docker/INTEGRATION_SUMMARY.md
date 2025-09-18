# Integration Summary: bat2mqtt gatttool in Docker Compose

## ✅ Integration Complete

The **bat2mqtt gatttool implementation** has been successfully integrated into the main docker-compose.yml file.

### What's Now Available

**Service Name:** `bat2mqtt`
**Container Name:** `battery`
**Image:** `bat2mqtt:gatttool`

### Configuration
```yaml
bat2mqtt:
  build:
    context: /home/tblank/code/tblank1024/rv/bat2mqtt
    dockerfile: Dockerfile.gatttool
  container_name: battery
  network_mode: host
  privileged: true
  environment:
    - DEBUG_LEVEL=1        # 0=production, 1=debug
    - MQTT_HOST=localhost
    - MQTT_PORT=1883
```

### Key Features
- **Direct gatttool**: Uses subprocess calls to gatttool for maximum reliability
- **USB Bluetooth**: Configured for hci1 USB adapter
- **MQTT Integration**: Publishes to RVC/_var/BATTERY_STATUS
- **Persistent Logs**: Stored in /home/tblank/code/tblank1024/rv/bat2mqtt/logs
- **Auto-restart**: Restarts on container failure

### Deployment Commands

**Start the full RV monitoring stack:**
```bash
cd /home/tblank/code/tblank1024/rv/docker
docker-compose up -d --build
```

**Monitor battery service logs:**
```bash
docker-compose logs -f battery
```

**Restart just the battery service:**
```bash
docker-compose restart battery
```

**Stop all services:**
```bash
docker-compose down
```

### Environment Variables
- `DEBUG_LEVEL=0`: Production mode (MQTT enabled, minimal logging)
- `DEBUG_LEVEL=1`: Debug mode (MQTT enabled, detailed logging)
- `DEBUG_LEVEL=2`: Debug mode (MQTT disabled for testing)

### Files Used
- `bat2mqtt_gatttool.py` - Main application
- `Dockerfile.gatttool` - Container definition
- `requirements_gatttool.txt` - Python dependencies (just paho-mqtt)

The integration is complete and ready for production use!
