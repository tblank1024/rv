import sys

class pipins():
    #constants
    PIEPINS = {
        #dictionary with 40 entries one for each Pie Header Pin
        #list contains 2 or 3 items: 1) the function of the pin (PWR, GPIO, or ID), 2) the BCM name of the pin 3) a string containing default_pull and the 0-5 alternate functions of the pin 
        # 
        1: ["PWR", "3V3", "-"], 
        2: ["PWR", "5V0", "-"],
        3: ["GPIO", "GPIO2", "High	SDA1	SA3	LCD_VSYNC	SPI3_MOSI	CTS2	SDA3"],
        4: ["PWR", "5V0", "-"],
        5: ["GPIO", "GPIO3", "High	SCL1	SA2	LCD_HSYNC	SPI3_SCLK	RTS2	SCL33"],
        6: ["PWR", "GND", "-"], 
        7: ["GPIO", "GPIO4", "High	GPCLK0	SA1	DPI_D0	SPI4_CE0_N	TXD3	SDA3"],
        8: ["GPIO", "GPIO14", "Low	TXD0	SD6	DPI_D10	SPI5_MOSI	CTS5	TXD1"],
        9: ["PWR", "GND", "-"],
        10: ["GPIO", "GPIO15", "Low	RXD0	SD7	DPI_D11	SPI5_SCLK	RTS5	RXD1"],
        11: ["GPIO", "GPIO17", "Low	FL1	SD9	DPI_D13	RTS0	SPI1_CE1_N	RTS1"],
        12: ["GPIO", "GPIO18", "Low	PCM_CLK	SD10	DPI_D14	SPI6_CE0_N	SPI1_CE0_N	PWM0"],
        13: ["GPIO", "GPIO27", "Low	SD0_DAT3	TE1	DPI_D23	SD1_DAT3	ARM_TMS	SPI6_CE1_N"],
        14: ["PWR", "GND", "-"],
        15: ["GPIO", "GPIO22", "Low	SD0_CLK	SD14	DPI_D18	SD1_CLK	ARM_TRST	SDA6"],
        16: ["GPIO", "GPIO23", "Low	SD0_CMD	SD15	DPI_D19	SD1_CMD	ARM_RTCK	SCL6"],
        17: ["PWR", "3V3", "-"],
        18: ["GPIO", "GPIO24", "Low	SD0_DAT0	SD16	DPI_D20	SD1_DAT0	ARM_TDO	SPI3_CE1_N"],
        19: ["GPIO", "GPIO10", "Low	SPI0_MOSI	SD2	DPI_D6	-	CTS4	SDA5"],
        20: ["PWR", "GND", "-"],
        21: ["GPIO", "GPIO9", "Low	SPI0_MISO	SD1	DPI_D5	-	RXD4	SCL4"],
        22: ["GPIO", "GPIO25", "Low	SD0_DAT1	SD17	DPI_D21	SD1_DAT1	ARM_TCK	SPI4_CE1_N"],
        23: ["GPIO", "GPIO11", "Low	SPI0_SCLK	SD3	DPI_D7	-	RTS4	SCL5"],
        24: ["GPIO", "GPIO8", "High	SPI0_CE0_N	SD0	DPI_D4	-	TXD4	SDA4"],
        25: ["PWR", "GND", "-"],
        26: ["GPIO", "GPIO7", "High	SPI0_CE1_N	SWE_N	DPI_D3	SPI4_SCLK	RTS3	SCL4"],
        27: ["ID", "ID_SD", "Don't use this pin"],
        28: ["ID", "ID_SC", "Don't use this pin"],
        29: ["GPIO", "GPIO5", "High	GPCLK1	SA0	DPI_D1	SPI4_MISO	RXD3	SCL3"],
        30: ["PWR", "GND", "-"],
        31: ["GPIO", "GPIO6", "High	GPCLK2	SOE_N	DPI_D2	SPI4_MOSI	CTS3	SDA4"],
        32: ["GPIO", "GPIO12", "Low	PWM0	SD4	DPI_D8	SPI5_CE0_N	TXD5	SDA5"],
        33: ["GPIO", "GPIO13", "Low	PWM1	SD5	DPI_D9	SPI5_MISO	RXD5	SCL5"],
        34: ["PWR", "GND", "-"],
        35: ["GPIO", "GPIO19", "Low	PCM_FS	SD11	DPI_D15	SPI6_MISO	SPI1_MISO	PWM1"],
        36: ["GPIO", "GPIO16", "Low	FL0	SD8	DPI_D12	CTS0	SPI1_CE2_N	CTS1"],
        37: ["GPIO", "GPIO26", "Low	SD0_DAT2	TE0	DPI_D22	SD1_DAT2	ARM_TDI	SPI5_CE1_N"],
        38: ["GPIO", "GPIO20", "Low	PCM_DIN	SD12	DPI_D16	SPI6_MOSI	SPI1_MOSI	GPCLK0"],
        39: ["PWR", "GND", "-"],
        40: ["GPIO", "GPIO21", "Low	PCM_DOUT	SD13	DPI_D17	SPI6_SCLK	SPI1_SCLK	GPCLK1"],
    }

    CANPINSDICT = {
        "PWR": "5V0",
        "GND": "GND",
        "GPIO7": "CAN_1 chip select",
        "GPIO8": "CAN_0 chip select",
        "GPIO9": "SPI clock input",
        "GPIO10": "SPI data input",
        "GPIO11": "SPI data output",
        "GPIO23": "CAN_0 interrupt output",
        "GPIO25": "CAN_1 interrupt output",
    }

    ALARMPINSDICT = {
        "PWR":    "5V0",
        "GND":    "GND",
        "GPIO5":  "PIRSENSORIN",
        "GPIO6":  "REDBUTTONIN",
        "GPIO12": "REDLEDOUT",
        "GPIO13": "BLUEBUTTONIN",
        "GPIO16": "BIKEIN1",
        "GPIO19": "BLUELEDOUT",
        "GPIO20": "BIKEOUT1",
        "GPIO21": "BIKEOUT2",
        "GPIO22": "BUZZEROUT",
        "GPIO27": "HORNOUT",
        "GPIO26": "BIKEIN2",
    }
    
   
    def print_pins_unused(self, BCM_List_of_Dicts):
        #prints pins not used in BCM_List_of_Dicts
        mergeddict = {}
        for dicts in BCM_List_of_Dicts:
            mergeddict |= dicts
        print("Pin#\t BCM#\t\t Pull\tOptions")
        for pin in self.PIEPINS:
            if self.PIEPINS[pin][1] not in list(mergeddict.keys()):
                print(pin, "\t", self.PIEPINS[pin][1].ljust(6), "\t", self.PIEPINS[pin][2], "")
        print("")
        
        # pinsused = []
        # for pin in self.PIEPINS:
        #     if self.PIEPINS[pin][0] != ("PWR" or "GND" or "ID") and (self.PIEPINS[pin][1] not in BCM_List_of_Dicts):
        #         pinsused.append(pin)
        # return pinsused 


    def print_BCM_pins(self, used_dict):
        #used_dict must be BCM named dictionary keys and usage; prints in pins list order
        print("Pin#\t Usage\t\t\t\t BCM#\t\t Pull\tOptions")
        for pin in self.PIEPINS:
            if self.PIEPINS[pin][0] == "PWR" or self.PIEPINS[pin][0] == "GND":
                continue
            if self.PIEPINS[pin][1] in list(used_dict.keys()):
                usage = used_dict[self.PIEPINS[pin][1]].ljust(23)
                print(pin, "\t",usage, "\t", self.PIEPINS[pin][1].ljust(6), "\t", self.PIEPINS[pin][2], "")
        print("")

    def BCM_to_PIN(self, BCM_List):
        #returns the pin numbers for a list of BCM names
        pinsused = []
        for pin in self.PIEPINS:
            if self.PIEPINS[pin][1] in BCM_List:
                pinsused.append(pin)
        return pinsused
    
    def PIN_to_BCM(self, PIN_List):
        #returns the BCM names for a list of pin numbers
        pinsused = []
        for pin in self.PIEPINS:
            if pin in PIN_List:
                pinsused.append(self.PIEPINS[pin][1])
        return pinsused
    
    def _ConflictCheck(self, dictlistBCM):
        #verify that there are no overlaps between the listed dictionaries
        tempdict = {}
        errorcount = 0
        for pin in self.PIEPINS:
            tempdict[self.PIEPINS[pin][1]]=  False
        for dicts in dictlistBCM:
            for item in dicts:
                if item == "PWR" or item == "GND":
                   continue 
                if tempdict[item] == True:
                    print('Conflict error for item: ', item)
                    errorcount += 1
                else:
                    tempdict[item] = True
        if errorcount > 0:
            print('Conflict Check Complete with Error Count = ', errorcount)
            sys.exit()  
        else: 
            print('No conflict errors found')  

        
    def __init__(self):
        
        print("Initialized")


if __name__ == "__main__":

    doit = pipins()
    useddictlist = [doit.CANPINSDICT, doit.ALARMPINSDICT]
    doit._ConflictCheck(useddictlist)
    print("CAN pin list")
    doit.print_BCM_pins(doit.CANPINSDICT)
    print("Alarm pin list")
    doit.print_BCM_pins(doit.ALARMPINSDICT)
    print("Remaining unused pins")
    

    doit.print_pins_unused(useddictlist)


    

