class SensorData:
    """传感器数据容器，所有无效值统一初始化为 -9999"""

    def __init__(self):
        # 温湿度（HDC1080，预留死代码，当前不接入）
        self.temp = -9999
        self.humi = -9999
        # 气压海拔（BMP280，预留死代码）
        self.presure = -9999
        self.altitude = -9999
        self.tempBMP280 = -9999
        # 光照（BH1750，预留死代码）
        self.luminance = -9999
        # PM2.5（PMS5003，预留死代码）
        self.pm25 = -9999
        # LM75A 温度（实际接入）
        self.tempLM75_1 = -9999  # 水冷散热器出水口温度 (0x4A)
        self.tempLM75_2 = -9999  # LED 灯板温度 (0x4F)
        self.tempLM75_3 = -9999  # 预留

    @property
    def LM75FanTemp(self):
        return self.tempLM75_1

    @LM75FanTemp.setter
    def LM75FanTemp(self, val):
        self.tempLM75_1 = val

    @property
    def LM75LedTemp(self):
        return self.tempLM75_2

    @LM75LedTemp.setter
    def LM75LedTemp(self, val):
        self.tempLM75_2 = val
