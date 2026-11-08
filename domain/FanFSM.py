import utime
import domain.DBUtils as db
from domain.LogUtils import log


class STATUS:
    INIT = 0
    EVAL = 1  # 评估+调速：每 tick 检查温度并按限速调整 PWM


# ===== 控制算法参数 =====
TEMP_FILTER_ALPHA = 0.25      # 温度 EMA 滤波系数（越小越平滑，0.25≈4 次采样达到稳态）
TEMP_HYSTERESIS = 1.5         # 启停滞回带（°C），消除临界点反复启停震荡
SPEED_RATE_LIMIT = 25.0       # 转速渐变限速（%/秒），平滑 PWM 过渡、避免电流冲击


class FSM:
    """风扇控制状态机：EMA 滤波 + 滞回带 + 渐变限速，实现平滑散热。
    传感器：LM75A 0x4A（水冷散热器出水口侧温度，即被动放热后的冷却液温度）。
    风扇属二级散热：只有散热器被动放热不足、出水口温度超阈值时才启动。
    关灯后立即停转（风扇噪音大），余热由水泵单独循环处理。"""

    def __init__(self, bspInstance, config):
        self.bspInstance = bspInstance
        self.config = config
        self.status = STATUS.INIT

        self.lastRunTick = utime.ticks_ms()
        self.lastLogTick = 0
        self.lastSaveTick = 0
        self.runTimeCounterMs = 0
        self.totalRunTimeMs = 0
        self.fanTotalRunTimeMs = 0

        saved = db.get("fanTotalRunTime")
        self.fanTotalRunTimeMs = int(saved) * 1000 if saved is not None else 0
        if saved is None:
            db.save({"fanTotalRunTime": "0"})

        self.targetSpeed = 0          # 温度映射得到的目标转速（0~100）
        self.appliedSpeed = 0         # 实际 PWM 输出转速（限速后）
        self.lastPwmSpeed = -1        # 上次写入 PWM 的转速（-1 强制首次写入）
        self.rawFanTemp = -9999       # 传感器原始读数
        self.filteredFanTemp = -9999  # EMA 滤波后的温度（用于控制决策）
        self.lastSpeedAdjustMs = 0    # 上次调速时间戳（限速计时基准）
        self._lastSavedRunSec = -1
        self._configDirty = False

        self.switch = {
            STATUS.INIT: self.initDevice,
            STATUS.EVAL: self.evaluate,
        }

    def reloadConfig(self, config):
        self.config = config
        self._configDirty = True

    def getStatus(self):
        return {
            "fanTotalRunTime": int(self.fanTotalRunTimeMs / 1000),
            "fanHThreshold": self.config.get("fanHThreshold"),
            "fanLThreshold": self.config.get("fanLThreshold"),
            "fanSpeed": self.appliedSpeed,
            "fanTemp": self.filteredFanTemp,
        }

    def saveData(self):
        currentSec = int(self.fanTotalRunTimeMs / 1000)
        if currentSec != self._lastSavedRunSec:
            db.save({"fanTotalRunTime": str(currentSec)})
            self._lastSavedRunSec = currentSec

    def close(self):
        log("FanFSM: close")
        self.setDeviceToReadyStatus()
        self.saveData()

    def evaluate(self):
        """评估灯光状态与散热器出水口温度，计算目标转速并按限速调整 PWM。
        关灯即停：风扇噪音敏感，余热交给水泵循环。"""
        if not self.bspInstance.getLightStatus():
            self.setDeviceToReadyStatus()
            return

        fanH = self.config.get("fanHThreshold", 40)
        fanL = self.config.get("fanLThreshold", 30)

        if self.filteredFanTemp == -9999:
            self.targetSpeed = 100
        elif self.filteredFanTemp >= fanH:
            self.targetSpeed = 100
        elif self.filteredFanTemp <= fanL - TEMP_HYSTERESIS:
            self.targetSpeed = 0
        elif self.filteredFanTemp >= fanL + TEMP_HYSTERESIS:
            denom = fanH - fanL
            if denom <= 0:
                self.targetSpeed = 100
            else:
                self.targetSpeed = round(100 * (self.filteredFanTemp - fanL) / denom, 1)
        # else: 滞回带内，保持 targetSpeed 不变

        self.applySpeedLimit()

    def applySpeedLimit(self):
        """渐变限速：逐步逼近目标转速，避免 PWM 突变引起电流冲击。"""
        elapsed = utime.ticks_diff(self.runTimeCounterMs, self.lastSpeedAdjustMs)
        self.lastSpeedAdjustMs = self.runTimeCounterMs
        # 主循环阻塞（GC/WiFi 重连/配置重载）会导致 elapsed 异常增大，
        # 使 appliedSpeed 直接跳变到 targetSpeed。FSM 正常 1Hz，钳制到 1.5s
        # 保证单 tick 变化不超过 37.5%，避免水泵/风扇 PWM 突变。
        if elapsed > 1500:
            elapsed = 1500

        # 时间基限速：每秒最多变化 SPEED_RATE_LIMIT %
        maxChange = SPEED_RATE_LIMIT * elapsed / 1000.0
        diff = self.targetSpeed - self.appliedSpeed
        if abs(diff) > maxChange:
            self.appliedSpeed += maxChange * (1 if diff > 0 else -1)
        else:
            self.appliedSpeed = self.targetSpeed

        if self._configDirty or self.lastPwmSpeed != self.appliedSpeed:
            self.bspInstance.setPwm("fanPwm", self.config.get("fanPwmFreq", 25000),
                                    self.config.get("fanPwmMin", 15), self.config.get("fanPwmMax", 100),
                                    self.appliedSpeed * 10)
            self.lastPwmSpeed = self.appliedSpeed
            self._configDirty = False

    def readSensor(self):
        """读取散热器出水口温度并做 EMA 滤波。"""
        raw = self.bspInstance.getSensorData().LM75FanTemp
        self.rawFanTemp = raw
        if raw == -9999:
            self.filteredFanTemp = -9999
        elif self.filteredFanTemp == -9999:
            self.filteredFanTemp = raw
        else:
            self.filteredFanTemp = self.filteredFanTemp * (1 - TEMP_FILTER_ALPHA) + raw * TEMP_FILTER_ALPHA

    def setDeviceToReadyStatus(self):
        """停机归零。关灯时本函数每 tick 都会走到，只在必要时（配置变更或
        上次不是 0）写 PWM，避免每秒重复写占空比。"""
        self.targetSpeed = 0
        self.appliedSpeed = 0
        # 更新限速计时基准，确保重新启动时首次渐变从小步长开始（约 1 个 tick）
        self.lastSpeedAdjustMs = self.runTimeCounterMs
        if self._configDirty or self.lastPwmSpeed != 0:
            self.bspInstance.setPwm("fanPwm", self.config.get("fanPwmFreq", 25000),
                                    self.config.get("fanPwmMin", 15), self.config.get("fanPwmMax", 100), 0)
            self.lastPwmSpeed = 0
        self._configDirty = False

    def initDevice(self):
        log("[WARN] FanFSM: init.")
        self.setDeviceToReadyStatus()
        self.status = STATUS.EVAL

    def run(self):
        now = utime.ticks_ms()
        delta = utime.ticks_diff(now, self.lastRunTick)
        self.lastRunTick = now
        self.runTimeCounterMs += delta
        self.totalRunTimeMs += delta

        if self.appliedSpeed > 0:
            self.fanTotalRunTimeMs += delta

        self.readSensor()

        if utime.ticks_diff(now, self.lastLogTick) >= 1000:
            self.lastLogTick = now
            log("[{}] Fan FSM: fanTemp(raw/filter)={}/{}, TH={}, TL={}, "
                "target={}%, applied={}%".format(
                    int(self.totalRunTimeMs / 1000),
                    self.rawFanTemp, self.filteredFanTemp,
                    self.config.get("fanHThreshold"), self.config.get("fanLThreshold"),
                    self.targetSpeed, self.appliedSpeed))

        if utime.ticks_diff(now, self.lastSaveTick) >= 60000:
            self.lastSaveTick = now
            self.saveData()

        func = self.switch.get(self.status, lambda: log("Fan FSM: unknown status"))
        return func()
