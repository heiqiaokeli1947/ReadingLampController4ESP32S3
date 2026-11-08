
class PMS5003():
    ADDRESS = 0x12
    
    def __init__(self, i2c):
        self.hardWareReady=False
        self.PMS5003_RESULT_LENGTH=32
        self.i2c=i2c

    def initHardware(self):
        print("start scan I2C...")
        i2c_devices = self.i2c.scan()
        print(i2c_devices)
        
        if self.ADDRESS not in i2c_devices:
            self.hardWareReady = False
        else:
            self.hardWareReady = True
            
    def readPMS5003(self):
        try:
            if not self.hardWareReady:
                self.initHardware()

            #print("first device is:{}".format(hex(i2c_devices[0])))
            dataT = self.i2c.readfrom(self.ADDRESS,self.PMS5003_RESULT_LENGTH)
        
            #print("PMS5003 data:{}".format(dataT))
        
            errCode = dataT[29]
            #print("ver:{}".format(dataT[28]))
            #print("error code:{}".format(errCode))
        
            checkSum = dataT[30]*256 + dataT[31]
            #print("checkSum:{}".format(checkSum))
            checkSumCalc = 0;
            for i in range(0,29):
                checkSumCalc = checkSumCalc + dataT[i]
        
    
            #print("checkSumCalc:{}".format(checkSumCalc))
            PM2_5_Value=-1
            if (checkSum == checkSumCalc) and (0 == errCode):
                PM2_5_Value = dataT[12]*256+dataT[13]
                #print("PM2.5:{} ug/m3.".format(PM2_5_Value))
            else:
                print("checksum  or sensor error:checksum calc={},checksum from sensor={},errCode={}".format(checkSum,checkSumCalc,errCode))
                PM2_5_Value = -1
                self.hardWareReady=False
            return PM2_5_Value
        except OSError:
            self.hardWareReady = False
            return -9999
