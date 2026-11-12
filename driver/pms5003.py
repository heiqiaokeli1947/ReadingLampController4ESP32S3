import utime


class PMS5003:
    """PMS5003I I2C 颗粒物传感器驱动（地址 0x12）。

    32 字节数据帧：
      [0:2]   帧头 0x42 0x4D
      [2:4]   帧长 0x00 0x1C (28)
      [4:6]   PM1.0 (CF=1, 标准颗粒物)
      [6:8]   PM2.5 (CF=1)
      [8:10]  PM10  (CF=1)
      [10:12] PM1.0 (大气环境)
      [12:14] PM2.5 (大气环境)
      [14:16] PM10  (大气环境)
      [16:18] >0.3um 颗粒数/0.1L
      [18:20] >0.5um
      [20:22] >1.0um
      [22:24] >2.5um
      [24:26] >5.0um
      [26:28] >10um
      [28]    版本号
      [29]    错误码 (0=正常)
      [30:32] 校验和 = 字节[0..29] 之和
    """

    ADDRESS = 0x12
    FRAME_LEN = 32
    _HEADER = b'\x42\x4d'
    _LENGTH = b'\x00\x1c'

    # 无效值标记（与 sensorData 约定一致）
    INVALID = -9999

    def __init__(self, i2c):
        self.i2c = i2c
        self.hardWareReady = False

    def initHardware(self):
        """扫描 I2C 总线确认设备存在。"""
        try:
            devices = self.i2c.scan()
        except OSError:
            self.hardWareReady = False
            return False
        self.hardWareReady = (self.ADDRESS in devices)
        return self.hardWareReady

    def _u16(self, data, idx):
        return (data[idx] << 8) | data[idx + 1]

    def read(self):
        """读取一帧并解析，返回 dict；失败返回 None（由上层保留旧值）。

        返回字段（单位：ug/m3 或 个/0.1L）：
          pm1_0_cf, pm2_5_cf, pm10_cf   标准颗粒物(CF=1)
          pm1_0, pm2_5, pm10            大气环境
          part0_3, part0_5, part1_0, part2_5, part5_0, part10
        """
        if not self.hardWareReady:
            self.initHardware()
            if not self.hardWareReady:
                return None

        try:
            data = self.i2c.readfrom(self.ADDRESS, self.FRAME_LEN)
        except OSError:
            self.hardWareReady = False
            return None

        if len(data) != self.FRAME_LEN:
            return None

        # 帧头与帧长校验
        if data[0:2] != self._HEADER or data[2:4] != self._LENGTH:
            return None

        # 校验和：字节[0..29] 之和
        checksum = self._u16(data, 30)
        calc = 0
        for i in range(30):
            calc += data[i]
        if calc != checksum:
            return None

        # 错误码
        err = data[29]
        if err != 0:
            return None

        return {
            "pm1_0_cf": self._u16(data, 4),
            "pm2_5_cf": self._u16(data, 6),
            "pm10_cf": self._u16(data, 8),
            "pm1_0": self._u16(data, 10),
            "pm2_5": self._u16(data, 12),
            "pm10": self._u16(data, 14),
            "part0_3": self._u16(data, 16),
            "part0_5": self._u16(data, 18),
            "part1_0": self._u16(data, 20),
            "part2_5": self._u16(data, 22),
            "part5_0": self._u16(data, 24),
            "part10": self._u16(data, 26),
        }
