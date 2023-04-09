import piplates.TINKERplate as TINK
import time
import RPi.GPIO as GPIO
import time
import logging
import mqttclient




from enum import Enum

class States(Enum):
    OFF         = 1
    ON          = 2
    STARTING    = 3
    STARTERROR  = 4
    TRIGDELAY   = 5
    TRIGGERED   = 6
    SILENCED    = 7

class AlarmTypes(Enum):
    Interior    = 1
    Bike        = 2


class Alarm:

    StateConsts = {
        # Value list assignments: 1st: Light indicator state; 2nd: Buzzer State; 3rd: Alarm State
        # Value meaning: 0 = off; 1 = on; 4 = slow blink; 16 = fast blink 

        States.OFF:         [ 0,  0,  0],     
        States.STARTING:    [ 4,  4,  0],
        States.STARTERROR:  [16, 16,  0],
        States.ON:          [ 1,  0,  0],
        States.TRIGDELAY:   [16, 16,  0],
        States.TRIGGERED:   [16, 16,  1],
        States.SILENCED:    [16, 16,  0]
    }

    #Class Constants
    ENTRYEXITDELAY  = int(30)            # Time in seconds where alarm won't go off after enable
    FASTBLINK       = int(1)             # time delay is = FASTBLINK * LoopDelay
    SLOWBLINK       = int(6 * FASTBLINK) # SLOWBLINK must be a multiple of FASTBLINK
    MAXALARMTIME    = int(2)             # Number of minutes max that the alarm can be on
    LOOPDELAY       = float(.3)          # time in seconds pausing between running loop
    TINKERADDR      = int(0)             # IO bd address
    BUZZER          = 1
    ALARMHORN       = 2
    LOUDENABLE      = True
    
    # Pin Definitons not using PI HAT:
    PIRSensor       = 17                 # Broadcom pin 17 (P1 pin 11)



    # Class variables
    AlarmTime: float        = 0.0
    BikeState: States       = States.OFF   #uses blue button
    BikeTime: float         = 0.0
    InteriorState: States   = States.OFF   #uses red button
    InteriorTime: float     = 0.0
    LastButtonTime: float   = 0.0        #Time button weas last pressed 
    LoopTime: float         = 0.0        #Time of current loop execution
    LoopCount: int          = 0          #Simple counter of loop cycles
    RedPWMVal: int          = 0          #PWM value from 0 - 100
    BluePWMVal: int          = 0          #PWM value from 0 - 100


    def __init__(self):
        ## Basic setup   
        TINK.setMODE(self.TINKERADDR,1,'BUTTON')  # Red Button
        TINK.setMODE(self.TINKERADDR,2,'PWM')     # Red LED
        TINK.setMODE(self.TINKERADDR,3,'BUTTON')  # Blue Button
        TINK.setMODE(self.TINKERADDR,4,'PWM')     # Blue LED
        TINK.setMODE(self.TINKERADDR,5,'DIN')     # PIR interior sensor 
        TINK.setMODE(self.TINKERADDR,6,'DOUT')    # Surrogate for Alarm horn
        TINK.clrLED(self.TINKERADDR,0)            # Note LED0 is surrogate for buzzer 
        TINK.setPWM(self.TINKERADDR,2,0)          # Red LED off
        TINK.setPWM(self.TINKERADDR,4,0)          # Blue LED
        TINK.clrDOUT(self.TINKERADDR,6)           # Surrogate Alarm horn
        TINK.relayOFF(self.TINKERADDR, self.BUZZER)   # Alarm Horn
        TINK.relayOFF(self.TINKERADDR, self.ALARMHORN)# Buzzer
        
        self.BikeState = States.OFF
        self.InteriorState = States.OFF
        # Pin Setup:
        GPIO.setmode(GPIO.BCM) # Broadcom pin-numbering scheme
        GPIO.setup(self.PIRSensor, GPIO.IN) # 
     
    def set_state(self, state_var: AlarmTypes, state_val: States):
        if state_var == AlarmTypes.Interior:
            self.InteriorState = state_val
            if state_val == States.STARTING:
                self.InteriorTime = self.LoopTime
        else:
            self.BikeState = state_val
            if state_val == States.STARTING:
                self.BikeTime = self.LoopTime

    def get_state(self, state_var: AlarmTypes) -> States:
        if state_var == AlarmTypes.Interior:
            return self.InteriorState
        else:
            return self.BikeState
         
    def _bikewire_error_tst(self) -> bool:
        VOL_DELTA = .20                                             #Allowed voltage delta in trip wire
        Chan1_Base = TINK.getADC(self.TINKERADDR,1)                 #This measures the 5V supply used to generate Chan3_Base and Chan4_Base 
        Chan3_Base = Chan1_Base * 0.6391                            #ratio set by resistive divider
        Chan4_Base = Chan1_Base * 0.309
        Chan3_Raw = TINK.getADC(self.TINKERADDR,3)
        Chan3_Err = abs(Chan3_Raw - Chan3_Base)
        Chan4_Raw = TINK.getADC(self.TINKERADDR,4)
        Chan4_Err = abs(Chan4_Raw - Chan4_Base)
        error_status = (Chan3_Err > VOL_DELTA) or (Chan4_Err > VOL_DELTA)
        if error_status or (self.LoopCount % 14400 == 0):
            Err_msg = ", Chan1B=, " + '%4.3f'%Chan1_Base + ", Chan3B =, "  + '%4.3f'%Chan3_Base + ", Chan4B=, " + '%4.3f'%Chan4_Base + \
                  " ,Chan3_Raw=, " + '%4.3f'%Chan3_Raw +  ", Chan4_Raw=, " + '%4.3f'%Chan4_Raw + \
                  " ,Chan3_Err=, " + '%4.3f'%Chan3_Err +  ", Chan4_Err=, " + '%4.3f'%Chan4_Err
            logging.debug(Err_msg)
        return (error_status)                                       # returns true if error detected
    
    def _check_bike_wire(self):
        # if self.BikeState in [States.ON, States.STARTING] and self._bikewire_error_tst()
            #two tests show error
            if(self.BikeState == States.STARTING):
                # Starting errror
                #self.BikeState = States.STARTERROR
                self.set_state(AlarmTypes.Bike, States.STARTERROR)
            else:
                # Alarm trigger 
                #self.BikeState = States.TRIGGERED   #Note: Bike has no alarm triggered delay.
                self.set_state(AlarmTypes.Bike, States.TRIGGERED)
                self.AlarmTime = self.LoopTime
    
    def _check_interior(self):
        if self.InteriorState == States.STARTING and GPIO.input(self.PIRSensor): 
             #Alarm triggered but starting
            self.set_state(AlarmTypes.Interior, States.STARTERROR)
        elif self.InteriorState == States.ON and GPIO.input(self.PIRSensor): 
            #Alarm triggered
            self.set_state(AlarmTypes.Interior, States.TRIGDELAY)
            self.AlarmTime = self.LoopTime
            logging.info("Interior Alarm triggered")

    def _check_buttons(self):
        BUTTONDELAY = 1             # Time (sec) before button toggles

        NowTime = self.LoopTime
        RedButton = TINK.getBUTTON(self.TINKERADDR,1)     #Interior Alarm control
        BlueButton = TINK.getBUTTON(self.TINKERADDR,3)    #Bike Alarm control
        
        if(RedButton == 1 and ((NowTime-self.LastButtonTime) > BUTTONDELAY)): 
            #Toggle
            if self.InteriorState == States.OFF:
                self.set_state(AlarmTypes.Interior,States.STARTING)
                logging.info("Red Starting")
            else:
                self.set_state(AlarmTypes.Interior,States.OFF)
                logging.info("Red Stopping")
            self.LastButtonTime = NowTime

        if BlueButton == 1 and ((NowTime-self.LastButtonTime) > BUTTONDELAY): 
            #Toggle
            if self.BikeState == States.OFF:
                self.set_state(AlarmTypes.Bike, States.STARTING)
                logging.info("Blue Starting")
            else:
                self.set_state(AlarmTypes.Bike, States.OFF)
                logging.info("Blue Stopping")
            self.LastButtonTime = NowTime

    def _display(self):
    
        IntState    = self.StateConsts[self.InteriorState]
        BkState     = self.StateConsts[self.BikeState]
        mytime = time.localtime()
        NightTime =  mytime.tm_hour < 8 or mytime.tm_hour > 20

        if IntState[0] == 0:
            TINK.setPWM(self.TINKERADDR,2, 0) #Red light off
        elif IntState[0] == 1:
            #Red light on
            if NightTime:
                TINK.setPWM(self.TINKERADDR,2,1)    #dim on
            else:
                TINK.setPWM(self.TINKERADDR,2,100)    #strong on
        if BkState[0] == 0:
            TINK.setPWM(self.TINKERADDR,4, 0) #Blue light off
        elif BkState[0] == 1:
            #Blue light on
            if NightTime:
                TINK.setPWM(self.TINKERADDR,4,1)    #Dim on
            else:
                TINK.setPWM(self.TINKERADDR,4,100)  #strong on

        
        # Combined Buzzer and Alarm values
        BuzzerVal = IntState[1] + BkState[1]
        AlarmVal = IntState[2] + BkState[2]

        if BuzzerVal == 0:
            TINK.relayOFF(self.TINKERADDR, self.BUZZER)
            TINK.clrLED(self.TINKERADDR,0)
        elif BuzzerVal == 1:
            if self.LOUDENABLE:
                    TINK.relayON(self.TINKERADDR,self.BUZZER)
            TINK.setLED(self.TINKERADDR,0)
        
        if AlarmVal == 0:
            TINK.relayOFF(self.TINKERADDR,self.ALARMHORN)
            TINK.clrDOUT(self.TINKERADDR,6)
        elif AlarmVal == 1:
            if self.LOUDENABLE:
                TINK.relayON(self.TINKERADDR,self.ALARMHORN)
            TINK.setDOUT(self.TINKERADDR,6)

        if BuzzerVal > 1 or AlarmVal > 1 or IntState[0] > 1 or BkState[0] > 1:
             # Someone needs to toggle now
            if self.LoopCount % self.SLOWBLINK == 0:
                if IntState[0] > 2:            # Red Light
                    self.RedPWMVal = (self.RedPWMVal+50) % 100
                    TINK.setPWM(self.TINKERADDR,2,self.RedPWMVal)
                if BkState[0] > 2:                # Blue Light
                    self.BluePWMVal = (self.BluePWMVal + 50) % 100
                    TINK.setPWM(self.TINKERADDR,4, self.BluePWMVal)
                if BuzzerVal > 2:
                    if self.LOUDENABLE:
                        TINK.relayTOGGLE(self.TINKERADDR,self.BUZZER)
                    TINK.toggleLED(self.TINKERADDR,0)
                if AlarmVal > 2:
                    if self.LOUDENABLE:
                        TINK.relayTOGGLE(self.TINKERADDR,self.ALARMHORN)
                    TINK.toggleDOUT(self.TINKERADDR,6)
            elif (self.LoopCount % self.FASTBLINK) == 0:
                if IntState[0] > 8:            # Red Light
                    self.RedPWMVal = (self.RedPWMVal+50) % 100
                    TINK.setPWM(self.TINKERADDR,2,self.RedPWMVal)
                if BkState[0] > 8:                # Blue Light
                    self.BluePWMVal = (self.BluePWMVal + 50) % 100
                    TINK.setPWM(self.TINKERADDR,4, self.BluePWMVal)
                if BuzzerVal > 8:
                    if self.LOUDENABLE:
                        TINK.relayTOGGLE(self.TINKERADDR,self.BUZZER)
                    TINK.toggleLED(self.TINKERADDR,0)
                if AlarmVal > 8:
                    if self.LOUDENABLE:
                        TINK.relayTOGGLE(self.TINKERADDR,self.ALARMHORN)
                    TINK.toggleDOUT(self.TINKERADDR,6)
                

       
    def _update_timed_transitions(self):
    # Three announcement assets: button light (red and blue), buzzer, and alarm horn
    # Note: buzzer and alarm horn are shared by both alarm circuits

        
        Inside = self.InteriorState
        if Inside in [States.STARTING, States.STARTERROR] and (self.LoopTime - self.InteriorTime) > self.ENTRYEXITDELAY:
            #self.InteriorState = States.ON
            self.set_state(AlarmTypes.Interior, States.ON)
    
        elif (Inside ==  States.TRIGDELAY) and ((self.LoopTime - self.AlarmTime) > self.ENTRYEXITDELAY):
            #self.InternalState = States.TRIGGERED
            self.set_state(AlarmTypes.Interior, States.TRIGGERED)
      
        elif (Inside ==  States.TRIGGERED) and ((self.LoopTime - self.AlarmTime) > (60 * self.MAXALARMTIME)):
            #self.InternalState = States.SILENCED
            self.set_state(AlarmTypes.Interior, States.SILENCED)   
       
        Bike = self.BikeState
        if (Bike in [States.STARTING, States.STARTERROR]) and (self.LoopTime - self.BikeTime) > self.ENTRYEXITDELAY:
            #self.BikeState = States.ON
            self.set_state(Bike, States.ON)
      
        elif (Bike ==  States.TRIGGERED) and ((self.LoopTime - self.AlarmTime) > (60 * self.MAXALARMTIME)):
            #self.BikeState = States.SILENCED
            self.set_state(Bike, States.SILENCED)
    
    def run_alarm_infinite(self):
        # run alarm code forever
        while True:                    
            if self.InteriorState == States.OFF and self.BikeState == States.OFF:
                #don't let the LoopCount get too big
                self.LoopCount = 1      
            else:
                self.LoopCount += 1
            self.LoopTime = time.time()
            self._check_buttons()    
            self._check_bike_wire()
            self._check_interior()
            self._update_timed_transitions()
            self._display()
            #if LoopCount % 40 == 0:
            #    print(AlarmState)
            time.sleep(self.LOOPDELAY) #sleep

if __name__ == "__main__":
    logging.basicConfig(filename='alarm.log', level=logging.DEBUG, format='%(asctime)s %(message)s')
    logging.info('Alarm App Starting')
    RVIO = Alarm()
    RVIO.run_alarm_infinite()
