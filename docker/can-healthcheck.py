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

A refused connection must NOT look like silence. paho's connect() completes the
TCP handshake and returns without raising; an auth rejection arrives later as a
CONNACK with a non-zero code. Without checking that, wrong MQTT credentials
read as "nothing is publishing" -- so the container is marked unhealthy and
autoheal restarts it forever while the real fault (auth) stays hidden. Found by
testing it with bad credentials on 2026-10-26, in both this script and
can-healthcheck.py.
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
# None until a CONNACK arrives; then True on success, False on rejection.
connected = [None]


def _on_message(_client, _userdata, msg):
    received.append(msg)


def _on_connect(_client, _userdata, _flags, rc, *_rest):
    connected[0] = (rc == 0)


try:
    client = mqtt.Client()
    if MQTT_USER:
        client.username_pw_set(MQTT_USER, MQTT_PASS)
    client.on_connect = _on_connect
    client.on_message = _on_message
    client.connect("localhost", 1883, keepalive=LISTEN_SECONDS + 5)
    client.loop_start()

    # Wait for the CONNACK before believing anything about silence.
    handshake = time.time() + 6.0
    while time.time() < handshake and connected[0] is None:
        time.sleep(0.1)
    if connected[0] is not True:
        client.loop_stop()
        client.disconnect()
        reason = "refused" if connected[0] is False else "no CONNACK"
        print(f"broker connection {reason} -- skipping check", file=sys.stderr)
        sys.exit(0)

    for topic in TOPICS:
        client.subscribe(topic)
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
