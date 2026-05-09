import json
import time
import random
#import MQTTClient
from  rvglue import MQTTClient
import rvglue.rvglue
from tzlocal import get_localzone
import datetime

# Create an alias for easier access
AliasData = rvglue.rvglue.AliasData

# Utility functions for safe data conversion
def safe_float(value, default=0.0):
    """Safely convert a value to float, handling 'n/a' and other invalid values"""
    try:
        if isinstance(value, str) and value.lower() in ['n/a', 'na', '', 'none']:
            return default
        return float(value)
    except (ValueError, TypeError):
        return default

def safe_int(value, default=0):
    """Safely convert a value to int, handling 'n/a' and other invalid values"""
    try:
        if isinstance(value, str) and value.lower() in ['n/a', 'na', '', 'none']:
            return default
        return int(float(value))  # Convert through float first to handle decimal strings
    except (ValueError, TypeError):
        return default


try:
    fp = open("./constants.json", "rt")
    constants = json.load(fp)
except:
    print(" ")
    exit("constants.json file not found or mal formed")

# Make constants available for import
__all__ = ['constants', 'safe_float', 'safe_int', 'BATT_POWER_MAX', 
           'InvertCalcs', 'ATS_Calcs', 'SolcarCalcs', 'BatteryCalcs', 'AlternatorCalcs',
           'GenAllFlows', 'LoadCalcs', 'HouseKeeping', 'FlowMotion']

#Global constants

#BATT_VOLTS-- Battery voltage
#BATT_AH --   Total Battery capacity in amp hours 

BATT_POWER_MAX = float(constants["BATT_VOLTS"]) * float(constants["BATT_AH"])   #Max battery power in watt hours

#Global variables
timebase = 1672772504.9141579 #from replay file
Batt_Power_Last = 0
Batt_Power_Running_Avg = 50
Batt_Power_Remaining = BATT_POWER_MAX
Invert_AC_power_prev = 35     #initial value

def FlowMotion():
    
    CurrentTime = int(time.time()) % 5          #determines motion update period; updates per second

    if CurrentTime == 0:
        RightMotion = LeftMotion = "\u2002\u00A0\u2002\u00A0\u2002\u00a0\u2002"
    elif CurrentTime == 1:
        RightMotion = ">\u2002\u00A0\u2002\u00A0\u2002\u00A0"
        LeftMotion  = "\u2002\u00A0\u2002\u00A0\u2002\u00A0<"
    elif CurrentTime == 2: 
        RightMotion = "> >\u2002\u00A0\u2002\u00A0"
        LeftMotion  = "\u2002\u00A0\u2002\u00A0< <"
    elif CurrentTime == 3:
        RightMotion = "> > >\u2002\u00A0"
        LeftMotion  = "\u2002\u00A0< < <"
    elif CurrentTime == 4:
        RightMotion = "> > > >"
        LeftMotion  = "< < < <"
    return(RightMotion, LeftMotion)

def GenAllFlows(Invert_status_num, BatteryPower, SolarPower, ShorePower, GenPower, AltPower):
    
    try:
        Invert_status_str = AliasData.get("_var15Invert_status_name", "Unknown")                                  #Invertor string meaning"
    except:
        Invert_status_str = "Unknown"

    RightMotion, LeftMotion = FlowMotion()  
    if BatteryPower == 0:
        BatteryFlow = ''
    elif BatteryPower > 0:                  #Battery charging 
        BatteryFlow = LeftMotion
    else:
        BatteryFlow = RightMotion

    if Invert_status_num == 1:              #DC powered  xxx
        if BatteryPower > 0:                #Battery charging if positive power
            Invert_status_str = 'Alternator Powered'
        else:
            Invert_status_str = 'Battery Powered'
        InvertPwrFlow = LeftMotion

    elif Invert_status_num == 2:            #AC/Shore powered
        Invert_status_str = 'Shore Powered'
        InvertPwrFlow = RightMotion

    else:
        InvertPwrFlow = '??'

    if AltPower > 0:
        AltPwrFlow = RightMotion
    else:
        AltPwrFlow = ''
        
    if SolarPower > 0:
        SolarPwrFlow = RightMotion
    else:
        SolarPwrFlow = ''

    if ShorePower > 0:
        ShorePwrFlow = RightMotion
    else:
        ShorePwrFlow = ''

    if GenPower > 0:
        GeneratorPwrFlow = LeftMotion
    else:
        GeneratorPwrFlow = ''

    return(BatteryFlow, InvertPwrFlow, ShorePwrFlow, GeneratorPwrFlow, SolarPwrFlow, AltPwrFlow, Invert_status_str)

BATT_DATA_STALE_SECONDS = 120   # Warn if battery MQTT data is older than this

def BatteryCalcs(debug):
    global Batt_Power_Last, Batt_Power_Running_Avg, Batt_Power_Remaining, BATT_POWER_MAX
    global _Loop_Call_count

    #Assumptions: 
    #   BatteryPower is positive when charging
    #   Loop is activated once per second
    #   2 x 125 Amp-Hr batteries in system (250 Amp-Hr total)
    #   12V battery system => 12V * 250 Amp-Hr = 3000 Watt-Hr battery capacity

    try:
        Batt_Charge = safe_float(AliasData.get("_var20Batt_charge"))                                     #Battery % charged"
        Batt_Current = safe_int(AliasData.get("_var19Batt_current", 0))                                  #Battery current
        Batt_Voltage = safe_float(AliasData.get("_var18Batt_voltage", 12.5))                                #Battery voltage"  TODO which DC voltage to use???

        # --- Staleness check: warn if battery data has not been updated recently ---
        batt_timestamp = safe_float(AliasData.get("_var18Batt_voltage_ts", 0))   # adjust key if timestamp stored differently
        if batt_timestamp > 0:
            data_age = time.time() - batt_timestamp
            if data_age > BATT_DATA_STALE_SECONDS:
                print(f"WARNING: Battery MQTT data is STALE ({data_age:.0f}s old). Calcs may be wrong!")
    except:
        #default values
        Batt_Voltage = 12.5 
        Batt_Charge = 100
        Batt_Current = 0
        print("Error reading battery data - using defaults")

    Batt_Power = Batt_Voltage * Batt_Current
    Batt_Power_Remaining = BATT_POWER_MAX * Batt_Charge/100

    if Batt_Power == 0:
        Batt_status_str = 'Floating'
        Batt_Hours_Remaining_str = ' '
    elif Batt_Power < 0:
        #discharging
        Batt_status_str = 'Discharging'
        # If avg was reset (e.g. just finished charging), seed it with current draw to avoid div/zero
        if Batt_Power_Running_Avg == 0:
            Batt_Power_Running_Avg = -Batt_Power   # seed with actual current draw (positive watts)
            print(f"INFO: Batt_Power_Running_Avg seeded to {Batt_Power_Running_Avg:.1f}W (was zero)")
        Batt_Power_Running_Avg = (Batt_Power_Running_Avg * 15 - Batt_Power) / 16            #Watt-hours discharging  
        Batt_Hours_Remaining_str = 'Est hours remaining: ' + str('%.1f' % (Batt_Power_Remaining  / Batt_Power_Running_Avg))
    else: #Battery charging; Batt_Power > 0
        Batt_Power_Running_Avg = 0
        #use charging power to calculate time to 100% charge (assuming 100% charge is BATT_POWER_MAX Watt-hours)
        Batt_Hrs_to_Full = (BATT_POWER_MAX - Batt_Power_Remaining)/ Batt_Power          
        Batt_Hours_Remaining_str = 'Est hours to 100%:   ' + str('%.1f' % Batt_Hrs_to_Full)  
        if Batt_Voltage > 14.8:
            Batt_status_str = 'Over-Voltage Charging Fault'
        elif Batt_Voltage > 14.4:
            Batt_status_str = 'Absorption Charging'
        elif Batt_Voltage > 13.8:
            Batt_status_str = 'Bulk Charging'
        else:
            Batt_status_str = 'Float Charging'

            
    
    
    if debug > -1:
       if _Loop_Call_count % 10 == 0:
           print(f"Battery: {Batt_Voltage:.1f}V {Batt_Current:.1f}A {Batt_Charge:.1f}% {Batt_Power_Running_Avg:.1f}Ave_W {Batt_Power_Remaining:.1f}   {Batt_Hours_Remaining_str}")

    return(Batt_Power, Batt_Voltage, Batt_Charge, Batt_Hours_Remaining_str, Batt_status_str)

def InvertCalcs():
    INVERT_STANDBY_PWR = 26  #Watts - measured power used by inverter when on but no load
    global Invert_AC_power_prev
    #Inverter Power Calculations
    
    try:
        Invert_status_num = AliasData["_var16Invert_status_num"]                                   #DC Invertor numerical state"
    except:
        Invert_status_num = 0  # Default to disabled
        
    """note: Invert_status_num meaning = 
        0 - Disabled
        1 - Invert
        2 - AC passthru
        3 - APS Only
        4 - Load sense (Unit is waiting for a load.)
        5 - Waiting to Invert
        6. Generator support
    """
    #Charger AC input (unidirectional input into charger/invertor. Power either from Gen or Shore )
    Charger_AC_current = safe_float(AliasData.get("_var02Charger_AC_current", 0))                                #AC charger RMS current" 
    Charger_AC_voltage = safe_float(AliasData.get("_var03Charger_AC_voltage", 0))                                #AC charger RMS voltage" 
    Charger_AC_power = Charger_AC_voltage * Charger_AC_current 
                                                        #AC charger power 
    #Charger DC output side from AC Charger. Power either from Gen or Shore
    DC_Charger_current = safe_float(AliasData.get("_var04Charger_current", 0))                                   #DC charger  current"  
    DC_Charger_volts = safe_float(AliasData.get("_var05Charger_voltage", 0))                                #DC charger  voltage" 
    DC_Charger_power = DC_Charger_volts * DC_Charger_current 
                                                    #DC charger power
    #Inverter AC output (Drives AC Coach only; power either from DC sdie or Shore/Gen) 
    Invert_AC_voltage = safe_float(AliasData.get("_var10Invert_AC_voltage", 0))                             #AC invertor RMS voltage" 
    Invert_AC_current = safe_float(AliasData.get("_var09Invert_AC_current", 0))                                #AC invertor RMS current"
    Invert_AC_power = Invert_AC_voltage * Invert_AC_current                                                      #AC invertor power
    
    #DC Invertor input (Only operates if no Shore/Gen power. Power from DC side only)
    #Don't care much about the DC side.  Only necessary for inverter efficiency calculations
    Invert_DC_Amp = safe_float(AliasData.get("_var13Invert_DC_Amp", 0))                               #DC Invertor current"
    Invert_DC_Volt = safe_float(AliasData.get("_var14Invert_DC_Volt", 0))                            #DC Invertor voltage"
    Invert_DC_power = Invert_DC_Volt * Invert_DC_Amp                #DC Invertor power

    #heuristics to compinsate for very lower power values and poor A/D resolution
    if Invert_status_num == 1:
        #Invertor is on
        if Invert_AC_power < 10:
            Invert_AC_power = .8 * Invert_DC_power      #.8 is efficiency estimate of inverter
    elif Invert_status_num == 2:
        #AC passthru
        if Invert_AC_power < 10:
            Invert_AC_power = Charger_AC_power - 1.2 * DC_Charger_power  #20% is efficiency estimate of charger
    elif Invert_status_num == 255:
        # 255 = uninitialized / CAN bus error sentinel — treat as unknown/disabled
        print(f'{datetime.datetime.now().isoformat()} WARNING: Inverter status 255 (CAN bus error or uninitialized). Defaulting to 0W.')
        Invert_AC_power = 0
    else:
        #shouldn't get  here
        print(f'{datetime.datetime.now().isoformat()} WARNING: Unexpected Invertor status = {Invert_status_num}')
    Invert_AC_power = (Invert_AC_power  * 8 + Invert_AC_power_prev * 8)/16
    Invert_AC_power_prev = Invert_AC_power

    #print('Inver AC = ',Invert_AC_power, 'DC = ', Invert_DC_power)

    return(Charger_AC_power, Charger_AC_voltage, Invert_AC_power, DC_Charger_power, DC_Charger_volts, Invert_DC_power, Invert_status_num)

def ATS_Calcs():
    # ATS == Automatic Transfer Switch

    # try:
    #     ATS_Power = AliasData["_var23ATS_AC_voltage"] * AliasData["_var22ATS_AC_current"] 
    #     ATS_Line = AliasData["_var21ATS_Line"]
    # except:
    #     ATS_Power = 0
    #     ATS_Line = 0

    # if ATS_Line == 1:
    #     ShorePower = ATS_Power
    #     GenPower = 0
    # else:
    #     ShorePower = 0
    #     GenPower = ATS_Power  
    
    #huerestic until better info available; assumes airconditioner is NOT on TODO
    Charger_AC_current = safe_float(AliasData.get("_var02Charger_AC_current", 0))                                #AC charger RMS current" 
    Charger_AC_voltage = safe_float(AliasData.get("_var03Charger_AC_voltage", 0))                                #AC charger RMS voltage" 
    ShorePower = round(Charger_AC_voltage * Charger_AC_current  )
    GenPower = 0


    return(ShorePower, GenPower)  

_Loop_Call_count = 0

def SolcarCalcs():
    global _Loop_Call_count

    #Solar power calculations
    SolarVBatt = safe_float(AliasData.get("_var40Solar_VBatt", 0), 0) 
    SolarIBatt = safe_float(AliasData.get("_var41Solar_IBatt", 0), 0)
    SolarPower = SolarVBatt * SolarIBatt
    _Loop_Call_count += 1
    if _Loop_Call_count % 10 == 0:
        print(f"Solar: {SolarVBatt:.1f}V {SolarIBatt:.1f}A {SolarPower:.1f}W")

    #only provide reasonable values 
    if SolarPower < 0:
        SolarPower = 0
        #print('Error: Solar power < 0')
    return(round(SolarPower))

def AlternatorCalcs(Batt_Power, Invert_status_num, InvertorDCPower, SolarPower):
    #Note: Alternator power not measured so using estimate 
    # Alternator power = Batt_Power + DC_Load + InvertorDCPower - SolarPower 
    if Invert_status_num == 2:                  # AC passthru
        AlternatorPower = 0
    elif Invert_status_num == 1:                # Inverter
        #Only power sources are Alternator and Solar
        #Assume that the battery is charging from the Alternator and DC_Load is unchanged
        #AC_Load = AliasData["_var24RV_Loads_AC"]
        # try:
        #     DC_Load = AliasData["_var25RV_Loads_DC"]
        #     if DC_Load == '':
        #         DC_Load = 54
        # except:
        #     DC_Load = 54
        DC_Load = 0 #Don't know what this is so assume it is zero and its small anyway
        AlternatorPower = Batt_Power + DC_Load + InvertorDCPower - SolarPower #Note: Battery power is positive when charging
    else:
        #shouldn't get here
        AlternatorPower = 0

    #only proivde reasonable values
    if AlternatorPower < 0:
        AlternatorPower = 0
    elif AlternatorPower > 2500:
        print('Alternator power > 2500W.  Check for error   ', AlternatorPower)
        AlternatorPower = 2500

    return(AlternatorPower)

def LoadCalcs(Invert_status_num, Charger_AC_power, DC_Charger_power, ShorePower, GenPower, Batt_Power, SolarPower, AlternatorPower, Invert_DC_power):
#Calc  AC HeatPump and DC Loads since not measured
    
    if Invert_status_num == 1:          #Not Shore/Gen driven; power drven by DC side
        DC_Load = -Batt_Power + SolarPower + AlternatorPower - Invert_DC_power  #Batt_Power is negative when discharging
    elif Invert_status_num == 2:        #AC Passthrough so Shore/Gen driven
        DC_Load = DC_Charger_power + SolarPower + AlternatorPower - Batt_Power     
    else:
        #Shouldn't get here
        DC_Load = -1
        print(f'{datetime.datetime.now().isoformat()} ERROR: Invert_status_num = >', Invert_status_num, '<')

    # "RV_Loads/1": {
    #                     "instance": 1,
    #                     "name": "RV_Loads",
    #                     "AC Load":                                      "_var24RV_Loads_AC",
    #                     "DC Load":                                      "_var25RV_Loads_DC",
    #                     "timestamp": "1672774554.8647683"}   

    #Update the dictionary entry with new data and publish
    # TODO: Fix AllData import issue
    # AllData['RV_Loads/1']["AC Load"] = 10 * random.random()
    # AllData['RV_Loads/1']["CD Load"] =  10 * random.random() + 10
    # AllData['RV_Loads/1']["timestamp"] = 10 * random.random()+ 20
    # MQTTClient.pub(AllData['RV_Loads/1'])  #this line doesn't work<<<
    
    
    #publish DC Load to mqtt TODO   
    # 
    AC_HeatPump = ShorePower + GenPower - Charger_AC_power
    if AC_HeatPump < 0:                #Shouldn't get here unless Shore/Gen power is zero
        AC_HeatPump = 0

    return(AC_HeatPump, DC_Load)



def HouseKeeping():
    #House Keeping Messages
    try:
        RedLamp = str(AliasData.get("_var07Red", "00"))
    except:
        RedLamp = "00"
        
    if RedLamp == '00':
        RedMsg = ''
    else:
        RedMsg = RedLamp + ' Red Lamp Fault'
        
    try:
        YellowLamp = str(AliasData.get("_var08Yellow", "00")) + " Yellow Lamp"
    except:
        YellowLamp = "00 Yellow Lamp"
    YellowMsg = ''
    
    # Use current wall clock time instead of potentially stale MQTT timestamp
    local_timezone = get_localzone()
    datetime_obj = datetime.datetime.now(tz=local_timezone)
    Time_Str = datetime_obj.strftime("%Y-%m-%d %I:%M:%S %p")
        
    return(RedMsg, YellowMsg, Time_Str)

if __name__ == "__main__":
   
    print("serv_calcs doesn't run standalone")