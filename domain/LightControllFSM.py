import utime
import domain.DBUtils as db
from domain.LogUtils import log


class STATUS:
    INIT = 0
    READY = 1
    SYS_ENABLED = 2
    FIT_POWER = 3


class FSM:
    """灯光控制状态机：旋钮调节亮度/色温，功率校准表线性插值，平滑调光"""

    # 调光渐变：全量程（0→100%）耗时（毫秒）。步长按时间计算，与主循环频率解耦
    FADE_TIME_MS = 2000

    def __init__(self, bspInstance, config):
        self.bspInstance = bspInstance
        self.config = config
        self.status = STATUS.INIT

        # 计时改用 ticks_ms 单调时钟，运行时长按毫秒累加
        self.lastRunTick = utime.ticks_ms()
        self.lastLogTick = 0
        self.lastSaveTick = 0
        self._lastSavedLedSec = 0  # LED 累计点亮时长持久化节流（秒），避免频繁写 flash
        self.runTimeCounterMs = 0
        # LED 累计点亮时长（跨开机持久化到 DB ledTotalRunTime）
        self.totalRunTimeMs = 0
        saved_led = db.get("ledTotalRunTime")
        if saved_led is not None:
            self.totalRunTimeMs = int(saved_led) * 1000
        else:
            db.save({"ledTotalRunTime": "0"})
        # LED 本次上电点亮时长（运行时，开机从 0 开始）
        self.ledRunTimeMs = 0

        self.onOffStatus = False
        self._offApplied = False  # 关灯状态已应用标记，避免每 tick 重复设置 PWM=0

        # 延迟关灯：记录开灯时刻，到时自动关灯；_delayedOffPending 表示用户已点关灯正在倒计时
        self._onSinceMs = 0
        self._delayedOffPending = False
        self._lastDelayedOff = self.config.get("delayedOff", 0)

        # 视疲劳提醒：连续开灯时长 + 脉冲状态
        self._continuousOnMs = 0
        self._eyeRemindActive = False
        self._eyeRemindStartMs = 0

        knob, knobKey = self.bspInstance.getknob()
        self.lastKnobValue = knob.value()
        self.lastKnobKey = knobKey

        # 从 DB 恢复色温，默认 50
        saved = db.get("colorTemperature")
        self.colorTemperature = int(saved) if saved is not None else 50
        if saved is None:
            db.save({"colorTemperature": str(self.colorTemperature)})
        self.lastColorTemperature = self.colorTemperature

        self.brightness = 0
        self.lastBrightness = 0
        # 从 DB 恢复上次关灯前的亮度（开灯时作为默认值，亮度为 0 时仍走 30 的兜底）
        saved_b = db.get("brightness")
        if saved_b is not None:
            self.brightness = int(saved_b)
            self.lastBrightness = self.brightness
        else:
            db.save({"brightness": str(self.brightness)})
        self.yellowBrightness = 0
        self.whiteBrightness = 0
        self.yellowBrightnessTemp = 0
        self.whiteBrightnessTemp = 0
        self.lastFitMs = 0
        self._configDirty = False  # reloadConfig 后置 True，fitPower 强制重应用 PWM

        # 功率校准表：[亮度百分比, 对应电流]
        self.YELLOW_CALC_TABLE = [
            [1, 3], [2, 4], [3, 5], [4, 6], [5, 8], [8, 13], [13, 26], [20, 50],
            [27, 80], [36, 129], [45, 187], [55, 261], [64, 336], [73, 418],
            [80, 486], [87, 558], [92, 611], [95, 684], [96, 818], [97, 965],
            [98, 1137], [99, 1329], [100, 1623]]
        self.WHITE_CALC_TABLE = [
            [1, 3], [2, 4], [3, 5], [4, 6], [5, 8], [8, 13], [13, 26], [20, 50],
            [27, 82], [36, 132], [45, 191], [55, 268], [64, 344], [73, 428],
            [80, 498], [87, 571], [92, 630], [95, 731], [96, 884], [97, 1057],
            [98, 1254], [99, 1476], [100, 1815]]

    def reloadConfig(self, config):
        self.config = config
        self._configDirty = True

    def calibratePower(self, duty, calibrateTable):
        if duty <= 0:
            return 0
        if duty >= 100:
            return 100
        head = calibrateTable[0]
        tail = calibrateTable[-1]
        fullCurrent = tail[1] - head[1]
        targetCurrent = head[1] + duty / 100 * fullCurrent
        for i in range(len(calibrateTable) - 1):
            if targetCurrent == calibrateTable[i][1]:
                return calibrateTable[i][0]
            elif calibrateTable[i][1] < targetCurrent <= calibrateTable[i + 1][1]:
                pwmRange = calibrateTable[i + 1][0] - calibrateTable[i][0]
                pwmBase = calibrateTable[i][0]
                percent = (targetCurrent - calibrateTable[i][1]) / (
                    calibrateTable[i + 1][1] - calibrateTable[i][1])
                return pwmBase + pwmRange * percent
        return 0

    def getStatus(self):
        return {
            "onOffStatus": self.onOffStatus,
            "brightness": self.brightness,
            "colorTemperature": self.colorTemperature,
            "yellowBrightness": self.yellowBrightness,
            "whiteBrightness": self.whiteBrightness,
            # 渐变后的实际亮度（PWM 当前输出），用于确认调光是否真的落到硬件
            "yellowApplied": round(self.yellowBrightnessTemp, 1),
            "whiteApplied": round(self.whiteBrightnessTemp, 1),
            "ledTotalRunTime": int(self.totalRunTimeMs / 1000),
            "ledRunTime": int(self.ledRunTimeMs / 1000),
            "eyeRemindActive": self._eyeRemindActive,
            "delayedOffPending": self._delayedOffPending,
        }

    def saveData(self):
        if self.lastColorTemperature != self.colorTemperature:
            log("save colorTemperature: {}".format(self.colorTemperature))
            db.save({"colorTemperature": str(self.colorTemperature)})
            self.lastColorTemperature = self.colorTemperature
        if self.lastBrightness != self.brightness:
            log("save brightness: {}".format(self.brightness))
            db.save({"brightness": str(self.brightness)})
            self.lastBrightness = self.brightness
        # LED 累计点亮时长持久化（每 60 秒落盘一次，降低 flash 磨损；关机前由主循环再兜底保存）
        ledSec = int(self.totalRunTimeMs / 1000)
        if ledSec - self._lastSavedLedSec >= 60:
            db.save({"ledTotalRunTime": str(ledSec)})
            self._lastSavedLedSec = ledSec

    # ---------- Web 控制接口 ----------
    # 标量赋值在 MicroPython GIL 下原子，主循环 fitPower 每 tick 读取，无需额外锁。
    # 设置后由主循环下一轮 fitPower 平滑应用（powerFitStep 渐变）。

    def setOnOff(self, on, auto=False):
        """开关灯：on 为真时开灯，否则关灯。开灯时若亮度为 0 则自动置 30。
        关灯时清零渐变中间值，与旋钮按键关灯保持一致：fitPower 关灯分支会把
        PWM 写成 0，若中间值保留原亮度，重新开灯时"中间值==目标值"不会重写
        PWM，灯将点不亮。
        auto=True 表示由延迟关灯倒计时自动触发，实际执行关灯；
        auto=False（默认）为用户手动关灯，若 delayedOff 开启则转为重新开始倒计时。"""
        self.onOffStatus = bool(on)
        if self.onOffStatus:
            if self.brightness <= 0:
                self.brightness = 30
            self._onSinceMs = self.runTimeCounterMs
            self._delayedOffPending = False
            # 延迟关灯开启时，连续开灯计时从开灯时刻重新算
            self._eyeRemindActive = False
        else:
            # 延迟关灯开启 + 用户手动关灯 → 不立即关灯，重置倒计时到时再关
            if not auto and self.config.get("delayedOff", 0):
                self._onSinceMs = self.runTimeCounterMs
                self._delayedOffPending = True
                self.onOffStatus = True  # 保持开灯状态
                return
            self.yellowBrightnessTemp = 0
            self.whiteBrightnessTemp = 0
            self._continuousOnMs = 0
            self._eyeRemindActive = False
            self._delayedOffPending = False
            # 真实关灯时立即落盘 LED 累计点亮时长，避免掉电丢失最后一段点亮时间
            ledSec = int(self.totalRunTimeMs / 1000)
            db.save({"ledTotalRunTime": str(ledSec)})
            self._lastSavedLedSec = ledSec
        self._recalcBrightness()
        self.bspInstance.setLightStatus(self.onOffStatus)

    def setBrightness(self, value):
        """设置亮度 0~100，关灯时自动开灯；亮度 0 时关灯。变更后立即持久化。"""
        v = int(max(0, min(100, value)))
        self.brightness = v
        if v == 0:
            # 亮度为 0 等同于关灯：走 setOnOff(auto=True) 完整关灯逻辑，
            # 确保 _continuousOnMs/_eyeRemindActive 清零、ledTotalRunTime 落盘、
            # 临时亮度清零，与旋钮/Web 关灯行为一致。auto=True 绕过延迟关灯倒计时。
            self.setOnOff(False, auto=True)
        else:
            wasOff = not self.onOffStatus
            if not self.onOffStatus:
                self.onOffStatus = True
                self.bspInstance.setLightStatus(True)
            if wasOff or self._delayedOffPending:
                # 开灯或取消延迟关灯倒计时：重新开始倒计时并清理状态
                self._onSinceMs = self.runTimeCounterMs
                self._eyeRemindActive = False
                self._delayedOffPending = False
            self._recalcBrightness()
        if self.lastBrightness != v:
            db.save({"brightness": str(v)})
            self.lastBrightness = v

    def setColorTemperature(self, value):
        """设置色温 0~100（0=全暖黄，100=全冷白），并持久化。"""
        v = int(max(0, min(100, value)))
        self.colorTemperature = v
        self._recalcBrightness()
        # 持久化色温
        if self.lastColorTemperature != v:
            db.save({"colorTemperature": str(v)})
            self.lastColorTemperature = v

    def _recalcBrightness(self):
        """根据 brightness 和 colorTemperature 重算黄/白通道亮度"""
        self.yellowBrightness = self.brightness * (100 - self.colorTemperature) / 100
        self.whiteBrightness = self.brightness * self.colorTemperature / 100

    def close(self):
        log("LightControlFSM: close")
        self.setDeviceToReadyStatus()
        self.saveData()

    def checkSystemEnableStatus(self):
        # 台灯系统始终使能（无物理开关），直接进入旋钮处理
        self.status = STATUS.SYS_ENABLED

    def processKnob(self):
        knob, knobKey = self.bspInstance.getknob()

        if self.lastKnobValue != knob.value() and not knobKey and self.onOffStatus:
            # 按住旋钮旋转 → 色温调节
            delt = knob.value() - self.lastKnobValue
            self.colorTemperature = max(0, min(100, self.colorTemperature + delt * 2))
            self._recalcBrightness()
            self.lastKnobValue = knob.value()
            self.lastKnobKey = knobKey

        elif self.lastKnobValue != knob.value() and knobKey and self.onOffStatus:
            # 不按旋钮旋转 → 亮度调节
            delt = knob.value() - self.lastKnobValue
            self.brightness = max(0, min(100, self.brightness + delt * 2))
            self._recalcBrightness()
            self.lastKnobValue = knob.value()
            self.lastKnobKey = knobKey

        elif self.lastKnobKey != knobKey and not knobKey:
            # 按键按下（下降沿）→ 开关灯（走 setOnOff 以保持延迟关灯逻辑一致）
            self.lastKnobValue = knob.value()
            self.setOnOff(not self.onOffStatus)
            self.lastKnobKey = False

        elif not self.lastKnobKey and knobKey:
            self.lastKnobKey = True

        elif self.lastKnobValue != knob.value():
            # 关灯时旋转没有调节目标，只同步基准值；否则基准停留在关灯前，
            # 开灯后第一次旋转会按累积差值（可能几十格）瞬间跳变
            self.lastKnobValue = knob.value()
            self.lastKnobKey = knobKey

        self.status = STATUS.FIT_POWER

    def fitPower(self):
        # 按时间计算本次步长：与主循环频率解耦，全量程（0→100%）固定 FADE_TIME_MS
        elapsed = utime.ticks_diff(self.runTimeCounterMs, self.lastFitMs)
        self.lastFitMs = self.runTimeCounterMs
        if elapsed <= 0:
            elapsed = 1
        step = 100.0 * elapsed / self.FADE_TIME_MS

        if not self.onOffStatus:
            if not self._offApplied:
                self.bspInstance.enableLED(0)
                self.bspInstance.setPwm("yellowPwm", self.config["yellowPwmFreq"],
                                        self.config["yellowPwmMin"], self.config["yellowPwmMax"], 0)
                self.bspInstance.setPwm("whitePwm", self.config["whitePwmFreq"],
                                        self.config["whitePwmMin"], self.config["whitePwmMax"], 0)
                self._offApplied = True
        else:
            self._offApplied = False
            self.bspInstance.enableLED(1)

            # 视疲劳提醒：10s 内 4 个周期三角波，亮度在当前值的 10%~100% 间振荡
            # 提醒期间直接设置 PWM 目标（绕过 2s 渐变），否则脉冲幅度被渐变压缩几乎不可见
            yellowTarget = self.yellowBrightness
            whiteTarget = self.whiteBrightness
            if self._eyeRemindActive:
                elapsed = self.runTimeCounterMs - self._eyeRemindStartMs
                cycle = elapsed % 2500  # 每周期 2.5s
                pos = cycle / 2500.0
                if pos < 0.5:
                    factor = 1.0 - 1.8 * pos       # 1.0 → 0.1
                else:
                    factor = 0.1 + 1.8 * (pos - 0.5)  # 0.1 → 1.0
                yellowTarget = self.yellowBrightness * factor
                whiteTarget = self.whiteBrightness * factor
                # 直接跟随三角波，不经过 FADE_TIME_MS 渐变
                self.yellowBrightnessTemp = yellowTarget
                self.whiteBrightnessTemp = whiteTarget
                yellowCal = self.calibratePower(self.yellowBrightnessTemp, self.YELLOW_CALC_TABLE)
                self.bspInstance.setPwm("yellowPwm", self.config["yellowPwmFreq"],
                                        self.config["yellowPwmMin"], self.config["yellowPwmMax"], yellowCal * 10)
                whiteCal = self.calibratePower(self.whiteBrightnessTemp, self.WHITE_CALC_TABLE)
                self.bspInstance.setPwm("whitePwm", self.config["whitePwmFreq"],
                                        self.config["whitePwmMin"], self.config["whitePwmMax"], whiteCal * 10)
                self._configDirty = False
            else:
                if self._configDirty or self.yellowBrightnessTemp != yellowTarget:
                    diff = self.yellowBrightnessTemp - yellowTarget
                    if diff > step:
                        self.yellowBrightnessTemp -= step
                    elif diff < -step:
                        self.yellowBrightnessTemp += step
                    else:
                        self.yellowBrightnessTemp = yellowTarget
                    yellowCal = self.calibratePower(self.yellowBrightnessTemp, self.YELLOW_CALC_TABLE)
                    self.bspInstance.setPwm("yellowPwm", self.config["yellowPwmFreq"],
                                            self.config["yellowPwmMin"], self.config["yellowPwmMax"], yellowCal * 10)

                if self._configDirty or self.whiteBrightnessTemp != whiteTarget:
                    diff = self.whiteBrightnessTemp - whiteTarget
                    if diff > step:
                        self.whiteBrightnessTemp -= step
                    elif diff < -step:
                        self.whiteBrightnessTemp += step
                    else:
                        self.whiteBrightnessTemp = whiteTarget
                    whiteCal = self.calibratePower(self.whiteBrightnessTemp, self.WHITE_CALC_TABLE)
                    self.bspInstance.setPwm("whitePwm", self.config["whitePwmFreq"],
                                            self.config["whitePwmMin"], self.config["whitePwmMax"], whiteCal * 10)
                self._configDirty = False

        self.status = STATUS.READY

    def setDeviceToReadyStatus(self):
        self.bspInstance.enableLED(0)
        for ch in ("fanPwm", "pumpPwm", "yellowPwm", "whitePwm"):
            self.bspInstance.setPwm(ch, self.config.get(ch + "Freq", 25000),
                                    self.config.get(ch + "Min", 15),
                                    self.config.get(ch + "Max", 100), 0)

    def initDevice(self):
        log("[WARN] LightControlFSM: init device.")
        self.setDeviceToReadyStatus()
        self.status = STATUS.READY

    def run(self):
        now = utime.ticks_ms()
        delta = utime.ticks_diff(now, self.lastRunTick)
        self.lastRunTick = now
        self.runTimeCounterMs += delta
        if self.onOffStatus:
            self.totalRunTimeMs += delta
            self.ledRunTimeMs += delta
            self._continuousOnMs += delta

            # 延迟关灯：开启后到点自动关灯
            delayed = self.config.get("delayedOff", 0)
            # delayedOff 由关→开时，若灯已亮，重置开灯时刻，避免历史已亮时长立即触发自动关灯。
            # 注意：self.config 与 systemConfig 是同一 dict，Web 线程改值后主循环 run()
            # 会立即看到新值，因此必须在 run() 内检测跳变，不能只依赖 reloadConfig。
            if delayed and not self._lastDelayedOff:
                if self.onOffStatus:
                    self._onSinceMs = self.runTimeCounterMs
                self._delayedOffPending = False
            elif not delayed and self._lastDelayedOff:
                # 关闭延迟关灯时，取消可能存在的倒计时状态
                self._delayedOffPending = False
            self._lastDelayedOff = delayed
            if delayed and self._onSinceMs > 0:
                onMs = self.runTimeCounterMs - self._onSinceMs
                delayMs = self.config.get("delayedOffTime", 60) * 1000
                if onMs >= delayMs:
                    log("delayed off triggered after {}s".format(onMs // 1000))
                    self.setOnOff(False, auto=True)

            # 视疲劳提醒：连续开灯超过间隔后触发 10s 脉冲
            interval = self.config.get("eyeRemindInterval", 0)
            if interval > 0 and not self._eyeRemindActive:
                if self._continuousOnMs >= interval * 60 * 1000:
                    log("eye fatigue reminder triggered")
                    self._eyeRemindActive = True
                    self._eyeRemindStartMs = self.runTimeCounterMs
            # 脉冲持续 10s 后结束，重置连续开灯计时以便下个周期再次触发
            if self._eyeRemindActive:
                if self.runTimeCounterMs - self._eyeRemindStartMs >= 10000:
                    self._eyeRemindActive = False
                    self._continuousOnMs = 0

        # 状态日志节流 1Hz
        if utime.ticks_diff(now, self.lastLogTick) >= 1000:
            self.lastLogTick = now
            log("[{}] Light FSM: On={}, brightness={}%, colorTemp={}%, "
                "yellow={}, white={}, fanTemp={}, LEDTemp={}".format(
                    int(self.totalRunTimeMs / 1000), self.onOffStatus,
                    self.brightness, self.colorTemperature,
                    self.yellowBrightness, self.whiteBrightness,
                    self.bspInstance.getSensorData().LM75FanTemp,
                    self.bspInstance.getSensorData().LM75LedTemp))

        # 持久化节流 10s
        if utime.ticks_diff(now, self.lastSaveTick) >= 10000:
            self.lastSaveTick = now
            self.saveData()

        if self.status == STATUS.INIT:
            return self.initDevice()

        # 每 tick 依次执行：系统使能 → 旋钮采样 → 渐变输出。
        # 早期版本用 READY→SYS_ENABLED→processKnob→FIT_POWER 四态轮转，
        # 每 3 个 tick 才真正调光一次，实测渐变速率只有设计值的 1/3
        # （0.66%/s 而非 2%/s）。这三个环节都无副作用，全部每 tick 执行。
        self.checkSystemEnableStatus()
        self.processKnob()
        self.fitPower()
