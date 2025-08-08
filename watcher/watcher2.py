#mqtt watcher tracks a set of variables and publishes a message when they change to stdout
#optionally outputs vars to csv file
#based on mqttclient.py

import os, argparse,  time, random, json
import re       # regular expressions   
import paho.mqtt.client as mqtt
from pprint import pprint
import tkinter as tk
import threading
import datetime

#CONSTANTS
FILEDIR = './watcherlogs/'

#global vars
topic_prefix = 'RVC'
TargetTopics = {}
MQTTNameToAliasName = {}
AliasData = {}
client = None
mode = 'c'
debug = 0
LastStatus = ''
IOFile = ''
IOFileptr = None
thread_data = {}
Sample_Period_Sec = 60
LastTime = 0


# Create a class for the window thread
class WindowDisplayThread(threading.Thread):
    def __init__(self):
        threading.Thread.__init__(self)


    def run(self):

        self.window = tk.Tk()
        self.window.title("MQTT/RVC Watcher")
        self.create_labels()
        self.update_data()        
        self.window.mainloop()

    

    def create_labels(self):
        global AliasData

        thread_data = AliasData

        label_widgets = {}
        x_pad = 30
        y_pad = 10

        for row, (label, _) in enumerate(thread_data.items()):
            label_widget = tk.Label(self.window, text=label.ljust(x_pad, '_'), font=("Arial", 18))
            label_widget.grid(row=row, column=0, padx=x_pad, pady=y_pad, sticky='w')
            label_widgets[label] = label_widget

        return label_widgets

    def update_data(self):
        global AliasData

        thread_data = AliasData

        value_widgets = {}

        x_pad = 30
        y_pad = 10

        for row, (label, value) in enumerate(thread_data.items()):
            if label not in value_widgets:
                value_widget = tk.Label(self.window, text=str(value).rjust(x_pad, '_'), font=("Arial", 18))
                value_widget.grid(row=row, column=1, padx=x_pad, pady=y_pad, sticky='e')
                value_widgets[label] = value_widget

            if label in value_widgets:
                value_widgets[label].config(text=str(value).rjust(x_pad, '_'))

        self.window.after(1000, self.update_data)

    # Create labels initially
    


class mqttclient():

    def __init__(self, initmode, mqttbroker,mqttport, varIDstr, topic_prefix, debug, opmode, IOFilename):
        
        global client, Watched_Vars, AliasData, MQTTNameToAliasName, TargetTopics, mode, IOFile, IOFileptr

        mode = opmode
        IOFile = IOFilename

        #Build data structures for the watched variables
        #   TargetTopics is a dictionary of dictionaries.  The first key is the MQTT topic and the second key is the variable name
        #   MQTTNameToAliasName is a dictionary of MQTT topic/variable names to the alias name
        #   AliasData is a dictionary of alias variable names to the current value
        for item in Watched_Vars:
            topic = topic_prefix + '/' + item 

            for entryvar in Watched_Vars[item]:
                tmp = Watched_Vars[item][entryvar]
                if  isinstance(tmp, str) and tmp.startswith(varIDstr):
                    #We want this topic
                    if topic not in TargetTopics:
                        TargetTopics[topic] = {}
                    TargetTopics[topic][entryvar] = tmp
                    local_topic = topic + '/' + entryvar
                    AliasData[tmp] = {
                        "timestamp": 0,
                        "flag": False,          #has this var been printed as an error already
                    }
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

        # For watching modes, we need to connect to the MQTT broker and possibly open .log file
        if mode == 'c' or mode == 's' or mode == 'b':
            # setup the MQTT client
            client = mqtt.Client()
            client.on_connect = self._on_connect
            client.on_message = self._on_message
            client.on_disconnect = self._on_disconnect

            # Connect to the MQTT broker
            while True:
                try:
                    client.connect(mqttbroker,mqttport, 60)
                    break
                except:
                    print("Can't connect to MQTT Broker/port -- will retry",mqttbroker,":",mqttport)
                    #sleep and try again
                    time.sleep(5)
            if mode == 'c':
                #open the .log file for writing
                try:
                    print('opening file: ', IOFile + '.log')
                    IOFileptr = open(IOFile + '.log', "a")
                except FileNotFoundError as e:
                    print(f"An FileNotFount error occurred: {e}")
                    exit()
                except PermissionError as e:
                    print(f"Permission error: {e}")
                    exit()
                except Exception as e:
                    print(f"An unexpected error occurred: {e}")
                    exit()
                # except:
                #     print("Can't open ",IOFile + '.log', ' for append -- exiting')
                #     exit()
                
        else:   #mode is output; reads from log file and outputs selected vars to csv file
            #open the .log file for reading
            try:
                IOFileptr = open(IOFile + '.log', "r")
            except:
                print("Can't open .log file for reading  -- exiting", IOFile + '.log')
                exit()

    def _UpdateAliasData(self, msg_dict, now):
        global AliasData, MQTTNameToAliasName, IOFileptr

        #test if this message is in the target list
        if msg_dict['topic'] not in TargetTopics:
            return True
        for item in TargetTopics[msg_dict['topic']]:
            if item == 'instance' or item not in msg_dict:
                break
            if debug>2:
                print('*** ',item,'= ', msg_dict[item])
            tmp = msg_dict['topic'] + '/' + item
            if tmp in MQTTNameToAliasName:
                AliasData[MQTTNameToAliasName[tmp]] = {
                    "timestamp": now,
                    "value": msg_dict[item],
                    "flag": False
                }
        return False


    #function arguments:
    # - json file with target variables identified
    # - file name assuming the.log extension for the input run data
    # input log file format: one dictionary entry per line for each message received from mqtt
    # - file name assuming the.csv extension for the output data
    def GenOutput(self):
        global Sample_Period_Sec
        msg_counter = 0
        LastTimestamp = 0

        #open the input file
        try:
            fp_out = open(IOFile + '.csv', "w")
        except:
            print("Can't open file for writing -- exiting", IOFile + '.csv')
            exit()
        #input one line from the input file
        while True:
            try:
                msg = IOFileptr.readline()
                msg_dict = json.loads(msg)
            except:
                if msg == '':
                    print('Finished reading input file')
                    break
                print('Error reading json data from input file')
                print('Problem msg = "', msg, '"  Line # = ', msg_counter+1)
                break

            if self._UpdateAliasData(msg_dict):
                #This record is no longer in the target list
                continue
            #Only output data if msg_dict['timestamp'] is different from the last output
            
            if "timestamp" in msg_dict:
                tmp = int(float(msg_dict['timestamp']))
                if tmp - LastTimestamp < Sample_Period_Sec * .2:
                    continue
                LastTimestamp = tmp
            if msg_counter == 0:
                for item in AliasData:
                    fp_out.write(item + ',')
                fp_out.write('\n') 
            for item in AliasData:
                fp_out.write(str(AliasData[item].value) + ',')
            fp_out.write('\n')
            msg_counter += 1
        fp_out.close()
        IOFileptr.close()
        
       
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
    
    def _on_disconnect(self, client, userdata, rc):
        print('Disconnected from MQTT server.  Result code = ', rc)
        count = 0
        while True:
            try:
                client.reconnect()
                break
            except:
                print("Reconnect failed! Trying again in 10 seconds. Trys = ", count, end = '\r')
                if count == 0:
                    #Create msg_dict to indicate error and timestamp
                    msg_dict = {}
                    msg_dict['name'] = 'SYS_ERRORS'
                    msg_dict['error'] = 'MQTT Disconnected'
                    msg_dict['timestamp'] = int(time.time())
                    #write this error msg once to the output file on one line
                    json.dump(msg_dict, IOFileptr)
                    IOFileptr.write("\n")
                    IOFileptr.flush()
                #sleep and try again
                time.sleep(10)
                count += 1

    # The callback for when a watched message is received from the MQTT server.
    def _on_message(self, client, userdata, msg):
        global TargetTopics, AliasData, MQTTNameToAliasName, LastStatus, TargetTopics, IOFileptr, debug, mode, Sample_Period_Sec, LastTime

        if debug>2:
            print(msg.topic + " " + str(msg.payload))
        msg_dict = json.loads(msg.payload.decode('utf-8'))
        msg_dict['topic'] = msg.topic   #add MQTT topic to the dictionary
        
        #Checks if the message is in the TargetTopics and if SAMPLEREATE seconds have passed since the last message of this topic and in mode 'c'
        try:
            t_time = int(TargetTopics[msg.topic]['timestamp'])
        except:
            t_time = 0
        #don't dump the SYS_ERROR mesages with error count to the log file
        if (mode == 'c') \
          and (msg.topic in TargetTopics) \
          and (time.time() - t_time) > Sample_Period_Sec \
          and not (msg_dict['name'] == 'SYS_ERRORS' and msg_dict['error'][0] == '#'):
            TargetTopics[msg.topic]['timestamp'] = time.time()
            #writes this dictionary to the output file on one line 
            json.dump(msg_dict, IOFileptr)
            IOFileptr.write("\n")
            IOFileptr.flush()
            if debug > 0:
                dt = datetime.datetime.fromtimestamp(time.time())
                print('wrote to file: ', dt, msg.topic, msg_dict)
                
        #Update the AliasData dictionary
        now = int(time.time())
        self._UpdateAliasData(msg_dict, now)

        #Check if timestamp is progressing for all AliasData entries except for SYS_ERRORS
        LARGESTINTERVAL = 90            #max update interval in seconds of any variable
        error_cnt = 0
        msg_dict = {}
        msg_dict['name'] = 'SYS_ERRORS'
        msg_dict['timestamp'] = int(time.time())
        for item in AliasData:
            if int(AliasData[item]['timestamp']) != 0  \
                    and int((AliasData[item]['timestamp'])) + LARGESTINTERVAL < now  \
                    and not AliasData[item]['flag'] \
                    and item != 'SYS_ERRORS':
                AliasData[item]['flag'] = True
                print('Timestamp not progressing for  ', item, '  now = ', now)
                pprint(AliasData[item])
                #build msg_dict to include error field
                msg_dict['error'] = 'Progression error: ' + item + '  now = ' + str(now)
                self.pub(msg_dict, qos=0, retain=False)
                #write this error msg to the output file on one line
                json.dump(msg_dict, IOFileptr)
                IOFileptr.write("\n")
                IOFileptr.flush()
                if debug > 0:
                    dt = datetime.datetime.fromtimestamp(time.time())
                    print('wrote error to file: ', dt, msg.topic, msg_dict)
            if AliasData[item]['flag']:
                error_cnt += 1
        #Publish error count to MQTT every 5 second 
        if now - LastTime > 5:      
            msg_dict['error'] = '# Errors = ' + str(error_cnt)
            if debug > 0:
                print('pub time ', end='')
                pprint(msg_dict)
            self.pub(msg_dict, qos=0, retain=False)
            LastTime = now      
     

    @staticmethod
    def pub(payload, qos=0, retain=False):
        global client, debug, topic_prefix
                
        if "instance" in payload:
            topic = topic_prefix + '/' + payload["name"] + '/' + str(payload["instance"])
        else:   
            topic = topic_prefix + '/' + payload["name"]             
        
        if debug > 0:
            print('Publishing: ', topic, payload)
        #quick check that topic is in TargetTopics
        if topic not in TargetTopics:
            print('Error: Publishing topic not in  specified json file: ', topic)
        client.publish(topic, json.dumps(payload), qos, retain)

    def run_mqtt_infinite(self):
        global client
        client.loop_forever()    

Watched_list = {
    "x_var01Timestamp",
    "x_var02Charger_AC_current",
    "_var24RV_Loads_AC",
    "_var24RV_Loads_DC",
    "_var09Invert_AC_current",
    "_var10Invert_AC_voltage",
    "_var27Solar_power",
    "_var18Batt_voltagew",
    "_var19Batt_current",
    "_var20Batt_charge",
    
}
"""
Watched_Vars = {
  
    "TANK_STATUS/0": {"absolute level": 65535,
                    "data": "001020FFFFFFFFFF",
                    "dgn": "1FFB7",
                    "instance": 0,
                    "instance definition":                          "x_var28Tank_Name",
                    "name": "TANK_STATUS",
                    "relative level":                               "_var29Tank_Level",
                    "resolution":                                   "x_var30Tank_Resolution",
                    "tank size": 65535,
                    "timestamp":                                    "x_var07Timestamp"},  
    "TANK_STATUS/1": {"absolute level": 65535,
                    "data": "010A38FFFFFFFFFF",
                    "dgn": "1FFB7",
                    "instance": 1,
                    "instance definition":                          "x_var31Tank_Name",
                    "name": "TANK_STATUS",
                    "relative level":                               "x_var32Tank_Level",
                    "resolution":                                   "x_var33Tank_Resolution",
                    "tank size": 65535,
                    "timestamp":                                    "x_var08Timestamp"},
    "TANK_STATUS/2": {"absolute level": 65535,
                    "data": "020B38FFFFFFFFFF",
                    "dgn": "1FFB7",
                    "instance": 2,
                    "instance definition":                          "x_var34Tank_Name",
                    "name": "TANK_STATUS",
                    "relative level":                               "x_var35Tank_Level",
                    "resolution":                                   "x_var36Tank_Resolution",
                    "tank size": 65535,
                    "timestamp":                                    "x_var09Timestamp"},
    "TANK_STATUS/3": {"absolute level": 65535,
                    "data": "034D64FFFFFFFFFF",
                    "dgn": "1FFB7",
                    "instance": 3,
                    "instance definition":                          "x_var37Tank_Name",
                    "name": "TANK_STATUS",
                    "relative level":                               "x_var38Tank_Level",
                    "resolution":                                   "x_var39Tank_Resolution",
                    "tank size": 65535,
                    "timestamp":                                    "x_var10Timestamp"},
    "RV_Loads/1": {
                    "instance": 1,
                    "name": "RV_Loads",
                    "AC Load":                                      "_var24RV_Loads_AC",
                    "DC Load":                                      "_var25RV_Loads_DC",
                    "timestamp":                                    "x_var11Timestamp"},
    "RV_Watcher/1": {
                    "instance": 1,
                    "name": "RV_Watcher",
                    "Status":                                       "_var50RV_Watcher_Status",
                    "timestamp":                                    "_var51Timestamp"},
    "SYS_ERRORS": {
                    "name": "SYS_ERRORS",
                    "error":                                        "_var52RVC_ERROR",
                    "timestamp":                                    "x_var53Timestamp"},
}
"""

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-b", "--broker", default = "localhost", help="MQTT Broker Host")
    parser.add_argument("-p", "--port", default = 1883, type=int, help="MQTT Broker Port")
    parser.add_argument("-d", "--debug", default = 0, type=int, choices=[0, 1, 2, 3], help="debug level")
    parser.add_argument("-t", "--topic", default = "RVC", help="MQTT topic prefix")
    parser.add_argument("-m", "--Mode", default = "c", help="s - screen only, b - capture MQTT msgs into file and screen output, c - file capture only , o - From xx.log file, output watched vars to xx.csv file")
    parser.add_argument("-i", "--IOfile", default = "watcher", help="IO file name with no extension")
    parser.add_argument("-s", "--sample_sec", default = 60, help="Capture Sample interval in seconds")
    
    args = parser.parse_args()
    broker = args.broker
    port = args.port
    debug = args.debug   
    mqttTopic = args.topic
    opmode = args.Mode
    Sample_Period_Sec = (args.sample_sec)

    print('Watcher starting in mode: ', opmode)
    print('debug level = ', debug)

              
    RVC_Client = mqttclient('sub',broker, port, '_var', mqttTopic, debug, opmode, FILEDIR+args.IOfile)


    if opmode == 's' or opmode == 'b':  #screen mode or capture mode
        # Create an instance of the window thread
        window_thread = WindowDisplayThread()
        # Start the window thread
        window_thread.start()
        # Start the MQTT client thread
        RVC_Client.run_mqtt_infinite()
    elif opmode == 'c': #file caputure only  mode
        RVC_Client.run_mqtt_infinite()
    else:   #output mode
        print('output mode')
        RVC_Client.GenOutput()
        print('Finished!')

    
