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
    """水泵控制状态机：EMA 滤波 + 滞回带 + 渐变限速，实现平滑散热。
    传感器：LM75A 0x4F（灯板温度）。
    水泵串联在灯板与水冷散热器之间，关灯后仍继续循环带走灯板余热，
    直到灯板温度降到 LEDLThreshold 以下才停转（停机完全由温度决定）。"""

    def __init__(self, bspInstance, config):
        self.bspInstance = bspInstance
        self.config = config
        self.status = STATUS.INIT

        self.lastRunTick = utime.ticks_ms()
        self.lastLogTick = 0
        self.lastSaveTick = 0
        self.runTimeCounterMs = 0
        self.totalRunTimeMs = 0
        self.pumpTotalRunTimeMs = 0

        saved = db.get("pumpTotalRunTime")
        self.pumpTotalRunTimeMs = int(saved) * 1000 if saved is not None else 0
        if saved is None:
            db.save({"pumpTotalRunTime": "0"})

        self.targetSpeed = 0          # 温度映射得到的目标转速（0~100）
        self.appliedSpeed = 0         # 实际 PWM 输出转速（限速后）
        self.lastPwmSpeed = -1        # 上次写入 PWM 的转速（-1 强制首次写入）
        self.rawLedTemp = -9999       # 传感器原始读数
        self.filteredLedTemp = -9999  # EMA 滤波后的温度（用于控制决策）
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
            "pumpTotalRunTime": int(self.pumpTotalRunTimeMs / 1000),
            "LEDHThreshold": self.config.get("LEDHThreshold"),
            "LEDLThreshold": self.config.get("LEDLThreshold"),
            "pumpSpeed": self.appliedSpeed,
            "ledTemp": self.filteredLedTemp,
        }

    def saveData(self):
        currentSec = int(self.pumpTotalRunTimeMs / 1000)
        if currentSec != self._lastSavedRunSec:
            db.save({"pumpTotalRunTime": str(currentSec)})
            self._lastSavedRunSec = currentSec

    def close(self):
        log("PumpFSM: close")
        self.setDeviceToReadyStatus()
        self.saveData()

    def evaluate(self):
        """按灯板温度计算目标转速，并按限速平滑调整 PWM。
        不判断灯光开关：关灯后余热仍需水路循环带走，直到温度低于阈值才停。"""
        ledH = self.config.get("LEDHThreshold", 45)
        ledL = self.config.get("LEDLThreshold", 35)

        if self.filteredLedTemp == -9999:
            # 传感器异常：开灯时全速保护，关灯时不空转
            self.targetSpeed = 100 if self.bspInstance.getLightStatus() else 0
        elif self.filteredLedTemp >= ledH:
            self.targetSpeed = 100
        elif self.filteredLedTemp <= ledL - TEMP_HYSTERESIS:
            self.targetSpeed = 0
        elif self.filteredLedTemp >= ledL + TEMP_HYSTERESIS:
            denom = ledH - ledL
            if denom <= 0:
                self.targetSpeed = 100
            else:
                self.targetSpeed = round(100 * (self.filteredLedTemp - ledL) / denom, 1)
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

        # 完全停转时重置限速计时基准，确保下次启动从小步长开始平滑爬升
        # （参考 FanFSM：风扇关灯时每 tick 调 setDeviceToReadyStatus 复位）
        if self.targetSpeed == 0 and self.appliedSpeed == 0:
            self.lastSpeedAdjustMs = self.runTimeCounterMs

        if self._configDirty or self.lastPwmSpeed != self.appliedSpeed:
            self.bspInstance.setPwm("pumpPwm", self.config.get("pumpPwmFreq", 25000),
                                    self.config.get("pumpPwmMin", 15), self.config.get("pumpPwmMax", 100),
                                    self.appliedSpeed * 10)
            self.lastPwmSpeed = self.appliedSpeed
            self._configDirty = False

    def readSensor(self):
        """读取灯板温度并做 EMA 滤波。"""
        raw = self.bspInstance.getSensorData().LM75LedTemp
        self.rawLedTemp = raw
        if raw == -9999:
            self.filteredLedTemp = -9999
        elif self.filteredLedTemp == -9999:
            self.filteredLedTemp = raw
        else:
            self.filteredLedTemp = self.filteredLedTemp * (1 - TEMP_FILTER_ALPHA) + raw * TEMP_FILTER_ALPHA

    def setDeviceToReadyStatus(self):
        """停机归零。仅在必要时（配置变更或上次不是 0）写 PWM，避免重复写占空比。"""
        self.targetSpeed = 0
        self.appliedSpeed = 0
        # 更新限速计时基准，确保重新启动时首次渐变从小步长开始（约 1 个 tick）
        self.lastSpeedAdjustMs = self.runTimeCounterMs
        if self._configDirty or self.lastPwmSpeed != 0:
            self.bspInstance.setPwm("pumpPwm", self.config.get("pumpPwmFreq", 25000),
                                    self.config.get("pumpPwmMin", 15), self.config.get("pumpPwmMax", 100), 0)
            self.lastPwmSpeed = 0
        self._configDirty = False

    def initDevice(self):
        log("[WARN] PumpFSM: init.")
        self.setDeviceToReadyStatus()
        self.status = STATUS.EVAL

    def run(self):
        now = utime.ticks_ms()
        delta = utime.ticks_diff(now, self.lastRunTick)
        self.lastRunTick = now
        self.runTimeCounterMs += delta
        self.totalRunTimeMs += delta

        if self.appliedSpeed > 0:
            self.pumpTotalRunTimeMs += delta

        self.readSensor()

        if utime.ticks_diff(now, self.lastLogTick) >= 1000:
            self.lastLogTick = now
            log("[{}] Pump FSM: ledTemp(raw/filter)={}/{}, TH={}, TL={}, "
                "target={}%, applied={}%".format(
                    int(self.totalRunTimeMs / 1000),
                    self.rawLedTemp, self.filteredLedTemp,
                    self.config.get("LEDHThreshold"), self.config.get("LEDLThreshold"),
                    self.targetSpeed, self.appliedSpeed))

        if utime.ticks_diff(now, self.lastSaveTick) >= 60000:
            self.lastSaveTick = now
            self.saveData()

        func = self.switch.get(self.status, lambda: log("Pump FSM: unknown status"))
        return func()
