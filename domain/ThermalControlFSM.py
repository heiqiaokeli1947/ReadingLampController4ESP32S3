"""温控 FSM 基类：EMA 滤波 + 滞回带 + 渐变限速。

FanFSM（二级散热，关灯即停）和 PumpFSM（一级散热，关灯后继续降温）
继承此类，仅在以下维度有差异：
  - 温度数据源（LM75FanTemp / LM75LedTemp）
  - 阈值配置键（fanHThreshold/fanLThreshold / LEDHThreshold/LEDLThreshold）
  - PWM 通道名（fanPwm / pumpPwm）与配置前缀（fanPwm* / pumpPwm*）
  - 停机条件（关灯即停 / 仅看温度）
  - 累计运行时长 DB 键（fanTotalRunTime / pumpTotalRunTime）

提取基类消除两个 FSM 间 95% 的重复代码，改一处自动同步另一处。"""

import utime
import domain.DBUtils as db
from domain.LogUtils import log


class STATUS:
    INIT = 0
    EVAL = 1  # 评估+调速：每 tick 检查温度并按限速调整 PWM


# 控制算法参数（FanFSM 与 PumpFSM 共享同值）
TEMP_FILTER_ALPHA = 0.25      # 温度 EMA 滤波系数（越小越平滑，0.25≈4 次采样达到稳态）
TEMP_HYSTERESIS = 1.5         # 启停滞回带（°C），消除临界点反复启停震荡
SPEED_RATE_LIMIT = 25.0       # 转速渐变限速（%/秒），平滑 PWM 过渡、避免电流冲击


class ThermalControlFSM:
    """温控 FSM 基类。子类通过 __init__ 的 params dict 注入差异点。"""

    def __init__(self, bspInstance, config, params):
        """params 字段：
        - name: 日志标签（'Fan' / 'Pump'）
        - temp_getter: 无参函数，返回当前温度（sensorData 对应属性）
        - h_key: 高温阈值配置键名
        - l_key: 低温阈值配置键名
        - pwm_ch: PWM 通道名（'fanPwm' / 'pumpPwm'）
        - pwm_prefix: PWM 配置键前缀（'fanPwm' / 'pumpPwm'）
        - stop_when_light_off: bool，关灯是否立即停转
        - run_time_db_key: 累计运行时长 DB 键名
        """
        self.bspInstance = bspInstance
        self.config = config
        self._p = params
        self.status = STATUS.INIT

        self.lastRunTick = utime.ticks_ms()
        self.lastLogTick = 0
        self.lastSaveTick = 0
        self.runTimeCounterMs = 0
        self.totalRunTimeMs = 0
        self.deviceTotalRunTimeMs = 0

        saved = db.get(params["run_time_db_key"])
        self.deviceTotalRunTimeMs = int(saved) * 1000 if saved is not None else 0
        if saved is None:
            db.save({params["run_time_db_key"]: "0"})

        self.targetSpeed = 0          # 温度映射得到的目标转速（0~100）
        self.appliedSpeed = 0         # 实际 PWM 输出转速（限速后）
        self.lastPwmSpeed = -1        # 上次写入 PWM 的转速（-1 强制首次写入）
        self.rawTemp = -9999          # 传感器原始读数
        self.filteredTemp = -9999     # EMA 滤波后的温度（用于控制决策）
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
        p = self._p
        return {
            p["run_time_db_key"]: int(self.deviceTotalRunTimeMs / 1000),
            p["h_key"]: self.config.get(p["h_key"]),
            p["l_key"]: self.config.get(p["l_key"]),
            p["speed_key"]: self.appliedSpeed,
            p["temp_key"]: self.filteredTemp,
        }

    def saveData(self):
        currentSec = int(self.deviceTotalRunTimeMs / 1000)
        if currentSec != self._lastSavedRunSec:
            db.save({self._p["run_time_db_key"]: str(currentSec)})
            self._lastSavedRunSec = currentSec

    def close(self):
        log("{}FSM: close".format(self._p["name"]))
        self.setDeviceToReadyStatus()
        self.saveData()

    def evaluate(self):
        """评估温度与灯光状态，计算目标转速并按限速调整 PWM。"""
        # 关灯即停（风扇噪音敏感）；水泵不判断灯光状态，关灯后余热仍需循环
        if self._p["stop_when_light_off"] and not self.bspInstance.getLightStatus():
            self.setDeviceToReadyStatus()
            return

        h = self.config.get(self._p["h_key"], 40)
        l = self.config.get(self._p["l_key"], 30)

        if self.filteredTemp == -9999:
            # 传感器异常：开灯时全速保护，关灯时不空转（仅水泵走此分支，风扇已在上面 return）
            self.targetSpeed = 100 if self.bspInstance.getLightStatus() else 0
        elif self.filteredTemp >= h:
            self.targetSpeed = 100
        elif self.filteredTemp <= l - TEMP_HYSTERESIS:
            self.targetSpeed = 0
        elif self.filteredTemp >= l + TEMP_HYSTERESIS:
            denom = h - l
            if denom <= 0:
                self.targetSpeed = 100
            else:
                self.targetSpeed = round(100 * (self.filteredTemp - l) / denom, 1)
        # else: 滞回带内，保持 targetSpeed 不变

        self.applySpeedLimit()

    def applySpeedLimit(self):
        """渐变限速：逐步逼近目标转速，避免 PWM 突变引起电流冲击。"""
        elapsed = utime.ticks_diff(self.runTimeCounterMs, self.lastSpeedAdjustMs)
        self.lastSpeedAdjustMs = self.runTimeCounterMs
        # 主循环阻塞（GC/WiFi 重连/配置重载）会导致 elapsed 异常增大，
        # 使 appliedSpeed 直接跳变到 targetSpeed。FSM 正常 1Hz，钳制到 1.5s
        # 保证单 tick 变化不超过 37.5%，避免 PWM 突变。
        if elapsed > 1500:
            elapsed = 1500

        maxChange = SPEED_RATE_LIMIT * elapsed / 1000.0
        diff = self.targetSpeed - self.appliedSpeed
        if abs(diff) > maxChange:
            self.appliedSpeed += maxChange * (1 if diff > 0 else -1)
        else:
            self.appliedSpeed = self.targetSpeed

        # 完全停转时重置限速计时基准，确保下次启动从小步长开始平滑爬升
        if self.targetSpeed == 0 and self.appliedSpeed == 0:
            self.lastSpeedAdjustMs = self.runTimeCounterMs

        p = self._p
        if self._configDirty or self.lastPwmSpeed != self.appliedSpeed:
            self.bspInstance.setPwm(
                p["pwm_ch"],
                self.config.get(p["pwm_prefix"] + "Freq", 25000),
                self.config.get(p["pwm_prefix"] + "Min", 15),
                self.config.get(p["pwm_prefix"] + "Max", 100),
                self.appliedSpeed * 10)
            self.lastPwmSpeed = self.appliedSpeed
            self._configDirty = False

    def readSensor(self):
        """读取温度并做 EMA 滤波。"""
        raw = self._p["temp_getter"]()
        self.rawTemp = raw
        if raw == -9999:
            self.filteredTemp = -9999
        elif self.filteredTemp == -9999:
            self.filteredTemp = raw
        else:
            self.filteredTemp = self.filteredTemp * (1 - TEMP_FILTER_ALPHA) + raw * TEMP_FILTER_ALPHA

    def setDeviceToReadyStatus(self):
        """停机归零。仅在必要时（配置变更或上次不是 0）写 PWM，避免重复写占空比。"""
        self.targetSpeed = 0
        self.appliedSpeed = 0
        self.lastSpeedAdjustMs = self.runTimeCounterMs
        p = self._p
        if self._configDirty or self.lastPwmSpeed != 0:
            self.bspInstance.setPwm(
                p["pwm_ch"],
                self.config.get(p["pwm_prefix"] + "Freq", 25000),
                self.config.get(p["pwm_prefix"] + "Min", 15),
                self.config.get(p["pwm_prefix"] + "Max", 100), 0)
            self.lastPwmSpeed = 0
        self._configDirty = False

    def initDevice(self):
        log("[WARN] {}FSM: init.".format(self._p["name"]))
        self.setDeviceToReadyStatus()
        self.status = STATUS.EVAL

    def run(self):
        now = utime.ticks_ms()
        delta = utime.ticks_diff(now, self.lastRunTick)
        self.lastRunTick = now
        self.runTimeCounterMs += delta
        self.totalRunTimeMs += delta

        if self.appliedSpeed > 0:
            self.deviceTotalRunTimeMs += delta

        self.readSensor()

        if utime.ticks_diff(now, self.lastLogTick) >= 1000:
            self.lastLogTick = now
            p = self._p
            log("[{}] {} FSM: temp(raw/filter)={}/{}, TH={}, TL={}, "
                "target={}%, applied={}%".format(
                    int(self.totalRunTimeMs / 1000), p["name"],
                    self.rawTemp, self.filteredTemp,
                    self.config.get(p["h_key"]), self.config.get(p["l_key"]),
                    self.targetSpeed, self.appliedSpeed))

        if utime.ticks_diff(now, self.lastSaveTick) >= 60000:
            self.lastSaveTick = now
            self.saveData()

        func = self.switch.get(self.status, lambda: log("{} FSM: unknown status".format(self._p["name"])))
        return func()
