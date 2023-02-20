#mqtt client to read values of interest from broker

import os
import time
import json
import paho.mqtt.client as mqtt
from pprint import pprint


#globals
topic_prefix = 'RVC'
msg_counter = 0
TargetTopics = {}
TopicData = {}
TargetAlias = {}
AliasData = {}

class webclient():

    

    # The callback for when the client receives a CONNACK response from the server.
    def _on_connect(client, userdata, flags, rc):
        global TargetTopics

        print("Connected with result code "+str(rc))
        # Subscribing in on_connect() means that if we lose the connection and
        # reconnect then subscriptions will be renewed.
        #client.subscribe("$SYS/#")
        for name in TargetTopics:
            #print('Subscribing to: ', key)
            client.subscribe(name,0)
        print('Running...')

    # The callback for when a PUBLISH message is received from the MQTT server.
    def _on_message(client, userdata, msg):
        global TargetTopics, TopicData, msg_counter, AliasData, TargetAlias
        #print(msg.topic+ " " + str(msg.payload))
        msg_dict = json.loads(msg.payload.decode('utf-8'))

        for item in TargetTopics[msg.topic]:
            if item == 'instance':
                break
            #print(item,'= ', msg_dict[item])
            tmp = msg.topic + '/' + item
            TopicData[tmp] = msg_dict[item]
            AliasData[TargetAlias[tmp]] = msg_dict[item]


        msg_counter += 1
        if msg_counter % 20 == 0:
            #This is a poor way to provide a UI but tkinter isn't working
            os.system('clear')
            print('*******************************************************')
            pprint(AliasData)
            #pprint(TopicData)
            msg_counter = 0
        #time.sleep(.5)
        
    def run_webMQTT_infinite(self):
        global TopicData, AliasData, TargetAlias, TargetTopics, topic_prefix

        client = mqtt.Client()
        client.on_connect = webclient._on_connect
        client.on_message = webclient._on_message

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

       
        for item in data:
            if "instance" in data[item]:
                topic = topic_prefix + '/' + item + '/' + str(data[item]["instance"])
            else:   
                topic = topic_prefix + '/' + item
            for entryvar in data[item]:
                tmp = data[item][entryvar]
                if  isinstance(tmp, str) and tmp.startswith("_var"):
                    if topic not in TargetTopics:
                        TargetTopics[topic] = {}
                    TargetTopics[topic][entryvar] = tmp
                    local_topic = topic + '/' + entryvar
                    TopicData[local_topic] = ''
                    AliasData[tmp] = ''
                    TargetAlias[local_topic] = tmp
        pprint(TargetTopics)
        pprint(TopicData)
        pprint(TargetAlias)
        pprint(AliasData)

        client.loop_forever()

if __name__ == "__main__":
    RVCWeb = webclient()
    RVCWeb.run_webMQTT_infinite()