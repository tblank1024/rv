#mqtt watcher tracks a set of variables and publishes a message when they change to stdout
#optionally outputs vars to csv file
#based on mqttclient.py

import os, argparse,  time, random, json
import re       # regular expressions   
import paho.mqtt.client as mqtt
from pprint import pprint
import tkinter as tk


#globals
topic_prefix = 'RVC'
msg_counter = 0
TargetTopics = {}
MQTTNameToAliasName = {}
AllData = {}
AliasData = {}
client = None
mode = 'c'
debug = 0
LastStatus = ''
IOFile = ''
TopicFile = ''
IOFileptr = None

class mqttclient():

    def __init__(self, initmode, mqttbroker,mqttport, mqtttopicfile, varIDstr, topic_prefix, debug, opmode, IOFilename):
        global client, AllData, AliasData, MQTTNameToAliasName, TargetTopics, mode, IOFile, TopicFile, IOFileptr

        mode = opmode
        IOFile = IOFilename
        TopicFile = mqtttopicfile

        # read in the json file that defines the topics and variables of interest
        try:    
            with open(TopicFile,"r") as newfile: 
                try:
                    AllData = json.load(newfile)
                except: 
                    print('Json file format error --- exiting')
                    exit()
        except:
            print(str(mqtttopicfile) + ' file not found -- exiting')
            exit()

        for item in AllData:
            if "instance" in AllData[item]:
                topic = topic_prefix + '/' + item + '/' + str(AllData[item]["instance"])
            else:   
                topic = topic_prefix + '/' + item
            for entryvar in AllData[item]:
                tmp = AllData[item][entryvar]
                if  isinstance(tmp, str) and tmp.startswith(varIDstr):
                    if topic not in TargetTopics:
                        TargetTopics[topic] = {}
                    TargetTopics[topic][entryvar] = tmp
                    local_topic = topic + '/' + entryvar
                    AliasData[tmp] = ''
                    MQTTNameToAliasName[local_topic] = tmp
        if debug > 0:
            #print('>>All Data:')
            #pprint(AllData)
            print('>>TargetTopics:')
            pprint(TargetTopics)
            print('>>MQTTnameToAliasName:')
            pprint(MQTTNameToAliasName)
            print('>>AliasData:')
            pprint(AliasData)
            print('>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>')

        if mode == 'c' or mode == 's':
            # setup the MQTT client
            client = mqtt.Client()
            client.on_connect = self._on_connect
            client.on_message = self._on_message

            try:
                client.connect(mqttbroker,mqttport, 60)
            except:
                print("Can't connect to MQTT Broker/port -- exiting",mqttbroker,":",mqttport)
                exit()
            if mode == 'c':
                #open the .log file for writing
                try:
                    IOFileptr = open(IOFile + '.log', "w")
                except:
                    print("Can't open .log file for writing  -- exiting",IOFile + '.log')
                    exit()
                
        else:   #mode is output; reads from log file and outputs selected vars to csv file
            #open the .log file for reading
            try:
                IOFileptr = open(IOFile + '.log', "r")
            except:
                print("Can't open .log file for reading  -- exiting",IOFile + '.log')
                exit()


    #function arguments:
    # - json file with target variables identified
    # - file name assuming the.log extension for the input run data
    # input log file format: one dictionary entry per line for each message received from mqtt
    # - file name assuming the.csv extension for the output data
    def GenOutput(self):
        global TargetTopics, msg_counter, AliasData, MQTTNameToAliasName
        #open the input file
        try:
            fp_out = open(IOFile + '.csv', "w")
        except:
            print("Can't open file for writing -- exiting", IOFile + '.log')
            exit()
        #input one line from the input file
        while True:
            msg = IOFileptr.readline()
            if msg == '':
                break

            msg_dict = json.loads(msg)

            for item in TargetTopics[msg_dict['topic']]:
                if item == 'instance':
                    break
                if debug>2:
                    print('*** ',item,'= ', msg_dict[item])
                tmp = msg_dict['topic'] + '/' + item
                AliasData[MQTTNameToAliasName[tmp]] = msg_dict[item]

            # print out the data every 15th message
            # doing tkinter UI would be better TODO
            
            if msg_counter == 0:
                for item in AliasData:
                    print(item, end='\t,')
                print('')
            elif msg_counter % 15 == 14:
                for item in AliasData:
                    print(AliasData[item], end='\t,')
                print(' ')
                os.sys.stdout.flush()
                msg_counter = 1
            msg_counter += 1
        fp_out.write('testing\n')
        fp_out.close()
        IOFileptr.close()
        
        # Function to print out all input dictionary values in a single line with a comma separator in a table format
    def _print_dict(self, dict):
        for item in dict:
            print(dict[item], end='\t,')
        

    # Function to print out all input dictionary names in a single line with a comma separator in a table format
    def _print_dict_names(self, dict):
        for item in dict:
            print(item, end='\t,')
        print('')



    # The callback for when the client receives a CONNACK response from the server.
    def _on_connect(self, client, userdata, flags, rc):
        global TargetTopics

        if rc != 0: 
            print('Failed _on_connect to MQTT server.  Result code = ', rc)
            exit()
        # Subscribing in on_connect() means that if we lose the connection and
        # reconnect then subscriptions will be renewed.
        # client.subscribe("$SYS/#")
        for name in TargetTopics:
            if debug>0:
                print('Subscribing to: ', name)
            client.subscribe(name,0)
        if debug > 0:
            print('Conected to MQTT and Running')
    

    # The callback for when a watched message is received from the MQTT server.
    def _on_message(self, client, userdata, msg):
        global TargetTopics, msg_counter, AliasData, MQTTNameToAliasName, LastStatus

        
        if debug>2:
            print(msg.topic + " " + str(msg.payload))
        msg_dict = json.loads(msg.payload.decode('utf-8'))
        msg_dict['topic'] = msg.topic
        if mode == 'c':
            #writes this dictionary to the output file on one line 
            json.dump(msg_dict, IOFileptr)
            IOFileptr.write("\n")
            IOFileptr.flush()

        # # if mst_dict status has changes print out the message
        # if msg_dict['status'] == LastStatus:
        #     return
        # else:
        #     LastStatus = msg_dict['status']
        #     print(msg.topic+ " " + str(msg.payload))


        for item in TargetTopics[msg_dict['topic']]:
            if item == 'instance':
                break
            if debug>2:
                print('*** ',item,'= ', msg_dict[item])
            tmp = msg.topic + '/' + item
            AliasData[MQTTNameToAliasName[tmp]] = msg_dict[item]

        # print out the data every 15th message
        # doing tkinter UI would be better TODO
        
        if msg_counter == 0:
            for item in AliasData:
                print(item, end='\t,')
            print('')
        elif msg_counter % 15 == 14:
            for item in AliasData:
                print(AliasData[item], end='\t,')
            print(' ')
            os.sys.stdout.flush()
            msg_counter = 1
        msg_counter += 1


    def run_mqtt_infinite(self):
        global client
        client.loop_forever()    

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-b", "--broker", default = "localhost", help="MQTT Broker Host")
    parser.add_argument("-p", "--port", default = 1883, type=int, help="MQTT Broker Port")
    parser.add_argument("-d", "--debug", default = 0, type=int, choices=[0, 1, 2, 3], help="debug level")
    parser.add_argument("-s", "--jsonvarfile", default = "./watched_variables.json", help="RVC json file with variables to watch")
    parser.add_argument("-t", "--topic", default = "RVC", help="MQTT topic prefix")
    parser.add_argument("-m", "--Mode", default = "o", help="s - screen only, c - capture msgs into file and screen output, o - output")
    parser.add_argument("-i", "--IOfile", default = "data", help="IO file name with no extension")
    
    args = parser.parse_args()

    broker = args.broker
    port = args.port
    debug = args.debug   
    jasonvarfile = args.jsonvarfile
    mqttTopic = args.topic
    opmode = args.Mode



    # # Create a new Tkinter window
    # window = tk.Tk()

    # # Set the window title
    # window.title("Simple Tkinter UI")

    # # Create a label widget
    # label = tk.Label(window, text="Hello, World!")
    # label.pack()

    # # Run the Tkinter event loop
    # window.mainloop()


    RVC_Client = mqttclient('sub',broker, port, jasonvarfile,'_var', mqttTopic, debug, opmode, args.IOfile)
    if opmode == 's' or opmode == 'c':
        RVC_Client.run_mqtt_infinite()
    else:   #output mode
        print('output mode')
        RVC_Client.GenOutput()

    