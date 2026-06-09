#mqtt/RV-C watcher
#
#Subscribes to a curated subset of RV-C topics published on the MQTT broker
#(by the rvc2mqtt CAN-to-MQTT bridge) as defined in WATCH_SPEC, and tracks the
#current value of each under a short alias name.
#
#Each time a new monthly .log file is opened, it also writes a paired
#<basename>.whitelist.json listing the {topic: [field_names]} derived from
#WATCH_SPEC -- this lets the webserver debug UI show only the fields the
#watcher actually tracks from each raw MQTT payload (see _build_watch_whitelist).
#
#Depending on the run mode (-m / --Mode) it can:
#   c - capture watched messages to a rotating monthly .log file (default)
#   s - show the watched values live in a Tkinter window (no file capture)
#   b - both: live window display AND .log file capture
#   o - replay a previously captured .log file and write the watched values
#       out to a .csv file for offline analysis (see GenOutput)
#
#While running (modes c/s/b) it also watches for two kinds of anomalies and
#reports them as SYS_ERRORS messages (printed, published back to MQTT, and
#logged):
#   - "progression" errors: a watched value hasn't updated in over
#     LARGESTINTERVAL seconds (possible sensor/comms dropout)
#   - "bounds" errors: a watched value has moved outside the optional
#     (min, max) range declared for it in WATCH_SPEC (possible sensor fault
#     or out-of-spec condition)
#
#based on mqttclient.py

import os, argparse,  time, random, json
import re       # regular expressions   
import paho.mqtt.client as mqtt
from pprint import pprint
import tkinter as tk
import threading
import datetime
import psutil


#CONSTANTS
FILEDIR = './watcherlogs/'
LARGESTINTERVAL = 60    # default max seconds between updates before a progression fault is raised

# Per-alias overrides for max allowed update interval.
# Tire sensors (TireLinc TPMS) broadcast every 100-270 s; exclude them from the 60 s check.
MAX_INTERVAL_OVERRIDES = {
    'Tire_FL_psi':    300,
    'Tire_FR_psi':    300,
    'Tire_RL_out_psi':300,
    'Tire_RL_in_psi': 300,
    'Tire_RR_in_psi': 300,
    'Tire_RR_out_psi':300,
}

#global vars
topic_prefix = 'RVC'
TargetTopics = {}
MQTTNameToAliasName = {}
WATCH_SPEC = {}
AliasData = {}
client = None
mode = 'c'
debug = 0
LastStatus = ''
#IOFile = ''
IOFileptr = None
thread_data = {}
Sample_Period_Sec = 60
LastTime = 0
_flush_timer = None


def _start_periodic_flush(interval=60):
    """Flush the log file on a repeating timer so buffered writes reach disk
    without the per-message flush() calls that cause unnecessary flash wear."""
    global _flush_timer

    def _tick():
        global IOFileptr, _flush_timer
        if IOFileptr and not IOFileptr.closed:
            try:
                IOFileptr.flush()
            except Exception:
                pass
        _flush_timer = threading.Timer(interval, _tick)
        _flush_timer.daemon = True
        _flush_timer.start()

    _flush_timer = threading.Timer(interval, _tick)
    _flush_timer.daemon = True
    _flush_timer.start()


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
 
    # Function to return file pointer for operation
    # Input  parameters: opmode - operation mode
    # Output parameters: file pointer
    # uses file naming convention of the form: currentMonth.log
    # If the file does not exist, it is created
    # If the file exists, it is opened in append mode unless 
    #   the creation date is greater than 6 months old in which case the file is opened in write mode
    def __get_output_file_pointer(self):
        global IOFilename, IOFileptr

        current_month = datetime.datetime.now().strftime("%B")
        file_name = f"{FILEDIR}{current_month}.log"
        previous_name = IOFileptr.name if IOFileptr is not None else None
        if IOFileptr is not None and IOFileptr.name != file_name:
            IOFileptr.close()
        if IOFilename != FILEDIR:
            #keep user supplied name
            file_name = f"{IOFilename}.log"
        # Check if the file exists
        if os.path.exists(file_name):
            # Get the creation date of the file
            creation_date = datetime.datetime.fromtimestamp(os.path.getctime(file_name))
            
            # Calculate the difference in months between the current date and the creation date
            months_diff = (datetime.datetime.now().year - creation_date.year) * 12 + (datetime.datetime.now().month - creation_date.month)
            
            # Check if the file is older than 6 months
            if months_diff > 6:
                # Open the file in write mode
                IOFileptr = open(file_name, "w")
            else:
                # Open the file in append mode
                IOFileptr = open(file_name, "a")
        else:
            # Create the file if it doesn't exist
            IOFileptr = open(file_name, "w")

        # (Re)write the WATCH_SPEC-derived whitelist alongside a newly opened log
        # file -- covers monthly rotation, user-supplied filenames, and restarts.
        if IOFileptr.name != previous_name:
            _write_whitelist_file(IOFileptr.name)

        return IOFileptr

    def __init__(self, initmode, mqttbroker,mqttport, topic_prefix, debug, opmode):
        global client, AliasData, MQTTNameToAliasName, TargetTopics, mode, IOFilename, IOFileptr

        mode = opmode

        #Build data structures for the watched variables from WATCH_SPEC
        #   TargetTopics is a dictionary of dictionaries.  The first key is the MQTT topic and the second key is the variable name
        #   MQTTNameToAliasName is a dictionary of MQTT topic/variable names to the alias name
        #   AliasData is a dictionary of alias variable names to the current value
        #   The order of entries in WATCH_SPEC determines AliasData/CSV column order, and each
        #   alias name must be unique across the whole spec since AliasData is keyed by alias name.
        #   Each entry is (topic_suffix, field_name, alias) or, to enable out-of-range detection,
        #   (topic_suffix, field_name, alias, min, max).
        for entry in WATCH_SPEC:
            topic_suffix, field_name, alias = entry[:3]
            bounds = entry[3:5] if len(entry) == 5 else None

            topic = topic_prefix + '/' + topic_suffix
            if topic not in TargetTopics:
                TargetTopics[topic] = {}
            TargetTopics[topic][field_name] = alias

            AliasData[alias] = {
                "timestamp": 0,
                "flag": False,          #has a progression error been printed already
                "bounds": bounds,       #(min, max) or None
                "bounds_flag": False,   #has an out-of-range error been printed already
                "max_interval": MAX_INTERVAL_OVERRIDES.get(alias, LARGESTINTERVAL),
            }
            MQTTNameToAliasName[topic + '/' + field_name] = alias

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
                    IOFileptr = self.__get_output_file_pointer()
                    print('opening file: ', IOFileptr.name)
                    _start_periodic_flush(interval=5)
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
                IOFileptr = open(IOFilename + '.log', "r")
            except:
                print("Can't open .log file for reading  -- exiting", IOFilename + '.log')
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
                alias = MQTTNameToAliasName[tmp]
                #preserve the static bounds/bounds_flag set up at init time -- only
                #replace the per-message fields (timestamp, value, progression flag)
                AliasData[alias]["timestamp"] = now
                AliasData[alias]["value"] = msg_dict[item]
                AliasData[alias]["flag"] = False
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

        if IOFilename == FILEDIR:
            print('No input file specified for output mode')
            exit()

        #open the input file
        try:
            fp_out = open(IOFilename + '.csv', "w")
        except:
            print("Can't open file for writing -- exiting", IOFilename + '.csv')
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

    # check for remaining disk space
    # The function takes a single argument, percent_free, which is the minimum percentage of free disk space that should be available.                
    def check_disk_space(self, percent_free):
        disk_usage = psutil.disk_usage('/')
        free_percent = disk_usage.free / disk_usage.total * 100
        return free_percent >= percent_free
                    
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
            #writes this dictionary to the output file on one line if enough disk space is available
            if self.check_disk_space(10):
                self.__get_output_file_pointer()
                json.dump(msg_dict, IOFileptr)
                IOFileptr.write("\n")
                #IOFileptr.flush()
            else:
                print('Disk space too low to write to file')
            if debug > 0:
                dt = datetime.datetime.fromtimestamp(time.time())
                print('wrote to file: ', dt, msg.topic, msg_dict)
                
        #Update the AliasData dictionary
        now = int(time.time())
        self._UpdateAliasData(msg_dict, now)

        #Check if timestamp is progressing for all AliasData entries except for SYS_ERRORS
        error_cnt = 0
        msg_dict = {}
        msg_dict['name'] = 'SYS_ERRORS'
        msg_dict['timestamp'] = int(time.time())
        for item in AliasData:
            if int(AliasData[item]['timestamp']) != 0  \
                    and int((AliasData[item]['timestamp'])) + AliasData[item]['max_interval'] < now  \
                    and not AliasData[item]['flag'] \
                    and item != 'SYS_ERRORS':
                AliasData[item]['flag'] = True
                elapsed = now - int(AliasData[item]['timestamp'])
                elapsed_str = f"{elapsed//60}m {elapsed%60}s" if elapsed >= 60 else f"{elapsed}s"
                alias_display = item.replace('_', ' ')
                print('No data:', alias_display, elapsed_str)
                pprint(AliasData[item])
                #build msg_dict to include error field
                msg_dict['error'] = f'No data: {alias_display} ({elapsed_str} silent)'
                self.pub(msg_dict, qos=0, retain=False)
                #write this error msg to the output file on one line
                json.dump(msg_dict, IOFileptr)
                IOFileptr.write("\n")
                if debug > 0:
                    dt = datetime.datetime.fromtimestamp(time.time())
                    print('wrote error to file: ', dt, msg.topic, msg_dict)

            #Check if value is outside its configured bounds (only for entries that declared bounds)
            bounds = AliasData[item]['bounds']
            value = AliasData[item].get('value')
            if bounds is not None and isinstance(value, (int, float)):
                in_range = bounds[0] <= value <= bounds[1]
                if not in_range and not AliasData[item]['bounds_flag']:
                    AliasData[item]['bounds_flag'] = True
                    print('Value out of bounds for  ', item, '  value = ', value, '  bounds = ', bounds)
                    pprint(AliasData[item])
                    #build msg_dict to include error field
                    msg_dict['error'] = 'Bounds error: ' + item + '  value = ' + str(value) + '  not in ' + str(bounds)
                    self.pub(msg_dict, qos=0, retain=False)
                    #write this error msg to the output file on one line
                    json.dump(msg_dict, IOFileptr)
                    IOFileptr.write("\n")
                    if debug > 0:
                        dt = datetime.datetime.fromtimestamp(time.time())
                        print('wrote bounds error to file: ', dt, msg.topic, msg_dict)
                elif in_range:
                    #value back in range -- re-arm so a future excursion is reported again
                    AliasData[item]['bounds_flag'] = False

            if AliasData[item]['flag'] or AliasData[item]['bounds_flag']:
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

#WATCH_SPEC: which MQTT fields to track, the alias each is stored/reported under,
#and (optionally) the valid value range to monitor for out-of-bounds faults.
#   Each entry is either:
#     (topic_suffix, field_name, alias)             -- no bounds check, or
#     (topic_suffix, field_name, alias, min, max)   -- flagged if value falls outside [min, max]
#   List order sets the AliasData and CSV column order.
#   Alias names must be unique across the whole spec (AliasData is keyed by alias name).
WATCH_SPEC = [
    ("CHARGER_AC_STATUS_1/1", "timestamp",                 "Charger_AC_timestamp"),
    ("CHARGER_AC_STATUS_1/1", "rms current",               "Charger_AC_current", 0, 50),
    ("CHARGER_AC_STATUS_1/1", "rms voltage",               "Charger_AC_voltage", 95,130),

    ("CHARGER_AC_STATUS_3/1", "real power",                "Charger_AC_real_power"),

    ("CHARGER_STATUS/1",      "charge current",            "Charger_current", 0,160),
    ("CHARGER_STATUS/1",      "charge voltage",            "Charger_voltage", 11,15),
    ("CHARGER_STATUS/1",      "operating state definition","Charger_state"),

    ("DM_RV",                 "red lamp status",           "DM_red_lamp"),
    ("DM_RV",                 "yellow lamp status",        "DM_yellow_lamp"),

    ("INVERTER_AC_STATUS_1/1","timestamp",                 "Invert_AC_timestamp"),
    ("INVERTER_AC_STATUS_1/1","rms current",               "Invert_AC_current", 0, 50),
    ("INVERTER_AC_STATUS_1/1","rms voltage",               "Invert_AC_voltage", 95,130),

    ("INVERTER_AC_STATUS_3/1","reactive power",            "Invert_AC_reactive_power"),
    ("INVERTER_AC_STATUS_3/1","real power",                "Invert_AC_real_power"),

    ("INVERTER_DC_STATUS/1",  "dc amperage",               "Invert_DC_amp",0,160),
    ("INVERTER_DC_STATUS/1",  "dc voltage",                "Invert_DC_volt", 11, 15),

    ("INVERTER_STATUS/1",     "timestamp",                 "Invert_timestamp"),
    ("INVERTER_STATUS/1",     "status",                    "Invert_status_num"),
    ("INVERTER_STATUS/1",     "status definition",         "Invert_status_name"),

    ("BATTERY_STATUS/1",      "timestamp",                 "Batt_timestamp"),
    ("BATTERY_STATUS/1",      "DC_voltage",                "Batt_voltage",  10, 15),
    ("BATTERY_STATUS/1",      "DC_current",                "Batt_current"),
    ("BATTERY_STATUS/1",      "State_of_charge",           "Batt_charge",   0, 100),

    ("ATS_AC_STATUS_1/1",     "line",                      "ATS_line"),
    ("ATS_AC_STATUS_1/1",     "rms current",               "ATS_AC_current"),
    ("ATS_AC_STATUS_1/1",     "rms voltage",               "ATS_AC_voltage"),

    ("SOLAR_CONTROLLER_STATUS/1","V",                     "Solar_voltage"),
    ("SOLAR_CONTROLLER_STATUS/1","I",                     "Solar_current"),

    ("TIRE_STATUS/FL",          "pressure_psi",           "Tire_FL_psi"),
    ("TIRE_STATUS/FR",          "pressure_psi",           "Tire_FR_psi"),
    ("TIRE_STATUS/RL_out",      "pressure_psi",           "Tire_RL_out_psi"),
    ("TIRE_STATUS/RL_in",       "pressure_psi",           "Tire_RL_in_psi"),
    ("TIRE_STATUS/RR_in",       "pressure_psi",           "Tire_RR_in_psi"),
    ("TIRE_STATUS/RR_out",      "pressure_psi",           "Tire_RR_out_psi"),

    ("TANK_STATUS/0",         "timestamp",                 "Tank0_timestamp"),
    ("TANK_STATUS/0",         "instance definition",      "Tank0_name"),
    ("TANK_STATUS/0",         "relative level",            "Tank0_level",   0, 100),
    ("TANK_STATUS/0",         "resolution",                "Tank0_resolution"),

    ("TANK_STATUS/1",         "timestamp",                 "Tank1_timestamp"),
    ("TANK_STATUS/1",         "instance definition",      "Tank1_name"),
    ("TANK_STATUS/1",         "relative level",            "Tank1_level",   0, 100),
    ("TANK_STATUS/1",         "resolution",                "Tank1_resolution"),

    ("TANK_STATUS/2",         "timestamp",                 "Tank2_timestamp"),
    ("TANK_STATUS/2",         "instance definition",      "Tank2_name"),
    ("TANK_STATUS/2",         "relative level",            "Tank2_level",   0, 100),
    ("TANK_STATUS/2",         "resolution",                "Tank2_resolution"),

    ("TANK_STATUS/3",         "timestamp",                 "Tank3_timestamp"),
    ("TANK_STATUS/3",         "instance definition",      "Tank3_name"),
    ("TANK_STATUS/3",         "relative level",            "Tank3_level",   0, 100),
    ("TANK_STATUS/3",         "resolution",                "Tank3_resolution"),

    ("RV_Loads/1",            "timestamp",                 "RV_Loads_timestamp"),
    ("RV_Loads/1",            "AC Load",                   "RV_Loads_AC"),
    ("RV_Loads/1",            "DC Load",                   "RV_Loads_DC"),

    ("RV_Watcher/1",          "timestamp",                 "RV_Watcher_timestamp"),
    ("RV_Watcher/1",          "Status",                    "RV_Watcher_Status"),

    ("SYS_ERRORS",            "timestamp",                 "SYS_timestamp"),
    ("SYS_ERRORS",            "error",                     "SYS_error"),
]


def _build_watch_whitelist():
    """Derive {topic: [field_names]} from WATCH_SPEC for the debug UI.

    "timestamp" entries are skipped since the UI renders each message's
    timestamp separately rather than listing it among the tracked values.
    """
    whitelist = {}
    for entry in WATCH_SPEC:
        topic_suffix, field_name = entry[0], entry[1]
        if field_name == 'timestamp':
            continue
        topic = topic_prefix + '/' + topic_suffix
        fields = whitelist.setdefault(topic, [])
        if field_name not in fields:
            fields.append(field_name)
    return whitelist


def _write_whitelist_file(log_file_name):
    """Write the WATCH_SPEC-derived whitelist next to the given .log file
    (same basename, .whitelist.json extension) so the debug UI can filter each
    raw MQTT payload down to just the fields the watcher tracks for that topic,
    without having to keep its own copy of WATCH_SPEC in sync.
    """
    whitelist_name = os.path.splitext(log_file_name)[0] + '.whitelist.json'
    try:
        with open(whitelist_name, 'w') as fp:
            json.dump(_build_watch_whitelist(), fp, indent=2)
    except Exception as e:
        print(f"Couldn't write watcher whitelist file {whitelist_name}: {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-b", "--broker", default = "localhost", help="MQTT Broker Host")
    parser.add_argument("-p", "--port", default = 1883, type=int, help="MQTT Broker Port")
    parser.add_argument("-d", "--debug", default = 0, type=int, choices=[0, 1, 2, 3], help="debug level")
    parser.add_argument("-t", "--topic", default = "RVC", help="MQTT topic prefix")
    parser.add_argument("-m", "--Mode", default = "c", help="s - screen only, b - capture MQTT msgs into file and screen output, c - file capture only , o - From xx.log file, output watched vars to xx.csv file")
    parser.add_argument("-i", "--IOfile", default = "", help="IO file name with no extension")
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

    IOFilename = FILEDIR + args.IOfile         
    RVC_Client = mqttclient('sub',broker, port, mqttTopic, debug, opmode)


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

    
