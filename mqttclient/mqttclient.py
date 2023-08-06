#mqtt client to read values of interest from broker

import os, argparse,  time, random, json
import re       # regular expressions   
import paho.mqtt.client as mqtt
from pprint import pprint


#globals
topic_prefix = 'RVC'
msg_counter = 0
TargetTopics = {}
MQTTNameToAliasName = {}
AliasData = {}
client = None
mode = 'sub'
debug = 0

class mqttclient():

    def __init__(self, initmode, mqttbroker,mqttport, varIDstr, topic_prefix, debug):
        global client, AllData, AliasData, MQTTNameToAliasName, TargetTopics, mode

        mode = initmode

        for item in AllData:
            #instance number is included in key but not topic prefix
            topic = topic_prefix + '/' + item
            
            for entryvar in AllData[item]:
                tmp = AllData[item][entryvar]
                if  isinstance(tmp, str) and tmp.startswith(varIDstr):
                    if topic not in TargetTopics:
                        TargetTopics[topic] = {}
                    TargetTopics[topic][entryvar] = tmp
                    local_topic = topic + '/' + entryvar
                    AliasData[tmp] = 3.14
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

        # setup the MQTT client
        client = mqtt.Client()
        client.on_connect = self._on_connect
        client.on_message = self._on_message

        try:
            client.connect(mqttbroker,mqttport, 60)
        except:
            print("Can't connect to MQTT Broker/port -- exiting",mqttbroker,":",mqttport)
            exit()

        

       
        

    # The callback for when the client receives a CONNACK response from the server.
    def _on_connect(self, client, userdata, flags, rc):
        global TargetTopics, mode

        if rc == 0:
            print("_on_connect to MQTT Server - OK")
        else:
            print('Failed _on_connect to MQTT server.  Result code = ', rc)
        # Subscribing in on_connect() means that if we lose the connection and
        # reconnect then subscriptions will be renewed.
        #client.subscribe("$SYS/#")
        if mode == 'sub':
            for name in TargetTopics:
                if debug>1:
                    print('Subscribing to: ', name)
                client.subscribe(name,0)
        print('Running...')

    # The callback for when a PUBLISH message is received from the MQTT server.
    def _on_message(self, client, userdata, msg):
        global TargetTopics, msg_counter, AliasData, MQTTNameToAliasName
        if debug>2:
            print(msg.topic+ " " + str(msg.payload))
        msg_dict = json.loads(msg.payload.decode('utf-8'))

        for item in TargetTopics[msg.topic]:
            if item == 'instance':
                break
            if debug>2:
                print('*** ',item,'= ', msg_dict[item])
            tmp = msg.topic + '/' + item
            AliasData[MQTTNameToAliasName[tmp]] = msg_dict[item]

        if debug > 0 and debug < 3:
            #This is a poor way to provide a UI but tkinter isn't working
            msg_counter += 1
            if msg_counter % 20 == 0:
                #os.system('clear')
                print('*******************************************************')
                pprint(AliasData)
                os.sys.stdout.flush()
                msg_counter = 0
    
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

AllData = {
    "CHARGER_AC_STATUS_1/1": {"data": "017009187D001EFF",
                         "dgn": "1FFCA",
                         "fault ground current": "11",
                         "fault open ground": "11",
                         "fault open neutral": "11",
                         "fault reverse polarity": "11",
                         "frequency": 60.0,
                         "input/output": "00",
                         "input/output definition":                     "xx not real ",
                         "instance": 1,
                         "line": "00",
                         "line definition": 1,
                         "name": "CHARGER_AC_STATUS_1",
                         "rms current":                             "_var02Charger_AC_current",
                         "rms voltage":                             "_var03Charger_AC_voltage",
                         "timestamp":                               "_var01Timestamp"},
    "CHARGER_AC_STATUS_3/1": {"complementary leg": 255,
                         "data": "01FCFFFFFFFF00FF",
                         "dgn": "1FFC8",
                         "harmonic distortion": 0.0,
                         "input/output": "00",
                         "input/output definition":                      "xx not real data _var04",
                         "instance": 1,
                         "line": "00",
                         "line definition": 1,
                         "name": "CHARGER_AC_STATUS_3",
                         "phase status": "1111",
                         "phase status definition": "no data",
                         "reactive power":                            "not used -bad value",  
                         "real power":                              "_var17AC_real_power",   
                         "timestamp": "1672774555.024753",
                         "waveform": "00",
                         "waveform definition": "sine wave"},
    "CHARGER_STATUS/1": {"auto recharge enable": "11",
                    "charge current":                               "_var04Charger_current",
                    "charge current percent of maximum": 0.0,
                    "charge voltage":                               "_var05Charger_voltage",
                    "data": "011201007D0006FF",
                    "default state on power-up": "11",
                    "dgn": "1FFC7",
                    "force charge": 15,
                    "instance": 1,
                    "name": "CHARGER_STATUS",
                    "operating state": 6,
                    "operating state definition":                   "_var06Charger_state",
                    "timestamp": "1672774554.984803"},
    "DC_SOURCE_STATUS_2/1": {"data": "0164FFFFC8FFFFFF",
                        "device priority": 100,
                        "device priority definition": "inverter Charger",
                        "dgn": "1FFFC",
                        "instance": 1,
                        "instance definition": "main house battery bank",
                        "name": "DC_SOURCE_STATUS_2",
                        "source temperature": "n/a",
                        "state of charge": 100.0,
                        "time remaining": 65535,
                        "timestamp": "1672774554.714678"},
    "DM_RV": {"bank select": 15,
           "data": "0542FFFFFFFFFFFF",
           "dgn": "1FECA",
           "dsa": 66,
           "dsa extension": 255,
           "fmi": 31,
           "name": "DM_RV",
           "occurrence count": 127,
           "operating status": "0101",
           "red lamp status":                                       "_var07Red",
           "spn-isb": 255,
           "spn-lsb": 7,
           "spn-msb": 255,
           "timestamp": "1672774552.1052072",
           "yellow lamp status":                                    "_var08Yellow"
	  },
    "INVERTER_AC_STATUS_1/1": {"data": "4170090A7D001EFF",
                          "dgn": "1FFD7",
                          "fault ground current": "11",
                          "fault open ground": "11",
                          "fault open neutral": "11",
                          "fault reverse polarity": "11",
                          "frequency": 60.0,
                          "input/output": "01",
                          "input/output definition":                    "xxx rubbish ",
                          "instance": 1,
                          "line": "00",
                          "line definition": 1,
                          "name": "INVERTER_AC_STATUS_1",
                          "rms current":                            "_var09Invert_AC_current",
                          "rms voltage":                            "_var10Invert_AC_voltage",
                          "timestamp": "1672774554.8647683"},
    "INVERTER_AC_STATUS_3/1": {"complementary leg": 255,
                          "data": "41C02E002D00FFFF",
                          "dgn": "1FFD5",
                          "harmonic distortion": 255,
                          "input/output": "01",
                          "input/output definition":                                  "xxx rubbish ",
                          "instance": 1,
                          "line": "00",
                          "line definition": 1,
                          "name": "INVERTER_AC_STATUS_3",
                          "phase status": "0000",
                          "phase status definition": "no complementary leg",
                          "reactive power":                         "_var11AC_reactive_power",
                          "real power":                             "_var12AC_real_power",
                          "timestamp": "1672774554.824777",
                          "waveform": "00",
                          "waveform definition": "sine wave"},
    "INVERTER_AC_STATUS_4/1": {"bypass mode active": "11",
                          "data": "4100FFFFFFFFFFFF",
                          "dgn": "1FF8F",
                          "fault high frequency": "11",
                          "fault how frequency": "11",
                          "fault surge protection": "11",
                          "input/output": "01",
                          "input/output definition":                                  " rubbish ",
                          "instance": 1,
                          "line": "00",
                          "line definition": 1,
                          "name": "INVERTER_AC_STATUS_4",
                          "qualification Status": 15,
                          "timestamp": "1672774554.7847886",
                          "voltage fault": 0,
                          "voltage fault definition": "voltage ok"},
    "INVERTER_DC_STATUS/1": {"data": "011201007DFFFFFF",
                        "dc amperage":                              "_var13Invert_DC_Amp",
                        "dc voltage":                               "_var14Invert_DC_Volt",
                        "dgn": "1FEE8",
                        "instance": 1,
                        "name": "INVERTER_DC_STATUS",
                        "timestamp": "1672774554.7448194"},
    "INVERTER_STATUS/1": {"battery temperature sensor present": "00",
                     "battery temperature sensor present definition": "no sensor in use",
                     "data": "0102F0FFFFFFFFFF",
                     "dgn": "1FFD4",
                     "instance": 1,
                     "load sense enabled": "00",
                     "load sense enabled definition": "load sense disabled",
                     "name": "INVERTER_STATUS",
                     "status":                                      "_var16Invert_status_num",
                     "status definition":                           "_var15Invert_status_name",
                     "timestamp": "1672774554.9447553"},
    "INVERTER_TEMPERATURE_STATUS/1": {"data": "01E026FFFFFFFFFF",
                                 "dgn": "1FEBD",
                                 "fet temperature": 38.0,
                                 "fet temperature F": 100.4,
                                 "instance": 1,
                                 "name": "INVERTER_TEMPERATURE_STATUS",
                                 "timestamp": "1672774554.9047515",
                                 "transformer temperature": "n/a"},
    "UNKNOWN-0EEFF": {"data": "ED5FE40E08813C80",
                   "dgn": "0EEFF",
                   "name": "UNKNOWN-0EEFF",
                   "timestamp": "1672774554.1447444"},
    "BATTERY_STATUS/1":{                         
                    "instance":1,
                    "name":"BATTERY_STATUS",
                    "DC_voltage":                                   "_var18Batt_voltage",
                    "DC_current":                                   "_var19Batt_current",
                    "State_of_charge":                              "_var20Batt_charge",
                    "Status":                                                    ""},
    "ATS_AC_STATUS_1/1": {"data": "4170090A7D001EFF",
                    "dgn": "1FFAD",
                    "instance": 1,
                    "line":                                         "_var21ATS_Line",
                    "line definition": 1,
                    "name": "ATS_AC_STATUS_1",
                    "rms current":                                  "_var22ATS_AC_current",
                    "rms voltage":                                  "_var23ATS_AC_voltage",
                    "timestamp": "1672774554.8647683"},
                     
    "SOLAR_CONTROLLER_STATUS/1":{ 
                    "dgn":"1FEB3",                        
                    "instance":1,
                    "name":"SOLAR_CONTROLLER_STATUS",
                    "DC_voltage":                                   "_var26Solar_voltage",
                    "DC_current":                                   "_var27Solar_current"},
    "TANK_STATUS/0": {"absolute level": 65535,
                    "data": "001020FFFFFFFFFF",
                    "dgn": "1FFB7",
                    "instance": 0,
                    "instance definition":                          "_var28Tank_Name",
                    "name": "TANK_STATUS",
                    "relative level":                               "_var29Tank_Level",
                    "resolution":                                   "_var30Tank_Resolution",
                    "tank size": 65535,
                    "timestamp": "1688685071.9489293"},
    "TANK_STATUS/1": {"absolute level": 65535,
                    "data": "010A38FFFFFFFFFF",
                    "dgn": "1FFB7",
                    "instance": 1,
                    "instance definition":                          "_var31Tank_Name",
                    "name": "TANK_STATUS",
                    "relative level":                               "_var32Tank_Level",
                    "resolution":                                   "_var33Tank_Resolution",
                    "tank size": 65535,
                    "timestamp": "1688685072.9491377"},
    "TANK_STATUS/2": {"absolute level": 65535,
                    "data": "020B38FFFFFFFFFF",
                    "dgn": "1FFB7",
                    "instance": 2,
                    "instance definition":                          "_var34Tank_Name",
                    "name": "TANK_STATUS",
                    "relative level":                               "_var35Tank_Level",
                    "resolution":                                   "_var36Tank_Resolution",
                    "tank size": 65535,
                    "timestamp": "1688685071.9494853"},
    "TANK_STATUS/3": {"absolute level": 65535,
                    "data": "034D64FFFFFFFFFF",
                    "dgn": "1FFB7",
                    "instance": 3,
                    "instance definition":                          "_var37Tank_Name",
                    "name": "TANK_STATUS",
                    "relative level":                               "_var38Tank_Level",
                    "resolution":                                   "_var39Tank_Resolution",
                    "tank size": 65535,
                    "timestamp": "1688685071.6974237"},
    "RV_Loads/1": {
                    "instance": 1,
                    "name": "RV_Loads",
                    "AC Load":                                      "_var24RV_Loads_AC",
                    "DC Load":                                      "_var25RV_Loads_DC",
                    "timestamp": "1672774554.8647683"}
}



if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-b", "--broker", default = "localhost", help="MQTT Broker Host")
    parser.add_argument("-p", "--port", default = 1883, type=int, help="MQTT Broker Port")
    parser.add_argument("-d", "--debug", default = 1, type=int, choices=[0, 1, 2, 3], help="debug level")
    parser.add_argument("-m", "--mode", default = "pub", help="sub or pub")
    parser.add_argument("-t", "--topic", default = "RVC", help="MQTT topic prefix")
    args = parser.parse_args()

    broker = args.broker
    port = args.port
    debug = args.debug
    #debug levels
    # 0 - no debug reports
    # 1 - light reportingof both send/rec
    # 2 - more reporting of both send/rec
    # 3 - heavy reporting of both send/rec and all raw data



    if args.mode == 'sub':
        mode = 'sub'
    else:
        mode = 'pub'
    mqttTopic = args.topic
    RVC_Client = mqttclient(mode,broker, port, '_var', mqttTopic, debug)
    if mode == 'sub':
        RVC_Client.run_mqtt_infinite()
    else:
        while True:
            time.sleep(6)
            #update AllData dictionary with new variable data
            """  target topic from json file 
            "BATTERY_STATUS/1":{                         
                    "instance":1,
                    "name":"BATTERY_STATUS",
                    "DC_voltage":                                               "_var18Batt_voltage",
                    "DC_current":                                               "_var19Batt_current",
                    "State_of_charge":                                          "_var20Batt_charge",
                    "Status":                                                    ""},
            """ 
            #Update the dictionary with new data and publish
            AllData['BATTERY_STATUS/1']["DC_voltage"] = 12.0 + random.random()
            AllData['BATTERY_STATUS/1']["DC_current"] =  20 * random.random() - 10
            AllData['BATTERY_STATUS/1']["State_of_charge"] = 100 - random.random()*100
            AllData['BATTERY_STATUS/1']["Status"] = "OK"
            RVC_Client.pub(AllData['BATTERY_STATUS/1'])
