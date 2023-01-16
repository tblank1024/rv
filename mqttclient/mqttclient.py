#mqtt client to read values of interest from broker

import paho.mqtt.client as mqtt
import ruamel.yaml as yaml
from pprint import pprint

with open("subscriptions.yml", "r") as file:
    data = yaml.load(file, Loader=yaml.Loader)
    pprint(data)
    




# The callback for when the client receives a CONNACK response from the server.
def on_connect(client, userdata, flags, rc):
    global data
    print("Connected with result code "+str(rc))
    # Subscribing in on_connect() means that if we lose the connection and
    # reconnect then subscriptions will be renewed.
    #client.subscribe("$SYS/#")
    for val in data['subscriptions']:
        print("Subscribing to: ",val[0]["dsn_name"], val[0]["qos"])
        client.subscribe(val[0]["dsn_name"], int(val[0]["qos"]))
    print('Running...')

# The callback for when a PUBLISH message is received from the server.
def on_message(client, userdata, msg):
    print(msg.topic+" "+str(msg.payload))

client = mqtt.Client()
client.on_connect = on_connect
client.on_message = on_message

#client.connect("mqtt.eclipseprojects.io", 1883, 60)
client.connect("localhost", 1883, 60)

# Blocking call that processes network traffic, dispatches callbacks and
# handles reconnecting.
# Other loop*() functions are available that give a threaded interface and a
# manual interface.
client.loop_forever()