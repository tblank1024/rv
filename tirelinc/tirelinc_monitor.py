#!/usr/bin/env python3
"""
TireLinc TPMS Monitor - GATT to MQTT bridge
Connects to Lippert TireLinc repeater via GATT, decodes tire pressure/temp
notifications, and publishes to MQTT.

Requires: display unplugged (repeater allows only 1 GATT connection)

Usage:
    sudo venv/bin/python3 tirelinc_monitor.py
    sudo ADAPTER=hci1 venv/bin/python3 tirelinc_monitor.py
    sudo TIRE_0=FL TIRE_1=RL_out venv/bin/python3 tirelinc_monitor.py

    # Production (new USB dongle pinned by MAC):
    sudo BT_ADAPTER_MAC=XX:XX:XX:XX:XX:XX venv/bin/python3 tirelinc_monitor.py

Note: env vars must come AFTER sudo:
    CORRECT:   sudo ADAPTER=hci2 venv/bin/python3 ...
    INCORRECT: ADAPTER=hci2 sudo venv/bin/python3 ...  (sudo strips the var)

MQTT output:
    Topic:   RVC/TIRE_STATUS/<position>
    Payload: {"instance": <n>, "name": "<position>", "pressure_psi": <n>,
              "temp_f": <n>, "sensor_id": "<hex>", "timestamp": <unix>}
"""

import asyncio
import json
import os
import subprocess
import sys
import time
from datetime import datetime

from bleak import BleakClient, BleakScanner, BleakError

# ---------------------------------------------------------------------------
# Configuration (all overridable via environment)
# ---------------------------------------------------------------------------
TIRELINC_MAC    = os.environ.get('TIRELINC_MAC',    'F4:CF:A2:85:D0:62')
MQTT_HOST       = os.environ.get('MQTT_HOST',       'localhost')
MQTT_PORT       = int(os.environ.get('MQTT_PORT',   '1883'))
DEBUG           = int(os.environ.get('DEBUG_LEVEL', '0'))
RECONNECT_DELAY = int(os.environ.get('RECONNECT_DELAY', '10'))  # seconds between reconnect attempts

# bat2mqtt's USB dongle MAC - tirelinc will skip this when auto-detecting adapter
BAT2MQTT_ADAPTER_MAC = os.environ.get('BAT2MQTT_ADAPTER_MAC', '08:BE:AC:35:8E:5E').upper()

# Adapter: explicit override, or pinned MAC, or auto-detect (skip bat2mqtt's)
ADAPTER         = os.environ.get('ADAPTER', '').strip()
BT_ADAPTER_MAC  = os.environ.get('BT_ADAPTER_MAC', '').upper().strip()

# Tire position names by index (0-5).
# Ambiguous tires (indices 2, 3, 5 all read 54 PSI) use placeholder names.
# Override when pressures differ to disambiguate, e.g.:
#   sudo TIRE_2=FR TIRE_3=RL_in TIRE_5=RR_in venv/bin/python3 tirelinc_monitor.py
TIRE_NAMES = {
    0: os.environ.get('TIRE_0', 'FL'),
    1: os.environ.get('TIRE_1', 'RL_out'),
    2: os.environ.get('TIRE_2', 'FR'),
    3: os.environ.get('TIRE_3', 'RL_in'),
    4: os.environ.get('TIRE_4', 'RR_out'),
    5: os.environ.get('TIRE_5', 'RR_in'),
}

# GATT UUIDs (Lippert TireLinc repeater)
TIRELINC_SERVICE       = '00000000-00b7-4807-beee-e0b0879cf3dd'
CHAR_TIRE_DATA         = '00000002-00b7-4807-beee-e0b0879cf3dd'  # read + notify
CHAR_CONFIG_WRITE      = '00000001-00b7-4807-beee-e0b0879cf3dd'  # read + write
CHAR_FIRMWARE          = '00000004-00b7-4807-beee-e0b0879cf3dd'  # read only

# Packet types
PKT_DATA   = 0x00  # live tire data: [0]=0x00 [1]=0x0E [2-3]=sensorID [7]=tempF [8-9]=psiBE
PKT_CONFIG = 0x02  # config packet:  [0]=0x02 [1]=0x0E [2-3]=sensorID [14-15]=indexBE

# ---------------------------------------------------------------------------
# Validation limits (overridable via environment)
# ---------------------------------------------------------------------------
MIN_PRESSURE_PSI  = int(os.environ.get('MIN_PRESSURE_PSI',  '50'))
MAX_PRESSURE_PSI  = int(os.environ.get('MAX_PRESSURE_PSI',  '60'))
MAX_TEMP_F        = int(os.environ.get('MAX_TEMP_F',        '150'))
MAX_TEMP_CHANGE_F = int(os.environ.get('MAX_TEMP_CHANGE_F', '60'))

# ---------------------------------------------------------------------------
# Globals
# ---------------------------------------------------------------------------
mqtt_client = None

# Sensor map built from config packets: sensorID_hex -> {"index": n, "name": str}
sensor_map = {}

# Track last published values to suppress duplicate publishes
last_published = {}  # sensorID_hex -> (psi, temp_f)

# Track last raw (unmodified) values for temperature-change detection
last_raw_values: dict = {}  # sensorID_hex -> (raw_psi, raw_temp_f)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
def ts():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')

def log(msg, level=0):
    if level <= DEBUG or level == 0:
        print(f"[{ts()}] {msg}", flush=True)

def dbg(msg):
    log(msg, level=1)

# ---------------------------------------------------------------------------
# Adapter detection
# ---------------------------------------------------------------------------
def detect_adapter():
    """Return adapter to use.
    Priority:
      1. ADAPTER env var (explicit override)
      2. BT_ADAPTER_MAC env var (pin by MAC - for production new dongle)
      3. Auto-detect: first USB adapter that is NOT bat2mqtt's dongle
    """
    if ADAPTER:
        log(f"Using explicit ADAPTER={ADAPTER}")
        return ADAPTER

    try:
        result = subprocess.run(['hciconfig', '-a'], capture_output=True, text=True, timeout=5)
        if result.returncode != 0:
            log("hciconfig failed - falling back to hci1")
            return 'hci1'

        # Parse all adapters
        adapters = []  # list of (hci_name, bus, mac)
        current_hci = None
        current_bus = None
        for line in result.stdout.split('\n'):
            if line.startswith('hci'):
                parts = line.split(':')
                current_hci = parts[0].strip()
                current_bus = 'USB' if 'Bus: USB' in line else ('UART' if 'Bus: UART' in line else 'other')
            if 'BD Address:' in line and current_hci:
                mac = line.strip().split()[2].upper()
                adapters.append((current_hci, current_bus, mac))
                current_hci = None

        dbg(f"Found adapters: {adapters}")

        # BT_ADAPTER_MAC pin
        if BT_ADAPTER_MAC:
            for hci, bus, mac in adapters:
                if mac == BT_ADAPTER_MAC:
                    log(f"Found pinned adapter by MAC {BT_ADAPTER_MAC}: {hci}")
                    return hci
            log(f"WARNING: Pinned MAC {BT_ADAPTER_MAC} not found, falling back to auto-detect")

        # Auto-detect: first USB adapter that is not bat2mqtt's
        for hci, bus, mac in adapters:
            if bus == 'USB' and mac != BAT2MQTT_ADAPTER_MAC:
                log(f"Auto-selected adapter {hci} (MAC {mac}, skipped bat2mqtt's {BAT2MQTT_ADAPTER_MAC})")
                return hci

        # Fallback: any USB adapter
        for hci, bus, mac in adapters:
            if bus == 'USB':
                log(f"WARNING: Using bat2mqtt's adapter {hci} (no other USB adapter found)")
                return hci

        log("No USB Bluetooth adapter found - falling back to hci1")
        return 'hci1'

    except Exception as e:
        log(f"Adapter detection failed: {e} - falling back to hci1")
        return 'hci1'

# ---------------------------------------------------------------------------
# MQTT
# ---------------------------------------------------------------------------
def setup_mqtt():
    global mqtt_client
    try:
        import paho.mqtt.client as mqtt
        try:
            mqtt_client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
        except (AttributeError, TypeError):
            mqtt_client = mqtt.Client()
        mqtt_client.connect(MQTT_HOST, MQTT_PORT, 60)
        mqtt_client.loop_start()
        log(f"MQTT connected to {MQTT_HOST}:{MQTT_PORT}")
        return True
    except ImportError:
        log("WARNING: paho-mqtt not installed - MQTT disabled")
        return False
    except Exception as e:
        log(f"MQTT connection failed: {e}")
        return False

def publish_tire(sensor_id_hex, index, name, psi, temp_f):
    """Publish tire data to MQTT. Suppresses duplicates unless value changed.
    Out-of-range pressure or temperature is flagged by negating the value."""
    global last_published, last_raw_values

    prev = last_published.get(sensor_id_hex)
    if prev == (psi, temp_f):
        dbg(f"  [{name}] no change ({psi} PSI / {temp_f}F) - skipping publish")
        return

    last_published[sensor_id_hex] = (psi, temp_f)

    # --- Validate pressure ---
    pub_psi = psi
    if psi < MIN_PRESSURE_PSI or psi > MAX_PRESSURE_PSI:
        log(f"  WARNING [{name}] pressure {psi} PSI out of range "
            f"[{MIN_PRESSURE_PSI}-{MAX_PRESSURE_PSI}] - flagging")
        pub_psi = -abs(psi)

    # --- Validate temperature ---
    pub_temp = temp_f
    if temp_f > MAX_TEMP_F:
        log(f"  WARNING [{name}] temp {temp_f}F exceeds max {MAX_TEMP_F}F - flagging")
        pub_temp = -abs(temp_f)
    else:
        prev_raw = last_raw_values.get(sensor_id_hex)
        if prev_raw is not None:
            _, prev_temp = prev_raw
            delta = abs(temp_f - prev_temp)
            if delta > MAX_TEMP_CHANGE_F:
                log(f"  WARNING [{name}] temp change {delta}F exceeds max "
                    f"{MAX_TEMP_CHANGE_F}F - flagging")
                pub_temp = -abs(temp_f)

    # Store raw values for next change-detection pass
    last_raw_values[sensor_id_hex] = (psi, temp_f)

    payload = {
        "instance":     index + 1,  # 1-based for RVC convention
        "name":         name,
        "pressure_psi": pub_psi,
        "temp_f":       pub_temp,
        "sensor_id":    sensor_id_hex,
        "timestamp":    int(time.time()),
    }
    topic = f"RVC/TIRE_STATUS/{name}"

    if mqtt_client:
        try:
            mqtt_client.publish(topic, json.dumps(payload))
        except Exception as e:
            log(f"MQTT publish error: {e}")

    log(f"  Published [{name}] {pub_psi} PSI / {pub_temp}F  -> {topic}")

# ---------------------------------------------------------------------------
# Packet decoder
# ---------------------------------------------------------------------------
def decode_packet(data: bytes):
    """
    Decode a 16-byte TireLinc notification packet.

    Type-00 (data):   [0]=0x00 [1]=0x0E [2-3]=sensorID [7]=tempF [8-9]=psiBE
    Type-02 (config): [0]=0x02 [1]=0x0E [2-3]=sensorID [7]=minPSI [8-9]=maxPSI_BE
                      [10-11]=maxTempF_BE [12-13]=maxDtempF_BE [14-15]=tireIndex_BE
    """
    if len(data) < 16:
        dbg(f"  Short packet ({len(data)} bytes) - skipping")
        return

    pkt_type  = data[0]
    sensor_id = int.from_bytes(data[2:4], 'big')
    sensor_hex = f"{sensor_id:04X}"
    spaced    = ' '.join(f'{b:02X}' for b in data)

    dbg(f"  PKT type=0x{pkt_type:02X} sensor={sensor_hex}  [{spaced}]")

    if pkt_type == PKT_CONFIG:
        # Config packet - build sensor map
        tire_index = int.from_bytes(data[14:16], 'big')
        min_psi    = data[7]
        max_psi    = int.from_bytes(data[8:10], 'big')
        max_temp   = int.from_bytes(data[10:12], 'big')
        max_dtemp  = int.from_bytes(data[12:14], 'big')
        name       = TIRE_NAMES.get(tire_index, f"TIRE_{tire_index}")

        sensor_map[sensor_hex] = {"index": tire_index, "name": name}

        log(f"  CONFIG  [{name}] idx={tire_index} sensor={sensor_hex}"
            f"  limits: PSI {min_psi}-{max_psi}  temp<={max_temp}F  dtemp<={max_dtemp}F")

    elif pkt_type == PKT_DATA:
        # Data packet - decode and publish
        temp_f = data[7]
        psi    = int.from_bytes(data[8:10], 'big')

        entry  = sensor_map.get(sensor_hex)
        if entry:
            name  = entry["name"]
            index = entry["index"]
        else:
            # Config not received yet for this sensor - use sensor ID as name
            name  = f"sensor_{sensor_hex}"
            index = -1
            dbg(f"  WARNING: sensor {sensor_hex} not in config map yet")

        log(f"  DATA    [{name}] {psi} PSI / {temp_f}F  (sensor={sensor_hex})")
        publish_tire(sensor_hex, index, name, psi, temp_f)

    else:
        dbg(f"  Unknown packet type 0x{pkt_type:02X} - ignored")

# ---------------------------------------------------------------------------
# GATT connection loop
# ---------------------------------------------------------------------------
async def connect_and_monitor(adapter: str):
    """Connect to TireLinc repeater, subscribe to notifications, decode packets."""
    log(f"Scanning for {TIRELINC_MAC} on {adapter}...")
    try:
        device = await BleakScanner.find_device_by_address(
            TIRELINC_MAC, timeout=8.0, bluez={'adapter': adapter}
        )
        if device is None:
            log(f"  Not found in scan - trying direct connect anyway")
        else:
            log(f"  Found: {device.name} ({device.address})")
    except Exception as e:
        err = str(e).lower()
        if 'in progress' in err or 'already' in err:
            log("  Scan busy - proceeding to connect")
        else:
            log(f"  Scan warning: {e} - proceeding to connect")

    log(f"Connecting to {TIRELINC_MAC} on {adapter}...")
    try:
        async with BleakClient(TIRELINC_MAC, bluez={'adapter': adapter}, timeout=20.0) as client:
            log("Connected!")
            await asyncio.sleep(1.5)  # let adapter settle before GATT ops

            # Read firmware version
            try:
                fw = await client.read_gatt_char('00002a26-0000-1000-8000-00805f9b34fb')
                log(f"Firmware: {fw.decode('ascii', errors='replace').strip()}")
            except Exception:
                pass

            # Subscribe to tire data characteristic — retry once on InProgress
            def notification_handler(sender, data: bytearray):
                decode_packet(bytes(data))

            for _attempt in range(2):
                try:
                    await client.start_notify(CHAR_TIRE_DATA, notification_handler)
                    break
                except BleakError as _e:
                    if 'inprogress' in str(_e).lower().replace('.', '').replace(' ', '') and _attempt == 0:
                        log("  start_notify InProgress - waiting 2s and retrying...")
                        await asyncio.sleep(2.0)
                    else:
                        raise
            log(f"Subscribed to notifications on {CHAR_TIRE_DATA}")
            log("Waiting for tire data...")
            log("")

            # Keep alive until disconnected
            while client.is_connected:
                await asyncio.sleep(1.0)

            log("Disconnected from TireLinc repeater")

    except BleakError as e:
        err = str(e)
        if 'le-connection-abort-by-local' in err:
            log(f"Connection failed: {err}")
            log("  -> hci0 (Pi5 internal BLE) cannot make GATT connections.")
            log("  -> Use a USB BT dongle (ADAPTER=hci1 or hci2).")
        elif 'timeout' in err.lower():
            log(f"Connection timed out: {err}")
            log("  -> Is the Lippert display still plugged in (holding the only GATT slot)?")
        else:
            log(f"BLE error: {err}")
    except Exception as e:
        log(f"Connection error: {e}")

# ---------------------------------------------------------------------------
# Main loop with reconnect
# ---------------------------------------------------------------------------
async def main():
    adapter = detect_adapter()

    # Reset adapter to clear any stale GATT state from a previous container run
    log(f"Resetting adapter {adapter}...")
    try:
        subprocess.run(['hciconfig', adapter, 'down'], capture_output=True, timeout=5)
        await asyncio.sleep(1.0)
        subprocess.run(['hciconfig', adapter, 'up'], capture_output=True, timeout=5)
        await asyncio.sleep(1.0)
    except Exception as e:
        log(f"Adapter reset warning: {e}")

    log("=" * 70)
    log("TireLinc TPMS Monitor")
    log("=" * 70)
    log(f"Target:     {TIRELINC_MAC}")
    log(f"Adapter:    {adapter}")
    log(f"MQTT:       {MQTT_HOST}:{MQTT_PORT}")
    log(f"Tire names: { {k: v for k,v in TIRE_NAMES.items()} }")
    log("")

    setup_mqtt()

    attempt = 0
    while True:
        attempt += 1
        log(f"--- Connection attempt {attempt} ---")
        sensor_map.clear()
        last_published.clear()
        last_raw_values.clear()
        await connect_and_monitor(adapter)
        log(f"Reconnecting in {RECONNECT_DELAY}s...")
        await asyncio.sleep(RECONNECT_DELAY)

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log("Stopped by user")
