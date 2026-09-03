#!/usr/bin/env python3
"""Docker healthcheck for the `can` (rvc2mqtt) container.

Real RV-C traffic streams continuously while the CAN bus is alive; if the
bus (or the read loop inside rvc2mqtt) locks up, these topics go silent
even though the process itself keeps running -- exactly the failure a
plain "is the process still running" check can't see.

Subscribes to a few CAN-derived (not locally-published, e.g. not
watcher's own RV_Watcher/SYS_ERRORS) RVC topics and fails only if the
broker is reachable but nothing arrives within the listen window -- the
specific "process alive, bus dead" signature. Any other problem (broker
down, library missing, etc.) is left for its own healthcheck/dependency
to catch, so this exits 0 ("can't tell, don't restart") rather than risk
restart-looping `can` for an unrelated fault.
"""
import os
import sys
import time

MQTT_USER = os.environ.get("MQTT_USER")
MQTT_PASS = os.environ.get("MQTT_PASS")

TOPICS = [
    "RVC/TANK_STATUS/#",
    "RVC/CHARGER_STATUS/#",
    "RVC/BATTERY_STATUS/#",
    "RVC/DM_RV",
]
LISTEN_SECONDS = 8

try:
    import paho.mqtt.client as mqtt
except Exception as e:
    print(f"paho-mqtt unavailable ({e}) -- skipping check", file=sys.stderr)
    sys.exit(0)

received = []


def _on_message(_client, _userdata, msg):
    received.append(msg)


try:
    client = mqtt.Client()
    if MQTT_USER:
        client.username_pw_set(MQTT_USER, MQTT_PASS)
    client.on_message = _on_message
    client.connect("localhost", 1883, keepalive=LISTEN_SECONDS + 5)
    for topic in TOPICS:
        client.subscribe(topic)
    client.loop_start()
    time.sleep(LISTEN_SECONDS)
    client.loop_stop()
    client.disconnect()
except Exception as e:
    print(f"couldn't reach MQTT broker ({e}) -- skipping check", file=sys.stderr)
    sys.exit(0)

if received:
    sys.exit(0)

print(f"no CAN traffic on {TOPICS} in {LISTEN_SECONDS}s -- reporting unhealthy", file=sys.stderr)
sys.exit(1)
