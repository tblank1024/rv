import sys
sys.path.append('/home/pi/Code/tblank1024/rv/mqttclient')
import time
import RPi.GPIO as GPIO
#from rpi_hardware_pwm import HardwarePWM
import time
import logging
#import mqttclient

# https://pypi.org/project/rpi-hardware-pwm/
# GPIO_18 as the pin for PWM0  aka Pin12
# GPIO_19 as the pin for PWM1  aka Pin35
# pwm = HardwarePWM(pwm_channel=0, hz=60)
# pwm.start(100) # full duty cycle
# pwm.change_duty_cycle(50)
# pwm.change_frequency(25_000)
# pwm.stop()

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


class Alarm():

    StateConsts = {
        # Value list assignments: 1st: Light indicator state; 2nd: Buzzer State; 3rd: Alarm State
        # Value meaning: 0 = off; 1 = on; 4 = slow blink; 16 = fast blink 

        States.OFF:         [ 0,  0,  0],     
        States.STARTING:    [ 4,  4,  0],
        States.STARTERROR:  [16, 16,  0],
        States.ON:          [ 1,  0,  0],
        States.TRIGDELAY:   [16, 16,  0],
        States.TRIGGERED:   [16, 16,  1],
        States.SILENCED:    [16, 16,  0],
    }

    #Class Constants
    ENTRYEXITDELAY  = int(30)            # Time in seconds where alarm won't go off after enable
    FASTBLINK       = int(1)             # time delay is = FASTBLINK * LoopDelay
    SLOWBLINK       = int(6 * FASTBLINK) # SLOWBLINK must be a multiple of FASTBLINK
    MAXALARMTIME    = int(2)             # Number of minutes max that the alarm can be on
    LOOPDELAY       = float(.3)          # time in seconds pausing between running loop
    LOUDENABLE      = True
    
    # Pin Definitons using board connector numbering and RP.gpio:

    BUZZEROUT       = 15
    HORNOUT         = 13

    PIRSENSORIN     = 29
    
    REDBUTTONIN     = 31
    REDLEDOUT       = 32
    BLUEBUTTONIN    = 33
    BLUELEDOUT      = 35

    BIKEIN1         = 36
    BIKEIN2         = 38
    BIKEOUT1        = 37
    BIKEOUT2        = 40
    
    



    PINSINPUT       = [REDBUTTONIN, BLUEBUTTONIN, BIKEIN1, BIKEIN2, PIRSENSORIN]
    PINSOUTPUT      = [REDLEDOUT, BLUELEDOUT, BIKEOUT1, BIKEOUT2, BUZZEROUT, HORNOUT]


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
    BluePWMVal: int         = 0          #PWM value from 0 - 100
    debuglevel: int         = 0



    def __init__(self, debug):
        #New Setup using raw RPI GPIO
        global debuglevel
        debuglevel = debug

        GPIO.setmode(GPIO.BOARD)                    #use board numbering scheme
        GPIO.setwarnings(False)
        GPIO.setup(self.PINSINPUT, GPIO.IN, pull_up_down=GPIO.PUD_UP) 
        GPIO.setup(self.PINSOUTPUT, GPIO.OUT) 
        GPIO.output(self.REDLEDOUT, False)
        GPIO.output(self.BLUELEDOUT, False)
        GPIO.output(self.HORNOUT, False)
        GPIO.output(self.BUZZEROUT, False)
        GPIO.output(self.BIKEOUT1, False)
        GPIO.output(self.BIKEOUT2, True)

        
        

        #TINK.clrLED(self.TINKERADDR,0)            # Note LED0 is surrogate for buzzer 
        #TINK.clrDOUT(self.TINKERADDR,6)           # Surrogate Alarm horn
        
        self.BikeState = States.OFF
        self.InteriorState = States.OFF


    def _toggle(self, outpin):
        outval = GPIO.input(outpin)
        GPIO.output(outpin, not outval)
        
    
     
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
         
    def _bikewire_error_chk(self) -> bool:
        wire1in = GPIO.input(self.BIKEIN1)
        wire2in = GPIO.input(self.BIKEIN2)
        wire1out = GPIO.input(self.BIKEOUT1)
        wire2out = GPIO.input(self.BIKEOUT2)
        if (wire1in == wire1out) and (wire2in == wire2out):
            error_status = False
        else:
            error_status = True
            if debuglevel > 0:
                logging.info("Bike Alarm triggered")
        self._toggle(self.BIKEOUT1)
        self._toggle(self.BIKEOUT2)
        return (error_status)                                       # returns true if error detected            


    
    def _check_bike_wire(self):
        if self.BikeState in [States.ON, States.STARTING] and self._bikewire_error_chk():
            #two tests show error
            if(self.BikeState == States.STARTING):
                # Starting errror
                self.set_state(AlarmTypes.Bike, States.STARTERROR)
            else:
                # Alarm triggered 
                self.set_state(AlarmTypes.Bike, States.TRIGGERED)
                self.AlarmTime = self.LoopTime
    
    def _check_interior(self):
        if self.InteriorState == States.STARTING and GPIO.input(self.PIRSENSORIN): 
             #Alarm triggered but starting
            self.set_state(AlarmTypes.Interior, States.STARTERROR)
        elif self.InteriorState == States.ON and GPIO.input(self.PIRSENSORIN): 
            #Alarm triggered
            self.set_state(AlarmTypes.Interior, States.TRIGDELAY)
            self.AlarmTime = self.LoopTime
            if debuglevel > 0:
                logging.info("Interior Alarm triggered")

    def _check_buttons(self):
        BUTTONDELAY = 1             # Time (sec) before button _toggle((s

        NowTime = self.LoopTime
        RedButton = GPIO.input(self.REDBUTTONIN)     #Interior Alarm control
        BlueButton = GPIO.input(self.BLUEBUTTONIN)    #Bike Alarm control
        
        if(RedButton == 0 and ((NowTime-self.LastButtonTime) > BUTTONDELAY)): 
            if self.InteriorState == States.OFF:
                self.set_state(AlarmTypes.Interior,States.STARTING)
                if debuglevel > 0:
                    logging.info("Red Starting")
            else:
                self.set_state(AlarmTypes.Interior,States.OFF)
                if debuglevel > 0:
                    logging.info("Red Stopping")
            self.LastButtonTime = NowTime

        if BlueButton == 0 and ((NowTime-self.LastButtonTime) > BUTTONDELAY): 
            #_toggle((
            if self.BikeState == States.OFF:
                self.set_state(AlarmTypes.Bike, States.STARTING)
                if debuglevel > 0:
                    logging.info("Blue Starting")
            else:
                self.set_state(AlarmTypes.Bike, States.OFF)
                if debuglevel > 0:
                    logging.info("Blue Stopping")
            self.LastButtonTime = NowTime

    def _display(self):
        global debuglevel
        
        IntState    = self.StateConsts[self.InteriorState]
        BkState     = self.StateConsts[self.BikeState]
        mytime = time.localtime()
        NightTime =  mytime.tm_hour < 8 or mytime.tm_hour > 20

        if IntState[0] == 0:
            GPIO.output(self.REDLEDOUT, 0) #Red light off
        elif IntState[0] == 1:
            #Red light on
            if NightTime:
                GPIO.output(self.REDLEDOUT,1)    #dim on
            else:
                GPIO.output(self.REDLEDOUT,100)    #strong on
        if BkState[0] == 0:
            GPIO.output(self.BLUELEDOUT, 0) #Blue light off
        elif BkState[0] == 1:
            #Blue light on
            if NightTime:
                GPIO.output(self.BLUELEDOUT,1)    #Dim on
            else:
                GPIO.output(self.BLUELEDOUT,100)  #strong on

        
        # Combined Buzzer and Alarm values
        BuzzerVal = IntState[1] + BkState[1]
        AlarmVal = IntState[2] + BkState[2]

        if BuzzerVal == 0:
            GPIO.output(self.BUZZEROUT, 0)
        elif BuzzerVal == 1:
            if self.LOUDENABLE:
                    GPIO.output(self.BUZZEROUT, 1)
            #TINK.setLED(self.TINKERADDR,0)
        
        if AlarmVal == 0:
            GPIO.output(self.HORNOUT, 0)
        elif AlarmVal == 1:
            if self.LOUDENABLE:
                GPIO.output(self.HORNOUT, 1)
            #TINK.setDOUT(self.TINKERADDR,6)

        if BuzzerVal > 1 or AlarmVal > 1 or IntState[0] > 1 or BkState[0] > 1:
             # Someone needs to _toggle(( now
            if self.LoopCount % self.SLOWBLINK == 0:
                if IntState[0] > 2:            # Red Light
                    self.RedPWMVal = (self.RedPWMVal+50) % 100
                    GPIO.output(self.REDLEDOUT,self.RedPWMVal)
                if BkState[0] > 2:                # Blue Light
                    self.BluePWMVal = (self.BluePWMVal + 50) % 100
                    GPIO.output(self.BLUELEDOUT, self.BluePWMVal)
                if BuzzerVal > 2:
                    if self.LOUDENABLE:
                        self._toggle(self.BUZZEROUT)
                    #TINK._toggle((LED(self.TINKERADDR,0)
                if AlarmVal > 2:
                    if self.LOUDENABLE:
                        self._toggle(self.HORNOUT)
                    #TINK._toggle((DOUT(self.TINKERADDR,6)
            elif (self.LoopCount % self.FASTBLINK) == 0:
                if IntState[0] > 8:            # Red Light
                    self.RedPWMVal = (self.RedPWMVal+50) % 100
                    GPIO.output(self.REDLEDOUT,self.RedPWMVal)
                if BkState[0] > 8:                # Blue Light
                    self.BluePWMVal = (self.BluePWMVal + 50) % 100
                    GPIO.output(self.BLUELEDOUT, self.BluePWMVal)
                if BuzzerVal > 8:
                    if self.LOUDENABLE:
                        self._toggle(self.BUZZEROUT)
                    #TINK._toggle((LED(self.TINKERADDR,0)
                if AlarmVal > 8:
                    if self.LOUDENABLE:
                        self._toggle(self.HORNOUT)
                    #TINK._toggle((DOUT(self.TINKERADDR,6)
        if debuglevel == 1:
            if self.LoopCount % 3 == 0:
                print (IntState, "\t", BkState, "\t", AlarmVal, "\t\t", BuzzerVal, "\t\t", GPIO.input(self.BIKEIN1), "\t", GPIO.input(self.BIKEIN2))
            if self.LoopCount % 50 == 1:
                print("IntState\tBkState \tAlarmVal\tBuzzerVal\tBike1\tBike2")
                

       
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

    def _InternalTest(self):
        #blink red and blue leds
        self.LoopCount += 1

        if self.LoopCount % 3 == 0:
            print(GPIO.input(self.PIRSENSORIN), "\t", GPIO.input(self.BLUEBUTTONIN), "\t", GPIO.input(self.REDBUTTONIN), "\t", GPIO.input(self.BIKEIN1), "\t", GPIO.input(self.BIKEIN2))
            if GPIO.input(self.REDBUTTONIN):
                GPIO.output(self.REDLEDOUT,1)
            else:
                GPIO.output(self.REDLEDOUT,0)
            if GPIO.input(self.BLUEBUTTONIN):
                GPIO.output(self.BLUELEDOUT,1)
            else:
                GPIO.output(self.BLUELEDOUT,0)
            # self._toggle(self.REDLEDOUT)
            # self._toggle(self.BLUELEDOUT)
            self._toggle(self.BUZZEROUT)
            self._toggle(self.HORNOUT)
            self._toggle(self.BIKEOUT1)
            self._toggle(self.BIKEOUT2)
        if self.LoopCount % 50 == 1:
            print("PIR\tRED\tBlu\tBK1\tBK2")
  
    
    def run_alarm_infinite(self):
        # run alarm code forever
        while True:                    
            
            if debuglevel == 10:
                self._InternalTest()
            else:
                if self.InteriorState == States.OFF and self.BikeState == States.OFF and self.LoopCount > 10000:
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
    print('Starting Alarm App')
    debuglevel = 0
    if debuglevel > 0:
        logging.basicConfig(filename='alarm.log', level=logging.DEBUG, format='%(asctime)s %(message)s')
        logging.info('Alarm App Starting')

    RVIO = Alarm(debuglevel)

    RVIO.run_alarm_infinite()
