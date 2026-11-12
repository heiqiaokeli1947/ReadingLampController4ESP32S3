import utime
from domain.LogUtils import log
from machine import Pin, PWM, I2C
from micropython import const
import domain.sensorData as sensorData
from domain.AACOps import AACOptimized
import neopixel
import driver.lm75a as lm75a
import driver.bmp280 as bmp280
import driver.hdc1080 as hdc1080
import driver.bh1750 as bh1750
import driver.pms5003 as pms5003
from lib.rotary.rotary_irq_esp import RotaryIRQ
from driver.ws2818_matrix import WS2818Matrix

# 传感器健康管理参数
_SENSOR_STALE_MS = const(10000)        # 超过 10s 无有效值 → 数据判为老化，置无效值
_I2C_MAX_FAIL_COUNT = const(30)        # 连续 30 次读失败 → 重建 I2C 总线
_I2C_RECOVER_RETRY_MS = const(60000)   # 传感器全缺失时每 60s 重试扫描（支持热插拔）
_PMS5003_INIT_RETRY = const(6)         # PMS5003 上电预热重试次数（传感器约需 10s 就绪）
_PMS5003_INIT_DELAY_MS = const(2000)   # 每次重试间隔 2s
_HOTPLUG_INTERVAL_MS = const(5000)     # 热插拔重连检测间隔：缺失传感器每 5s 快速扫描一次

_DEFAULT_PWM_FREQ = const(25000)
_DEFAULT_PWM_DUTY = const(0)


class BSP:
    """硬件抽象层：ESP32-S3 引脚映射 + PWM/传感器/编码器管理"""

    # 引脚定义（迁移自 WROOM-32，详见 Doc/引脚迁移方案.md）
    PIN_SOFT_I2C_SCL = 7   # LM75A SCL (原 GPIO32，S3 无 32→同位置左7)
    PIN_SOFT_I2C_SDA = 42  # LM75A SDA (原 GPIO4，S3 右13=PSRAM→移至右6)
    PIN_HARD_I2C_SCL = 2   # 死代码 HardI2C SCL (原 GPIO22，S3 无 22→右5)
    PIN_HARD_I2C_SDA = 41  # 死代码 HardI2C SDA (原 GPIO21，同位置附近右7，strap 但死代码)
    PIN_LED_EN_A = 3       # LED 电源使能 A (原 GPIO12，同位置左13，JTAG strap 已验证可用)
    PIN_LED_EN_B = 9       # LED 电源使能 B (原 GPIO13，同位置左15)
    PIN_FAN_PWM = 8        # 风扇 PWM (原 GPIO14，同位置左12)
    PIN_PUMP_PWM = 18      # 水泵 PWM (原 GPIO27，同位置左11)
    PIN_YELLOW_PWM = 17    # 暖黄 LED PWM (原 GPIO26，同位置左10)
    PIN_WHITE_PWM = 16     # 冷白 LED PWM (原 GPIO25，S3 无 25→同位置左9)
    PIN_ROTARY_CLK = 40    # 编码器 CLK (原 GPIO16，S3 右12=PSRAM→就近右8)
    PIN_ROTARY_DT = 39     # 编码器 DT (原 GPIO17，S3 右11=PSRAM→就近右9)
    PIN_ROTARY_KEY = 1     # 编码器按键 (原 GPIO23，S3 无 23→就近右4)
    PIN_WS2812 = 48        # 状态指示灯 WS2812 (原 GPIO2 板载 LED)
    PIN_WS2818_MATRIX = 47  # 8x8 WS2818 矩阵数据脚 (右17，紧邻 GPIO48 状态灯)

    # 单例
    __instance = None

    def __new__(cls, *args, **kwargs):
        if cls.__instance is None:
            cls.__instance = super(BSP, cls).__new__(cls)
            cls.__instance._initialized = False
        return cls.__instance

    def __init__(self):
        if self._initialized:
            log("BSP already initialized.")
            return

        log("BSP Initializing...")
        self.config = None
        self._pwmReady = False
        # 记录各通道当前 PWM 频率，避免重复设置导致输出毛刺
        self._pwmFreq = {}

        # 硬件 I2C（I2C0，GPIO7=SCL, GPIO42=SDA，100kHz）
        # 共享总线设备：LM75A×2、PMS5003、BH1750、BMP280、HDC1080
        self.i2c = I2C(0, scl=Pin(self.PIN_SOFT_I2C_SCL),
                       sda=Pin(self.PIN_SOFT_I2C_SDA), freq=100000)

        # WS2812 状态灯
        self.__LEDArray = neopixel.NeoPixel(Pin(self.PIN_WS2812), 1)

        # WS2818 8x8 矩阵
        self.matrix = WS2818Matrix(self.PIN_WS2818_MATRIX, 8, 8, serpentine=False, rotation=90)

        # LED 电源使能
        self.__LED_EN_A = Pin(self.PIN_LED_EN_A, Pin.OUT, value=0)
        self.__LED_EN_B = Pin(self.PIN_LED_EN_B, Pin.OUT, value=0)

        # PWM 通道统一存字典，避免名称混淆 hack 与重复分配
        self._pwmChannels = {}  # {"fanPwm": PWM, "pumpPwm": PWM, ...}

        self.__fanSpeed = 0
        self.__pumpSpeed = 0
        self.__lightStatus = False

        self.__sensorData = sensorData.SensorData()
        # 湿球温度计算器（根据 HDC1080 干球温度+湿度计算）
        self._aac = AACOptimized()

        # 传感器健康状态（老化判定 + 总线自愈）
        self._lastGoodFanTick = 0      # 0 表示自启动起从未读到有效值
        self._lastGoodLedTick = 0
        self._lastGoodPmsTick = 0
        self._lastGoodBh1750Tick = 0
        self._lastGoodBmp280Tick = 0
        self._lastGoodHdc1080Tick = 0
        self._fanReadFailed = False    # 故障/恢复日志翻转标记
        self._ledReadFailed = False
        self._pmsReadFailed = False
        self._bh1750ReadFailed = False
        self._bmp280ReadFailed = False
        self._hdc1080ReadFailed = False
        self._i2cFailCount = 0         # 连续读失败次数
        self._lastRecoverTick = utime.ticks_ms()
        self._lastHotPlugTick = 0      # 热插拔重连检测上次时间戳（所有缺失传感器共用）

        # LM75A 温度传感器（散热器出水口 0x4A，灯板 0x4F）
        # 逐个容错：缺失/总线故障时降级为 None，避免 OSError 冒泡到模块级
        # bspInstance 实例化导致 main.py 启动中止（整机停摆）
        self.LM75FanTemp = self._createLm75A(0x4A, "fan")
        self.LM75LedTemp = self._createLm75A(0x4F, "led")

        # PMS5003 颗粒物传感器（I2C 0x12，共享 I2C 总线）
        self.pms5003 = self._createPMS5003()

        # BH1750 光照传感器（I2C 0x23，共享 I2C 总线）
        self.bh1750 = self._createBH1750()
        # BMP280 气压/温度传感器（I2C 0x76，共享 I2C 总线）
        self.bmp280 = self._createBMP280()
        # HDC1080 温湿度传感器（I2C 0x40，共享 I2C 总线）
        self.hdc1080 = self._createHDC1080()

        # 旋转编码器
        self.knob = RotaryIRQ(pin_num_clk=self.PIN_ROTARY_CLK,
                              pin_num_dt=self.PIN_ROTARY_DT,
                              min_val=0,
                              max_val=20,
                              reverse=True,
                              range_mode=RotaryIRQ.RANGE_UNBOUNDED,
                              invert=False)
        self.knobKey = Pin(self.PIN_ROTARY_KEY, Pin.IN, Pin.PULL_UP)

        self._lastSensorTick = 0

        self._initialized = True
        log("BSP initialized.")

    def setConfig(self, config):
        self.config = config
        if self._pwmReady:
            self.updatePWM()
        else:
            self.initHW()

    def initHW(self):
        """PWM 对象仅构造一次（雾化器规范：避免重建导致泄漏+输出毛刺）"""
        log("init PWM...")
        self._pwmChannels = {
            "fanPwm": PWM(Pin(self.PIN_FAN_PWM), freq=int(self.config["fanPwmFreq"]), duty=_DEFAULT_PWM_DUTY),
            "pumpPwm": PWM(Pin(self.PIN_PUMP_PWM), freq=int(self.config["pumpPwmFreq"]), duty=_DEFAULT_PWM_DUTY),
            "yellowPwm": PWM(Pin(self.PIN_YELLOW_PWM), freq=int(self.config["yellowPwmFreq"]), duty=_DEFAULT_PWM_DUTY),
            "whitePwm": PWM(Pin(self.PIN_WHITE_PWM), freq=int(self.config["whitePwmFreq"]), duty=_DEFAULT_PWM_DUTY),
        }
        self._pwmFreq = {
            "fanPwm": int(self.config["fanPwmFreq"]),
            "pumpPwm": int(self.config["pumpPwmFreq"]),
            "yellowPwm": int(self.config["yellowPwmFreq"]),
            "whitePwm": int(self.config["whitePwmFreq"]),
        }
        self._pwmReady = True

    def updatePWM(self):
        """配置变更时原地更新 PWM 频率，不重建对象、不改动占空比。
        占空比由各 FSM 依据当前目标值在 reloadConfig 后重新应用（_configDirty 标记），
        避免保存任意配置时把运行中的灯/风扇/水泵 duty 强制归零导致瞬断。"""
        for ch, key in (("fanPwm", "fanPwmFreq"), ("pumpPwm", "pumpPwmFreq"),
                        ("yellowPwm", "yellowPwmFreq"), ("whitePwm", "whitePwmFreq")):
            newFreq = int(self.config[key])
            if self._pwmFreq.get(ch) != newFreq:
                self._pwmChannels[ch].freq(newFreq)
                self._pwmFreq[ch] = newFreq

    def _createLm75A(self, address, name):
        """创建 LM75A 实例；缺失/总线故障时返回 None（避免 OSError 冒泡打断启动）"""
        try:
            sensor = lm75a.LM75A(self.i2c, address)
            log("LM75A {} (0x{:02X}) ready.".format(name, address))
            return sensor
        except OSError as e:
            log("[WARN] LM75A {}(0x{:02X}) not found, temp unavailable:{}".format(
                name, address, e))
            return None

    def _createPMS5003(self, quick=False):
        """创建 PMS5003 实例并扫描总线。
        PMS5003 上电后激光/风扇需约 10s 预热，I2C 接口在预热期可能无响应。
        - quick=False（开机初始化）：多次重试扫描，等待传感器预热就绪
        - quick=True（热插拔重连）：单次快速扫描，传感器已上电应立即响应"""
        try:
            sensor = pms5003.PMS5003(self.i2c)
            if quick:
                if sensor.initHardware():
                    log("PMS5003 (0x{:02X}) hot-plug detected.".format(
                        pms5003.PMS5003.ADDRESS))
                    return sensor
                return None
            for i in range(_PMS5003_INIT_RETRY):
                if sensor.initHardware():
                    log("PMS5003 (0x{:02X}) ready.".format(pms5003.PMS5003.ADDRESS))
                    return sensor
                if i < _PMS5003_INIT_RETRY - 1:
                    utime.sleep_ms(_PMS5003_INIT_DELAY_MS)
            log("[WARN] PMS5003 (0x{:02X}) not found on I2C bus after {} retries.".format(
                pms5003.PMS5003.ADDRESS, _PMS5003_INIT_RETRY))
            return None
        except OSError as e:
            log("[WARN] PMS5003 init failed:{}".format(e))
            return None

    def _createBH1750(self, quick=False):
        """创建 BH1750 光照传感器实例并扫描总线。
        - quick=False（开机初始化）：创建即尝试 initHardware
        - quick=True（热插拔重连）：仅扫描总线确认存在"""
        try:
            sensor = bh1750.BH1750(self.i2c)
            sensor.initHardware()
            if sensor.hardWareReady:
                if quick:
                    log("BH1750 (0x{:02X}) hot-plug detected.".format(
                        bh1750.BH1750.ADDRESS))
                else:
                    log("BH1750 (0x{:02X}) ready.".format(bh1750.BH1750.ADDRESS))
                return sensor
            if not quick:
                log("[WARN] BH1750 (0x{:02X}) not found on I2C bus.".format(
                    bh1750.BH1750.ADDRESS))
            return None
        except OSError as e:
            log("[WARN] BH1750 init failed:{}".format(e))
            return None

    def _createBMP280(self, quick=False):
        """创建 BMP280 气压/温度传感器实例并扫描总线。"""
        try:
            sensor = bmp280.BMP280(self.i2c)
            sensor.initHardware()
            if sensor.hardWareReady:
                if quick:
                    log("BMP280 (0x{:02X}) hot-plug detected.".format(
                        bmp280.BMP280.ADDRESS))
                else:
                    log("BMP280 (0x{:02X}) ready.".format(bmp280.BMP280.ADDRESS))
                return sensor
            if not quick:
                log("[WARN] BMP280 (0x{:02X}) not found on I2C bus.".format(
                    bmp280.BMP280.ADDRESS))
            return None
        except OSError as e:
            log("[WARN] BMP280 init failed:{}".format(e))
            return None

    def _createHDC1080(self, quick=False):
        """创建 HDC1080 温湿度传感器实例并扫描总线。"""
        try:
            sensor = hdc1080.HDC1080(self.i2c)
            sensor.initHardware()
            if sensor.hardWareReady:
                if quick:
                    log("HDC1080 (0x{:02X}) hot-plug detected.".format(
                        0x40))
                else:
                    log("HDC1080 (0x{:02X}) ready.".format(0x40))
                return sensor
            if not quick:
                log("[WARN] HDC1080 (0x{:02X}) not found on I2C bus.".format(0x40))
            return None
        except OSError as e:
            log("[WARN] HDC1080 init failed:{}".format(e))
            return None

    def readSensors(self):
        """由主循环时间驱动调用（1Hz），读取 LM75A 温度。容错策略：
        1. 单次读失败：保留上次有效值，日志仅在"故障/恢复"翻转时各打印一次
        2. 连续 _SENSOR_STALE_MS 无有效值：数据判为老化，置 -9999 交 FSM 故障安全处理
        3. 连续 _I2C_MAX_FAIL_COUNT 次读失败：重建 I2C 总线与传感器对象（总线锁死自愈）
        4. 任一路传感器缺失：每 _I2C_RECOVER_RETRY_MS 重试扫描，支持热插拔"""
        now = utime.ticks_ms()
        if utime.ticks_diff(now, self._lastSensorTick) < 1000:
            return
        self._lastSensorTick = now

        failed = False
        # 传感器缺失时对象为 None，跳过读取（温度保持无效值 -9999）
        if self.LM75FanTemp is not None:
            try:
                self.__sensorData.LM75FanTemp = self.LM75FanTemp.temp()
                self._lastGoodFanTick = now
                if self._fanReadFailed:
                    self._fanReadFailed = False
                    log("LM75A fan(0x4A) read recovered.")
            except OSError as e:
                failed = True
                if not self._fanReadFailed:
                    self._fanReadFailed = True
                    log("[WARN] LM75A fan(0x4A) read failed, keep last value:{}".format(e))

        if self.LM75LedTemp is not None:
            try:
                self.__sensorData.LM75LedTemp = self.LM75LedTemp.temp()
                self._lastGoodLedTick = now
                if self._ledReadFailed:
                    self._ledReadFailed = False
                    log("LM75A led(0x4F) read recovered.")
            except OSError as e:
                failed = True
                if not self._ledReadFailed:
                    self._ledReadFailed = True
                    log("[WARN] LM75A led(0x4F) read failed, keep last value:{}".format(e))

        # 热插拔重连：任一传感器对象为 None 时每 5s 快速扫描总线，
        # 传感器插回后 5s 内自动恢复，无需等待 60s 的总线恢复周期
        if utime.ticks_diff(now, self._lastHotPlugTick) >= _HOTPLUG_INTERVAL_MS:
            self._lastHotPlugTick = now
            if self.pms5003 is None:
                s = self._createPMS5003(quick=True)
                if s is not None:
                    self.pms5003 = s
            if self.bh1750 is None:
                s = self._createBH1750(quick=True)
                if s is not None:
                    self.bh1750 = s
            if self.bmp280 is None:
                s = self._createBMP280(quick=True)
                if s is not None:
                    self.bmp280 = s
            if self.hdc1080 is None:
                s = self._createHDC1080(quick=True)
                if s is not None:
                    self.hdc1080 = s

        # PMS5003 颗粒物（读取失败/校验失败返回 None → 保留上次有效值）
        if self.pms5003 is not None:
            d = self.pms5003.read()
            if d is not None:
                self.__sensorData.updatePMS(d)
                self._lastGoodPmsTick = now
                if self._pmsReadFailed:
                    self._pmsReadFailed = False
                    log("PMS5003 read recovered.")
            else:
                failed = True
                if not self._pmsReadFailed:
                    self._pmsReadFailed = True
                    log("[WARN] PMS5003 read failed, keep last value.")

        # BH1750 光照（读取失败返回 -9999 → 保留上次有效值）
        if self.bh1750 is not None:
            lux = self.bh1750.luminance(bh1750.BH1750.CONT_HIRES_1)
            if lux != -9999:
                self.__sensorData.luminance = lux
                self._lastGoodBh1750Tick = now
                if self._bh1750ReadFailed:
                    self._bh1750ReadFailed = False
                    log("BH1750 read recovered.")
            else:
                failed = True
                if not self._bh1750ReadFailed:
                    self._bh1750ReadFailed = True
                    log("[WARN] BH1750 read failed, keep last value.")

        # BMP280 气压/温度（读取失败返回 -9999 → 保留上次有效值）
        if self.bmp280 is not None:
            t = self.bmp280.getTemp()
            p = self.bmp280.getPress()
            if t != -9999 and p != -9999:
                self.__sensorData.tempBMP280 = t
                self.__sensorData.presure = p
                # 用实测气压更新湿球温度计算器（BMP280 单位 Pa，与 AACOps.p 一致）
                self._aac.set_pressure(p)
                self._lastGoodBmp280Tick = now
                if self._bmp280ReadFailed:
                    self._bmp280ReadFailed = False
                    log("BMP280 read recovered.")
            else:
                failed = True
                if not self._bmp280ReadFailed:
                    self._bmp280ReadFailed = True
                    log("[WARN] BMP280 read failed, keep last value.")

        # HDC1080 温湿度（读取失败返回 -9999 → 保留上次有效值）
        if self.hdc1080 is not None:
            t = self.hdc1080.temperature
            h = self.hdc1080.humidity
            if t != -9999 and h != -9999:
                self.__sensorData.temp = t
                self.__sensorData.humi = h
                # 湿球温度：AACOps.ts(干球温度℃, 相对湿度0~1)，h 为百分比需 /100
                self.__sensorData.wetBulb = self._aac.ts(t, h / 100.0)
                self._lastGoodHdc1080Tick = now
                if self._hdc1080ReadFailed:
                    self._hdc1080ReadFailed = False
                    log("HDC1080 read recovered.")
            else:
                failed = True
                if not self._hdc1080ReadFailed:
                    self._hdc1080ReadFailed = True
                    log("[WARN] HDC1080 read failed, keep last value.")

        self._checkSensorAge(now)

        if failed:
            self._i2cFailCount += 1
            if self._i2cFailCount >= _I2C_MAX_FAIL_COUNT:
                self.recoverI2C(now)
            return
        self._i2cFailCount = 0

        # 任一路传感器缺失（开机未接入/闪断后未恢复）：周期重试扫描，支持热插拔
        if (self.LM75FanTemp is None or self.LM75LedTemp is None or
                self.pms5003 is None or self.bh1750 is None or
                self.bmp280 is None or self.hdc1080 is None) and \
                utime.ticks_diff(now, self._lastRecoverTick) >= _I2C_RECOVER_RETRY_MS:
            self.recoverI2C(now)

    def _checkSensorAge(self, now):
        """数据老化判定：曾读到有效值的传感器若超过 _SENSOR_STALE_MS 无新数据，
        置 -9999（无效值），由 FSM 按故障安全策略处理；状态翻转时只打一条日志。"""
        if self._lastGoodFanTick != 0 and \
                utime.ticks_diff(now, self._lastGoodFanTick) >= _SENSOR_STALE_MS and \
                self.__sensorData.LM75FanTemp != -9999:
            self.__sensorData.LM75FanTemp = -9999
            log("[WARN] LM75A fan(0x4A) data stale >{}s, mark invalid.".format(
                _SENSOR_STALE_MS // 1000))

        if self._lastGoodLedTick != 0 and \
                utime.ticks_diff(now, self._lastGoodLedTick) >= _SENSOR_STALE_MS and \
                self.__sensorData.LM75LedTemp != -9999:
            self.__sensorData.LM75LedTemp = -9999
            log("[WARN] LM75A led(0x4F) data stale >{}s, mark invalid.".format(
                _SENSOR_STALE_MS // 1000))

        if self._lastGoodPmsTick != 0 and \
                utime.ticks_diff(now, self._lastGoodPmsTick) >= _SENSOR_STALE_MS and \
                self.__sensorData.pm2_5 != -9999:
            self.__sensorData.updatePMS({
                "pm1_0_cf": -9999, "pm2_5_cf": -9999, "pm10_cf": -9999,
                "pm1_0": -9999, "pm2_5": -9999, "pm10": -9999,
                "part0_3": -9999, "part0_5": -9999, "part1_0": -9999,
                "part2_5": -9999, "part5_0": -9999, "part10": -9999,
            })
            log("[WARN] PMS5003 data stale >{}s, mark invalid.".format(
                _SENSOR_STALE_MS // 1000))

        if self._lastGoodBh1750Tick != 0 and \
                utime.ticks_diff(now, self._lastGoodBh1750Tick) >= _SENSOR_STALE_MS and \
                self.__sensorData.luminance != -9999:
            self.__sensorData.luminance = -9999
            log("[WARN] BH1750 data stale >{}s, mark invalid.".format(
                _SENSOR_STALE_MS // 1000))

        if self._lastGoodBmp280Tick != 0 and \
                utime.ticks_diff(now, self._lastGoodBmp280Tick) >= _SENSOR_STALE_MS and \
                self.__sensorData.presure != -9999:
            self.__sensorData.tempBMP280 = -9999
            self.__sensorData.presure = -9999
            # BMP280 数据失效，湿球温度计算回退到标准大气压
            self._aac.reset_pressure()
            log("[WARN] BMP280 data stale >{}s, mark invalid.".format(
                _SENSOR_STALE_MS // 1000))

        if self._lastGoodHdc1080Tick != 0 and \
                utime.ticks_diff(now, self._lastGoodHdc1080Tick) >= _SENSOR_STALE_MS and \
                self.__sensorData.temp != -9999:
            self.__sensorData.temp = -9999
            self.__sensorData.humi = -9999
            self.__sensorData.wetBulb = -9999
            log("[WARN] HDC1080 data stale >{}s, mark invalid.".format(
                _SENSOR_STALE_MS // 1000))

    def recoverI2C(self, now=None):
        """重建硬件 I2C 总线并重新绑定所有传感器对象（总线锁死/从机掉线的自愈路径）。
        无条件尝试重建所有传感器（无论之前是否为 None），以支持热插拔恢复：
        即使某路因闪断被置为 None，也要重新扫描总线，传感器恢复后自动重新绑定。"""
        if now is None:
            now = utime.ticks_ms()
        self._lastRecoverTick = now
        self._i2cFailCount = 0
        log("[WARN] I2C bus recovery: re-init hardware I2C.")
        try:
            self.i2c = I2C(0, scl=Pin(self.PIN_SOFT_I2C_SCL),
                           sda=Pin(self.PIN_SOFT_I2C_SDA), freq=100000)
        except Exception as e:
            log("[ERROR] I2C re-init failed:{}".format(e))
            return
        # 无条件重建所有传感器（支持热插拔：即使之前因缺失被置 None，也要重新扫描）
        self.LM75FanTemp = self._createLm75A(0x4A, "fan")
        self.LM75LedTemp = self._createLm75A(0x4F, "led")
        self.pms5003 = self._createPMS5003()
        self.bh1750 = self._createBH1750()
        self.bmp280 = self._createBMP280()
        self.hdc1080 = self._createHDC1080()

    # ===== 死传感器处理函数（预留，硬件未接入，读取逻辑已注释）=====
    # BMP280 气压/温度/海拔
    def bmp280TimerHandler(self):
        # self.__sensorData.presure = self.__bmp280.getPress()
        # self.__sensorData.altitude = self.__bmp280.getAltitude()
        # self.__sensorData.tempBMP280 = self.__bmp280.getTemp()
        pass

    # HDC1080 温湿度
    def hdc1080TimerHandler(self):
        # self.__sensorData.temp = self.__hdc1080.temperature
        # self.__sensorData.humi = self.__hdc1080.humidity
        pass

    # BH1750 光照
    def bh1750TimerHandler(self):
        # self.__sensorData.luminance = self.bh1750.luminance(0x11)
        pass

    # PMS5003 PM2.5（已接入，读取逻辑在 readSensors 中）
    def pms5003TimerHandler(self):
        pass

    def setLEDArray(self, color):
        self.__LEDArray[0] = color
        self.__LEDArray.write()

    def enableLED(self, status):
        if status == 1:
            self.__LED_EN_A.on()
            self.__LED_EN_B.on()
        else:
            self.__LED_EN_A.off()
            self.__LED_EN_B.off()

    def setPwm(self, channelName, freq, minDuty, maxDuty, percent, reverse=False):
        """设置 PWM 占空比。percent 范围 0-1000。"""
        pwm = self._pwmChannels.get(channelName)
        if pwm is None:
            log("Invalid PWM channel: " + channelName)
            return

        p = percent
        if p > 1000:
            p = 1000
        if p < 0:
            p = 0
        if reverse:
            p = 1000 - p

        if p == 0:
            duty = 0
        else:
            base = (minDuty / 100.0) * 1023
            full = (maxDuty - minDuty) / 100.0 * 1023
            duty = full * (p / 1000.0) + base
            if duty > 1023:
                duty = 1023

        # 仅在频率变化时设置，避免 PWM 输出毛刺
        newFreq = int(freq)
        if self._pwmFreq.get(channelName) != newFreq:
            pwm.freq(newFreq)
            self._pwmFreq[channelName] = newFreq
        pwm.duty(int(duty))

        if channelName == "fanPwm":
            self.__fanSpeed = percent / 10.0
        elif channelName == "pumpPwm":
            self.__pumpSpeed = percent / 10.0

    def getknob(self):
        return self.knob, self.knobKey.value()

    def getLightStatus(self):
        return self.__lightStatus

    def setLightStatus(self, status):
        self.__lightStatus = status

    def getSensorData(self):
        return self.__sensorData

    def getFanSpeed(self):
        return self.__fanSpeed

    def getPumpSpeed(self):
        return self.__pumpSpeed

    @classmethod
    def getInstance(cls):
        if cls.__instance is None:
            cls.__instance = BSP()
        return cls.__instance


bspInstance = BSP()
