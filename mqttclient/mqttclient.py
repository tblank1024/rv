#mqtt client to read values of interest from broker

import os
import time
import json
import paho.mqtt.client as mqtt
from pprint import pprint


TOPIC_PREFIX = 'RVC'

# The callback for when the client receives a CONNACK response from the server.
def on_connect(client, userdata, flags, rc):
    global TargetTopics, TOPIC_PREFIX

    print("Connected with result code "+str(rc))
    # Subscribing in on_connect() means that if we lose the connection and
    # reconnect then subscriptions will be renewed.
    #client.subscribe("$SYS/#")
    for name in TargetTopics:
        #print('Subscribing to: ', key)
        client.subscribe(name,0)
    print('Running...')

# The callback for when a PUBLISH message is received from the MQTT server.
def on_message(client, userdata, msg):
    global TargetTopics, TopicData, msg_counter
    #print(msg.topic+ " " + str(msg.payload))
    msg_dict = json.loads(msg.payload.decode('utf-8'))

    for item in TargetTopics[msg.topic]:
        if item == 'instance':
            break
        #print(item,'= ', msg_dict[item])
        TopicData[msg.topic + '/' + item] = msg_dict[item]

    msg_counter += 1
    if msg_counter % 20 == 0:
        #This is a poor way to provide a UI but tkinter isn't working
        os.system('clear')
        print('******************************************************')
        pprint(TopicData)
    #time.sleep(.5)
    

client = mqtt.Client()
client.on_connect = on_connect
client.on_message = on_message

try:
    client.connect("localhost", 1883, 60)
except:
    print("Can't connect to MQTT Broker -- exiting")
    exit()

try:    
    with open("dgn_variables.json","r") as newfile: 
        try:
            data = json.load(newfile)
        except: 
            print('Json file format error --- exiting')
            exit()
except:
    print('dgn_variables.json file not found -- exiting')
    exit()

msg_counter = 0
TargetTopics = {}
TopicData = {}
for item in data:
    if "instance" in data[item]:
        topic = TOPIC_PREFIX + '/' + item + '/' + str(data[item]["instance"])
    else:   
        topic = TOPIC_PREFIX + '/' + item
    for entryvar in data[item]:
        tmp = data[item][entryvar]
        if  isinstance(tmp, str) and tmp.startswith("Variable"):
            if topic not in TargetTopics:
                TargetTopics[topic] = {}
            TargetTopics[topic][entryvar] = tmp
            TopicData[topic + '/' + entryvar] = ""
pprint(TargetTopics)
pprint(TopicData)

# Blocking call that processes network traffic, dispatches callbacks and
# handles reconnecting.
# Other loop*() functions are available that give a threaded interface and a
# manual interface.
client.loop_forever()