class SensorData:
    """传感器数据容器，所有无效值统一初始化为 -9999"""

    def __init__(self):
        # 温湿度（HDC1080）
        self.temp = -9999
        self.humi = -9999
        self.wetBulb = -9999   # 湿球温度 (℃)，由 AACOps 根据干球温度+湿度计算
        # 气压海拔（BMP280，预留死代码）
        self.presure = -9999
        self.altitude = -9999
        self.tempBMP280 = -9999
        # 光照（BH1750，预留死代码）
        self.luminance = -9999
        # PMS5003 颗粒物（I2C，已接入）
        self.pm1_0_cf = -9999   # PM1.0 (CF=1, 标准颗粒物) ug/m3
        self.pm2_5_cf = -9999   # PM2.5 (CF=1)
        self.pm10_cf = -9999    # PM10  (CF=1)
        self.pm1_0 = -9999      # PM1.0 (大气环境)
        self.pm2_5 = -9999      # PM2.5 (大气环境)
        self.pm10 = -9999       # PM10  (大气环境)
        self.part0_3 = -9999    # >0.3um 颗粒数/0.1L
        self.part0_5 = -9999
        self.part1_0 = -9999
        self.part2_5 = -9999
        self.part5_0 = -9999
        self.part10 = -9999
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

    @property
    def pm25(self):
        """兼容旧字段：返回大气环境 PM2.5。"""
        return self.pm2_5

    @pm25.setter
    def pm25(self, val):
        self.pm2_5 = val

    def updatePMS(self, d):
        """用 PMS5003 驱动返回的 dict 批量更新颗粒物字段。"""
        for k, v in d.items():
            if hasattr(self, k):
                setattr(self, k, v)
