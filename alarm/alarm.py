import sys
sys.path.append('/home/pi/Code/tblank1024/rv/mqttclient')
import time
import logging
import os
#import mqttclient

# Import GPIO libraries for Raspberry Pi 5
from gpiozero import Device, LED, Button, OutputDevice, InputDevice

# For Raspberry Pi 5, use lgpio pin factory (preferred) or fallback
try:
    from gpiozero.pins.lgpio import LGPIOFactory
    Device.pin_factory = LGPIOFactory()
    print("Using LGPIO pin factory for Raspberry Pi 5")
except ImportError:
    try:
        from gpiozero.pins.rpigpio import RPiGPIOFactory
        Device.pin_factory = RPiGPIOFactory()
        print("Using RPi.GPIO pin factory (legacy)")
    except ImportError:
        print("No compatible GPIO library found")

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
    
    # Pin Definitions using BCM GPIO numbering for gpiozero:
    # Board pin -> BCM GPIO mapping for RPi
    BUZZEROUT       = 22  # Board pin 15 -> GPIO22
    HORNOUT         = 27  # Board pin 13 -> GPIO27

    PIRSENSORIN     = 5   # Board pin 29 -> GPIO5
    
    REDBUTTONIN     = 6   # Board pin 31 -> GPIO6
    REDLEDOUT       = 12  # Board pin 32 -> GPIO12
    BLUEBUTTONIN    = 13  # Board pin 33 -> GPIO13
    BLUELEDOUT      = 19  # Board pin 35 -> GPIO19

    BIKEIN1         = 16  # Board pin 36 -> GPIO16
    BIKEIN2         = 20  # Board pin 38 -> GPIO20
    BIKEOUT1        = 26  # Board pin 37 -> GPIO26
    BIKEOUT2        = 21  # Board pin 40 -> GPIO21
    

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
        """Initialize the Alarm system with GPIO devices"""
        self.debuglevel = debug

        try:
            # Clean up any existing GPIO state first
            try:
                from gpiozero import Device
                Device.pin_factory.reset()
            except:
                pass  # Ignore if reset fails
            
            # Initialize gpiozero devices
            # Output devices (LEDs, buzzer, horn, bike outputs)
            self.red_led = LED(self.REDLEDOUT)
            self.blue_led = LED(self.BLUELEDOUT)
            self.buzzer = OutputDevice(self.BUZZEROUT)
            self.horn = OutputDevice(self.HORNOUT)
            self.bike_out1 = OutputDevice(self.BIKEOUT1)
            self.bike_out2 = OutputDevice(self.BIKEOUT2)
            
            # Input devices (buttons and sensors) - using pull_up=True with inverted logic
            self.red_button  = Button(self.REDBUTTONIN, pull_up=True)
            self.blue_button = Button(self.BLUEBUTTONIN, pull_up=True)
            self.pir_sensor  = InputDevice(self.PIRSENSORIN, pull_up=True)
            self.bike_in1    = InputDevice(self.BIKEIN1, pull_up=True)
            self.bike_in2    = InputDevice(self.BIKEIN2, pull_up=True)
            
            # Set initial states
            self.red_led.off()
            self.blue_led.off()
            self.horn.off()
            self.buzzer.off()
            self.bike_out1.off()
            self.bike_out2.on()
            
            print("GPIO devices initialized successfully")
            
        except Exception as e:
            print(f"Error initializing GPIO devices: {e}")
            raise
        
        self.BikeState = States.OFF
        self.InteriorState = States.OFF


    def _toggle(self, device):
        """Toggle an output device on/off"""
        if device.is_active:
            device.off()
        else:
            device.on()
        
    
     
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
        wire1in = self.bike_in1.is_active
        wire2in = self.bike_in2.is_active
        wire1out = self.bike_out1.is_active
        wire2out = self.bike_out2.is_active
        if (wire1in == wire1out) and (wire2in == wire2out):
            error_status = False
        else:
            error_status = True
            if self.debuglevel > 0:
                logging.info("Bike Alarm triggered")
        self._toggle(self.bike_out1)
        self._toggle(self.bike_out2)
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
        if self.InteriorState == States.STARTING and not self.pir_sensor.is_active: 
             #Alarm triggered but starting (with pull_up=True, is_active=False means movement detected)
            self.set_state(AlarmTypes.Interior, States.STARTERROR)
        elif self.InteriorState == States.ON and not self.pir_sensor.is_active: 
            #Alarm triggered (with pull_up=True, is_active=False means movement detected)
            self.set_state(AlarmTypes.Interior, States.TRIGDELAY)
            self.AlarmTime = self.LoopTime
            if self.debuglevel > 0:
                logging.info("Interior Alarm triggered")

    def _check_buttons(self):
        BUTTONDELAY = 1             # Time (sec) before button press is registered

        NowTime = self.LoopTime
        RedButton = self.red_button.is_pressed     #Interior Alarm control
        BlueButton = self.blue_button.is_pressed    #Bike Alarm control
        
        if(RedButton and ((NowTime-self.LastButtonTime) > BUTTONDELAY)): 
            if self.InteriorState == States.OFF:
                self.set_state(AlarmTypes.Interior,States.STARTING)
                if self.debuglevel > 0:
                    logging.info("Red Starting")
            else:
                self.set_state(AlarmTypes.Interior,States.OFF)
                if self.debuglevel > 0:
                    logging.info("Red Stopping")
            self.LastButtonTime = NowTime

        if BlueButton and ((NowTime-self.LastButtonTime) > BUTTONDELAY): 
            #Toggle
            if self.BikeState == States.OFF:
                self.set_state(AlarmTypes.Bike, States.STARTING)
                if self.debuglevel > 0:
                    logging.info("Blue Starting")
            else:
                self.set_state(AlarmTypes.Bike, States.OFF)
                if self.debuglevel > 0:
                    logging.info("Blue Stopping")
            self.LastButtonTime = NowTime

    def _display(self):
        
        IntState    = self.StateConsts[self.InteriorState]
        BkState     = self.StateConsts[self.BikeState]
        mytime = time.localtime()
        NightTime =  mytime.tm_hour < 8 or mytime.tm_hour > 20

        if IntState[0] == 0:
            self.red_led.off() #Red light off
        elif IntState[0] == 1:
            #Red light on
            if NightTime:
                self.red_led.on()    #dim on (gpiozero doesn't support PWM on LED by default)
            else:
                self.red_led.on()    #strong on
        if BkState[0] == 0:
            self.blue_led.off() #Blue light off
        elif BkState[0] == 1:
            #Blue light on
            if NightTime:
                self.blue_led.on()    #Dim on
            else:
                self.blue_led.on()  #strong on

        
        # Combined Buzzer and Alarm values
        BuzzerVal = IntState[1] + BkState[1]
        AlarmVal = IntState[2] + BkState[2]

        if BuzzerVal == 0:
            self.buzzer.off()
        elif BuzzerVal == 1:
            if self.LOUDENABLE:
                    self.buzzer.on()
            #TINK.setLED(self.TINKERADDR,0)
        
        if AlarmVal == 0:
            self.horn.off()
        elif AlarmVal == 1:
            if self.LOUDENABLE:
                self.horn.on()
            #TINK.setDOUT(self.TINKERADDR,6)

        if BuzzerVal > 1 or AlarmVal > 1 or IntState[0] > 1 or BkState[0] > 1:
             # Someone needs to _toggle now
            if self.LoopCount % self.SLOWBLINK == 0:
                if IntState[0] > 2:            # Red Light
                    self.RedPWMVal = (self.RedPWMVal+50) % 100
                    self.red_led.on()  # simplified for gpiozero
                if BkState[0] > 2:                # Blue Light
                    self.BluePWMVal = (self.BluePWMVal + 50) % 100
                    self.blue_led.on()  # simplified for gpiozero
                if BuzzerVal > 2:
                    if self.LOUDENABLE:
                        self._toggle(self.buzzer)
                    #TINK._toggle((LED(self.TINKERADDR,0)
                if AlarmVal > 2:
                    if self.LOUDENABLE:
                        self._toggle(self.horn)
                    #TINK._toggle((DOUT(self.TINKERADDR,6)
            elif (self.LoopCount % self.FASTBLINK) == 0:
                if IntState[0] > 8:            # Red Light
                    self.RedPWMVal = (self.RedPWMVal+50) % 100
                    self.red_led.on()  # simplified for gpiozero
                if BkState[0] > 8:                # Blue Light
                    self.BluePWMVal = (self.BluePWMVal + 50) % 100
                    self.blue_led.on()  # simplified for gpiozero
                if BuzzerVal > 8:
                    if self.LOUDENABLE:
                        self._toggle(self.buzzer)
                    #TINK._toggle((LED(self.TINKERADDR,0)
                if AlarmVal > 8:
                    if self.LOUDENABLE:
                        self._toggle(self.horn)
                    #TINK._toggle((DOUT(self.TINKERADDR,6)
        if self.debuglevel == 1:
            if self.LoopCount % 3 == 0:
                print (IntState, "\t", BkState, "\t", AlarmVal, "\t\t", BuzzerVal, "\t\t", self.bike_in1.is_active, "\t", self.bike_in2.is_active)
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
            self.set_state(AlarmTypes.Bike, States.ON)
      
        elif (Bike ==  States.TRIGGERED) and ((self.LoopTime - self.AlarmTime) > (60 * self.MAXALARMTIME)):
            #self.BikeState = States.SILENCED
            self.set_state(AlarmTypes.Bike, States.SILENCED)

    def _InternalTest(self):
        #blink red and blue leds
        self.LoopCount += 1

        if self.LoopCount % 3 == 0:
            print(self.pir_sensor.is_active, "\t", self.blue_button.is_pressed, "\t", self.red_button.is_pressed, "\t", self.bike_in1.is_active, "\t", self.bike_in2.is_active)
            if self.red_button.is_pressed:
                self.red_led.on()
            else:
                self.red_led.off()
            if self.blue_button.is_pressed:
                self.blue_led.on()
            else:
                self.blue_led.off()
            # self._toggle(self.red_led)
            # self._toggle(self.blue_led)
            self._toggle(self.buzzer)
            self._toggle(self.horn)
            self._toggle(self.bike_out1)
            self._toggle(self.bike_out2)
        if self.LoopCount % 50 == 1:
            print("PIR\tRED\tBlu\tBK1\tBK2")
  
    
    def run_alarm_infinite(self):
        # run alarm code forever
        while True:                    
            
            if self.debuglevel == 10:
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
