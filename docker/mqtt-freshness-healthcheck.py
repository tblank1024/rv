#!/usr/bin/env python3
"""
Generic Docker healthcheck: does this container still publish?

Follows can-healthcheck.py's discipline deliberately. It fails ONLY on the
specific "process alive, data dead" signature -- the broker is reachable but
the topics this service owns have gone quiet. Every other problem (broker
down, paho missing, auth refused) exits 0, meaning "can't tell, don't
restart", because a healthcheck that fails for unrelated reasons becomes a
restart loop once autoheal is watching. That matters more now than it did:
before 2026-10-26 autoheal was wired to one container, and it is now wired to
five.

Configured per service in docker-compose.yml:
    HEALTHCHECK_TOPICS   comma-separated MQTT topics (wildcards allowed)
    HEALTHCHECK_WINDOW   seconds to listen (default 15)

Only use this for a service that publishes on a TIMER. A service that
publishes on change -- the alarm, for instance -- legitimately stays silent,
and this check would restart it in a loop for behaving correctly.

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

TOPICS = [t.strip() for t in os.environ.get("HEALTHCHECK_TOPICS", "").split(",") if t.strip()]
WINDOW = float(os.environ.get("HEALTHCHECK_WINDOW", "15"))
MQTT_USER = os.environ.get("MQTT_USER")
MQTT_PASS = os.environ.get("MQTT_PASS")

if not TOPICS:
    print("HEALTHCHECK_TOPICS unset -- skipping check", file=sys.stderr)
    sys.exit(0)

try:
    import paho.mqtt.client as mqtt
except Exception as exc:
    print(f"paho-mqtt unavailable ({exc}) -- skipping check", file=sys.stderr)
    sys.exit(0)

received = []
# None until a CONNACK arrives; then True on success, False on rejection.
connected = [None]


def _on_connect(_client, _userdata, _flags, rc, *_rest):
    connected[0] = (rc == 0)


try:
    client = mqtt.Client()
    if MQTT_USER:
        client.username_pw_set(MQTT_USER, MQTT_PASS)
    client.on_connect = _on_connect
    client.on_message = lambda *_a: received.append(1)
    client.connect("localhost", 1883, keepalive=int(WINDOW) + 5)
    client.loop_start()

    # Wait for the CONNACK before believing anything about silence.
    handshake = time.time() + min(6.0, WINDOW)
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
    deadline = time.time() + WINDOW
    while time.time() < deadline and not received:
        time.sleep(0.25)          # return as soon as one message arrives
    client.loop_stop()
    client.disconnect()
except Exception as exc:
    print(f"couldn't reach MQTT broker ({exc}) -- skipping check", file=sys.stderr)
    sys.exit(0)

if received:
    sys.exit(0)

print(f"nothing on {', '.join(TOPICS)} in {WINDOW:g}s -- publisher is wedged",
      file=sys.stderr)
sys.exit(1)
