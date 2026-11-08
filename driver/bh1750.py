from utime import sleep_ms

class BH1750():
    ADDRESS = 0x23
    PWR_OFF = 0x00
    PWR_ON = 0x01
    RESET = 0x07
    CONT_LOWRES = 0x13
    CONT_HIRES_1 = 0x10
    CONT_HIRES_2 = 0x11
    ONCE_HIRES_1 = 0x20
    ONCE_HIRES_2 = 0x21
    ONCE_LOWRES = 0x23

    def __init__(self, i2c):
        self.i2c = i2c
        self.hardWareReady=False
        self.mode = -1
        
    def initHardware(self):
        i2c_devices = self.i2c.scan()
        #print(i2c_devices)
        
        if self.ADDRESS not in i2c_devices:
            self.hardWareReady = False
        else:
            self.off()
            self.reset()
            self.hardWareReady = True
            
    def off(self):
        self.set_mode(self.PWR_OFF)
        
    def on(self):
        self.set_mode(self.PWR_ON)
        
    def reset(self):
        self.on()
        self.set_mode(self.RESET)
        
    def set_mode(self, mode):
        self.i2c.writeto(self.ADDRESS, bytes([mode]))
        self.mode = mode
        
    def luminance(self, mode):
        try:
            if not self.hardWareReady:
                self.initHardware()
                
            if mode & 0x10 and mode != self.mode:
                self.set_mode(mode)
            if mode & 0x20:
                self.set_mode(mode)
            sleep_ms(24 if mode in (self.CONT_LOWRES, self.ONCE_LOWRES) else 180)
            data = self.i2c.readfrom(self.ADDRESS, 2)
            factor = 2.0 if mode in (self.CONT_HIRES_2, self.ONCE_HIRES_2) else 1.0
            value = (data[0]<<8 | data[1]) / (1.2 * factor)
            return round(value,1)
        except (OSError,TypeError):
            self.hardWareReady = False
            return -9999
    
    
    
        