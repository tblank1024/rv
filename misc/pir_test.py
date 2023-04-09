# External module imports
import RPi.GPIO as GPIO
import time

# Pin Definitons:
PIRSensor = 17 # Broadcom pin 17 (P1 pin 11)


# Pin Setup:
GPIO.setmode(GPIO.BCM) # Broadcom pin-numbering scheme
GPIO.setup(PIRSensor, GPIO.IN) # 

count = 0
print("Here we go! Press CTRL+C to exit")
try:
    while 1:
        if GPIO.input(PIRSensor): # PIR has detected movement
            #print("Button pressed)")
            new_var = time.strftime("Event: %Y/%m/%d %H:%M:%S")
            print("\n",new_var)
            time.sleep(3.0)
            count = 0

        else: # button is pressed:
            count += 1
            print("Delta Seconds = ", count, " Hours = ", round(count/3600,2), end='\r')

        time.sleep(1.0)
except KeyboardInterrupt: # If CTRL+C is pressed, exit cleanly
    GPIO.cleanup()
    print("finished")
