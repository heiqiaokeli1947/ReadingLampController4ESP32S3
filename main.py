from domain.LogUtils import log
import machine
from lib.microdot import Microdot, send_file
import domain.wifi as wifi
import domain.fileUtils as fileUtils
import utime, ujson
import driver.bsp as bsp
import domain.LightControllFSM as lightControlFSM
import domain.FanFSM as fanFSM
import domain.PumpFSM as pumpFSM
import domain.DBUtils as db
import domain.ntpSync as ntpSync
import domain.matrix_anim as matrix_anim
import _thread
import gc
import micropython as mp

# 固件：ESP32_GENERIC_S3-SPIRAM_OCT
log("software version:20261108")
log("start begin...")

# 默认系统配置
defaultSystemConfig = {
    "deviceusername": "admin",
    "devicepwd": "pengping",
    "wifiname": "cissco_2g",
    "wifipwd": "13438045703",
    "wifipwdDefault": "13438045703",
    "devicetype": "Micropython",
    "APName": "ReadingLamp",
    "sw2name": "开关B",
    "APNetMask": "255.255.255.0",
    "altitude": 498,
    "wifinameDefault": "ESP32S3",
    "latitude": 30.67831,
    "serverurl": "http://3a892544f7.qicp.vip",
    "APPwd": "19880612",
    "devicename": "ReadingLamp",
    "mode": "normal",
    "sw1name": "开关A",
    "APGateway": "192.168.1.1",
    "APIP": "192.168.4.1",
    "longitude": 104.0375,
    # 风扇 PWM
    "fanPwmFreq": 25000, "fanPwmMin": 15, "fanPwmMax": 100,
    # 水泵 PWM
    "pumpPwmFreq": 25000, "pumpPwmMin": 15, "pumpPwmMax": 100,
    # 暖黄 LED PWM
    "yellowPwmFreq": 25000, "yellowPwmMin": 15, "yellowPwmMax": 100,
    # 冷白 LED PWM
    "whitePwmFreq": 25000, "whitePwmMin": 15, "whitePwmMax": 100,
    # 温度阈值
    "fanHThreshold": 40, "fanLThreshold": 30,
    "LEDHThreshold": 45, "LEDLThreshold": 35,
    # 风扇/水泵调速延迟（秒）
    "fanDelayTime": 5,
    # 延迟关灯：开关(0/1) + 延时秒数(3~300)
    "delayedOff": 0,
    "delayedOffTime": 60,
    # 视疲劳提醒间隔（分钟，0=关闭）
    "eyeRemindInterval": 0,
    # 矩阵显示设置（持久化）
    "matrixAnim": "rainbow",
    "matrixText": "",
    "matrixColor": "#00ff78",
    "matrixBrightness": 1.0,
    "matrixSpeed": 20,
    "ver": "1.0"
}

# 加载配置：默认值与存储值合并，老库缺字段取默认值
systemConfig = db.get("systemConfig")
if systemConfig is not None:
    stored = None
    try:
        stored = ujson.loads(systemConfig)
    except ValueError:
        pass
    if not isinstance(stored, dict):
        log("[ERROR] systemConfig in DB invalid, fallback to defaults.")
        stored = {}
    systemConfig = dict(defaultSystemConfig)
    systemConfig.update(stored)
    # 清理已废弃的配置项（历史 DB 中残留的 key 不应再出现在 status 响应或参与校验）
    for _k in list(systemConfig.keys()):
        if _k not in defaultSystemConfig and _k != "deviceId":
            systemConfig.pop(_k, None)
    log("systemConfig loaded from DB.")
else:
    log("create default systemConfig...")
    db.save({"systemConfig": ujson.dumps(defaultSystemConfig)})
    systemConfig = dict(defaultSystemConfig)

# 初始化设备 UUID
if "deviceId" not in systemConfig or not systemConfig["deviceId"]:
    systemConfig["deviceId"] = machine.unique_id().hex().upper()
    log("Generated device UUID:{}".format(systemConfig["deviceId"]))
    db.save({"systemConfig": ujson.dumps(systemConfig)})


def createDefaultConfig():
    log("create default config...")
    db.delete("systemConfig")
    db.save({"systemConfig": ujson.dumps(defaultSystemConfig)})


# ===== BSP + FSM 初始化 =====
bspInstance = bsp.bspInstance
bspInstance.setConfig(systemConfig)

log("init FSM...")
lightFSM = lightControlFSM.FSM(bspInstance, systemConfig)
fanFSMInstance = fanFSM.FSM(bspInstance, systemConfig)
pumpFSMInstance = pumpFSM.FSM(bspInstance, systemConfig)

# ===== 矩阵动画（run() 由主循环驱动，与 FSM 同模式）=====
matrixAnim = matrix_anim.MatrixAnim(bspInstance.matrix, fps=24, brightness=systemConfig.get("matrixBrightness", 1.0))
matrixAnim.play(systemConfig.get("matrixAnim", "rainbow"))
log("matrix animations: {}".format(matrixAnim.list()))


# ===== 主循环计时变量 =====
lastMainTick = utime.ticks_ms()
lastFanTick = 0
lastPumpTick = 0
lastSensorTick = 0
lastWifiCheckTick = 0
lastGCTick = 0
lastSaveTick = 0
lastLedTick = 0
ledOn = True
runMs = 0  # 本次上电运行毫秒数（输出 runTime = runMs // 1000）

# 跨开机累计系统运行时间（DB 以秒存储）
totalRunTimeMs = 0
if db.get("totalRunTime") is not None:
    totalRunTimeMs = int(db.get("totalRunTime")) * 1000
else:
    db.save({"totalRunTime": "0"})

# 系统总上电次数（每次开机 +1 并持久化）
powerOnCount = 0
if db.get("powerOnCount") is not None:
    powerOnCount = int(db.get("powerOnCount"))
powerOnCount += 1
db.save({"powerOnCount": str(powerOnCount)})
log("powerOnCount: {}".format(powerOnCount))

WIFI_RECONNECT_INTERVAL_MS = 30000
GC_INTERVAL_MS = 300000  # 5 分钟（对齐雾化器，30s 过于频繁造成不必要停顿）
SAVE_INTERVAL_MS = 3600000
FSM_SLOW_INTERVAL_MS = 1000  # Fan/Pump FSM 1Hz
WDT_TIMEOUT_MS = 60000  # 看门狗超时 60s
ALIVE_TIMEOUT_MS = 30000  # 主循环超过 30s 未刷新视为卡死

wdt = machine.WDT(timeout=WDT_TIMEOUT_MS)

# 主循环活性检测：主循环每轮刷新 lastAliveTick，
# feedDog 仅在主循环存活时喂狗；主循环卡死则停止喂狗，由 WDT 触发复位
lastAliveTick = utime.ticks_ms()

# 主循环实测频率（每 5s 统计一次），暴露到 /status 便于发现阻塞掉速
loopHz = 0.0
_loopCount = 0
_loopCountTick = utime.ticks_ms()


def updateAliveTick():
    global lastAliveTick, loopHz, _loopCount, _loopCountTick
    now = utime.ticks_ms()
    lastAliveTick = now
    _loopCount += 1
    elapsed = utime.ticks_diff(now, _loopCountTick)
    if elapsed >= 5000:
        loopHz = round(_loopCount * 1000.0 / elapsed, 1)
        _loopCount = 0
        _loopCountTick = now


def feedDog(timer):
    now = utime.ticks_ms()
    if utime.ticks_diff(now, lastAliveTick) < ALIVE_TIMEOUT_MS:
        wdt.feed()
    else:
        log("[WARN] main loop blocked {}ms, stop feeding WDT.".format(
            utime.ticks_diff(now, lastAliveTick)))


WDTTimer = machine.Timer(0)
WDTTimer.init(mode=machine.Timer.PERIODIC, period=15000, callback=feedDog)

# WiFi 重连并发保护：startReconnect 内部有 1s sleep，放后台线程避免阻塞主循环（旋钮 10Hz 响应）
_reconnecting = False

# 配置热更新标记：Web 线程修改 systemConfig 后置 True，主循环在主线程上下文执行 reloadAllConfig，
# 避免 Web 线程与主循环同时修改 FSM/BSP 状态造成竞态
_pendingConfigReload = False


def _doReconnect(ssid, pwd):
    global _reconnecting
    try:
        wifi.startReconnect(ssid, pwd)
    finally:
        _reconnecting = False


def maskArgs(args):
    """密码字段脱敏日志。
    注意：request.args 是 microdot.MultiDict（dict 子类，值存为列表），
    MicroPython 的 dict(args) 对 dict 子类会退化为迭代键字符串而抛
    ValueError，因此手动迭代构建普通 dict。"""
    masked = {}
    try:
        for k in args:
            masked[k] = args.get(k)
    except Exception:
        masked = {"args": str(args)}
    for k in ("pwd", "devicepwd", "APPwd", "wifipwd"):
        if k in masked:
            masked[k] = "****"
    return masked


def reloadAllConfig():
    """配置变更后通知所有 FSM + BSP 重载"""
    bspInstance.setConfig(systemConfig)
    lightFSM.reloadConfig(systemConfig)
    fanFSMInstance.reloadConfig(systemConfig)
    pumpFSMInstance.reloadConfig(systemConfig)


# ===== Web 服务 =====
app = Microdot()
MAX_CONFIG_MODE_TIME_IN_SECONDS = 300
whenGotoConfigMode = 0


def _sendStatic(request, filePath):
    """支持 gzip 预压缩静态资源；max_age=0 强制浏览器每次重新校验，避免改完页面仍显示旧缓存"""
    dirEnd = filePath.rfind('/')
    if 'gzip' in request.headers.get('Accept-Encoding', '') and \
            fileUtils.isFileExist(filePath[:dirEnd + 1],
                                  filePath[dirEnd + 1:] + '.gz'):
        log("send compressed file:{}".format(filePath))
        return send_file(filePath, compressed=True, file_extension='.gz', max_age=0)
    return send_file(filePath, max_age=0)


@app.route('/')
def handler(request):
    global whenGotoConfigMode
    whenGotoConfigMode = utime.time()
    return _sendStatic(request, '/static/index.html')


@app.route('/favicon.ico')
def handler(request):
    return _sendStatic(request, '/static/favicon.ico')


@app.route('/static/<path:path>')
def handler(request, path):
    if '..' in path or not fileUtils.isFileExist("/static/", path):
        return 'Not found', 404
    return _sendStatic(request, '/static/' + path)


@app.get('/status')
def handler(request):
    global whenGotoConfigMode
    whenGotoConfigMode = utime.time()

    if "devicepwd" not in request.args or request.args["devicepwd"] != systemConfig["devicepwd"]:
        return ujson.dumps({"errCode": "-1", "msg": "invalid device password."})

    mode = request.args.get("mode", "")

    if mode == "get":
        res = {"errCode": "0"}
        sd = bspInstance.getSensorData()
        res["temp"] = sd.temp
        res["humi"] = sd.humi
        res["presure"] = sd.presure
        res["luminance"] = sd.luminance
        res["pm25"] = sd.pm25
        res["tempBMP280"] = sd.tempBMP280
        res["tempLM75_1"] = sd.tempLM75_1
        res["tempLM75_2"] = sd.tempLM75_2
        res["tempLM75_3"] = sd.tempLM75_3
        res.update(systemConfig)
        # 密码类字段不下发：避免任何持有 devicepwd 的客户端拿到设备密码明文
        # （WiFi 密码/AP 密码为设备自身配置，页面需 devicepwd 鉴权，允许回显）
        for _k in ("devicepwd", "wifipwdDefault"):
            res.pop(_k, None)
        res.update(lightFSM.getStatus())
        res.update(fanFSMInstance.getStatus())
        res.update(pumpFSMInstance.getStatus())
        res["fanSpeed"] = bspInstance.getFanSpeed()
        res["pumpSpeed"] = bspInstance.getPumpSpeed()
        res["lightStatus"] = bspInstance.getLightStatus()
        res["runTime"] = int(runMs / 1000)
        res["totalRunTime"] = int(totalRunTimeMs / 1000)
        res["powerOnCount"] = powerOnCount
        res["loopHz"] = loopHz
        return ujson.dumps(res)

    elif mode == "set":
        errors = validateSetArgs(request.args)
        if errors:
            return ujson.dumps({"errCode": "-1", "msg": "; ".join(errors)})

        # 数值参数
        for key in ("fanHThreshold", "fanLThreshold", "LEDHThreshold", "LEDLThreshold"):
            if key in request.args:
                systemConfig[key] = float(request.args[key])
        for key in ("fanPwmFreq", "fanPwmMin", "fanPwmMax",
                    "pumpPwmFreq", "pumpPwmMin", "pumpPwmMax",
                    "yellowPwmFreq", "yellowPwmMin", "yellowPwmMax",
                    "whitePwmFreq", "whitePwmMin", "whitePwmMax",
                    "fanDelayTime", "delayedOff",
                    "delayedOffTime", "eyeRemindInterval"):
            if key in request.args:
                systemConfig[key] = int(request.args[key])
        if "sw1name" in request.args:
            systemConfig["sw1name"] = request.args["sw1name"]
        if "sw2name" in request.args:
            systemConfig["sw2name"] = request.args["sw2name"]

        log("set config:{}".format(maskArgs(request.args)))
        db.save({"systemConfig": ujson.dumps(systemConfig)})
        # 配置在主线程重载，避免 Web 线程与主循环竞态修改 FSM/BSP 状态
        global _pendingConfigReload
        _pendingConfigReload = True
        return ujson.dumps({"errCode": "0", "msg": "set finish."})

    return ujson.dumps({"errCode": "-1", "msg": "unsupported operation."})


def validateSetArgs(args):
    """参数范围校验，返回错误消息列表"""
    errors = []

    def checkNum(key, conv, lo, hi):
        if key not in args:
            return
        try:
            v = conv(args[key])
            if v < lo or v > hi:
                errors.append("{} out of range[{},{}]".format(key, lo, hi))
        except (ValueError, TypeError):
            errors.append("{} must be a number".format(key))

    def effVal(key, conv):
        if key in args:
            return conv(args[key])
        # 用 .get 兜底，避免 systemConfig 缺 key 时抛 KeyError
        return conv(systemConfig.get(key, 0))

    def checkPair(a, b, conv):
        try:
            if effVal(a, conv) >= effVal(b, conv):
                errors.append("{} must be less than {}".format(a, b))
        except (ValueError, TypeError, KeyError):
            pass

    # 温度阈值
    checkNum("fanLThreshold", float, -20, 120)
    checkNum("fanHThreshold", float, -20, 120)
    checkPair("fanLThreshold", "fanHThreshold", float)
    checkNum("LEDLThreshold", float, -20, 120)
    checkNum("LEDHThreshold", float, -20, 120)
    checkPair("LEDLThreshold", "LEDHThreshold", float)

    # PWM 参数
    for prefix in ("fanPwm", "pumpPwm", "yellowPwm", "whitePwm"):
        checkNum(prefix + "Freq", int, 1, 78125)
        checkNum(prefix + "Min", int, 0, 100)
        checkNum(prefix + "Max", int, 0, 100)
        checkPair(prefix + "Min", prefix + "Max", int)

    checkNum("fanDelayTime", int, 1, 3600)
    checkNum("delayedOff", int, 0, 1)
    checkNum("delayedOffTime", int, 3, 300)
    checkNum("eyeRemindInterval", int, 0, 60)
    return errors


@app.get('/light')
def handler(request):
    """灯光 Web 控制：onOffStatus / brightness(0-100) / colorTemperature(0-100)
    标量赋值经 MicroPython GIL 保证原子，主循环 fitPower 每 tick 平滑应用。"""
    global whenGotoConfigMode
    whenGotoConfigMode = utime.time()

    if "devicepwd" not in request.args or request.args["devicepwd"] != systemConfig["devicepwd"]:
        return ujson.dumps({"errCode": "-1", "msg": "invalid device password."})

    mode = request.args.get("mode", "")

    if mode == "get":
        return ujson.dumps({"errCode": "0", "light": lightFSM.getStatus()})

    elif mode == "set":
        if "onOffStatus" in request.args:
            lightFSM.setOnOff(request.args["onOffStatus"] in ("true", "1", "on"))
        if "brightness" in request.args:
            try:
                lightFSM.setBrightness(int(request.args["brightness"]))
            except (ValueError, TypeError):
                return ujson.dumps({"errCode": "-1", "msg": "brightness must be 0-100"})
        if "colorTemperature" in request.args:
            try:
                lightFSM.setColorTemperature(int(request.args["colorTemperature"]))
            except (ValueError, TypeError):
                return ujson.dumps({"errCode": "-1", "msg": "colorTemperature must be 0-100"})
        return ujson.dumps({"errCode": "0", "msg": "light set finish.", "light": lightFSM.getStatus()})

    return ujson.dumps({"errCode": "-1", "msg": "unsupported operation."})


@app.get('/matrix')
def handler(request):
    """矩阵动画控制：mode=list 列出动画，mode=set&name=xxx 切换动画。"""
    global whenGotoConfigMode
    whenGotoConfigMode = utime.time()
    if "devicepwd" not in request.args or request.args["devicepwd"] != systemConfig["devicepwd"]:
        return ujson.dumps({"errCode": "-1", "msg": "invalid device password."})
    mode = request.args.get("mode", "")
    if mode == "list":
        return ujson.dumps({"errCode": "0", "animations": matrixAnim.list()})
    elif mode == "set":
        name = request.args.get("name", "")
        if name in matrixAnim.list():
            # 亮度：支持从请求参数传入并持久化
            brightness = systemConfig.get("matrixBrightness", 1.0)
            try:
                brightness = max(0.01, min(1.0, float(request.args.get("brightness", str(brightness)))))
            except ValueError:
                pass
            systemConfig["matrixBrightness"] = brightness
            matrixAnim.matrix.brightness = brightness
            matrixAnim.play(name)
            systemConfig["matrixAnim"] = name
            db.save({"systemConfig": ujson.dumps(systemConfig)})
            return ujson.dumps({"errCode": "0", "msg": "playing: {}".format(name)})
        return ujson.dumps({"errCode": "-1", "msg": "unknown animation: {}".format(name)})
    elif mode == "scroll":
        text = request.args.get("text", "")
        if text:
            # 颜色：支持 #RRGGBB 或 r,g,b
            color = (0, 255, 120)
            c = request.args.get("color", "")
            if c:
                if c.startswith("#") and len(c) == 7:
                    try:
                        color = (int(c[1:3], 16), int(c[3:5], 16), int(c[5:7], 16))
                    except ValueError:
                        pass
                elif "," in c:
                    parts = c.split(",")
                    if len(parts) == 3:
                        try:
                            color = (int(parts[0]), int(parts[1]), int(parts[2]))
                        except ValueError:
                            pass
            brightness = 1.0
            try:
                brightness = max(0.01, min(1.0, float(request.args.get("brightness", "1"))))
            except ValueError:
                pass
            speed = 20
            try:
                speed = max(1.0, min(100.0, float(request.args.get("speed", "20"))))
            except ValueError:
                pass
            matrixAnim.scroll_text(text, color=color, brightness=brightness, speed=speed)
            # 持久化到 systemConfig
            color_hex = "#{:02x}{:02x}{:02x}".format(color[0], color[1], color[2])
            systemConfig["matrixText"] = text
            systemConfig["matrixColor"] = color_hex
            systemConfig["matrixBrightness"] = brightness
            systemConfig["matrixSpeed"] = speed
            db.save({"systemConfig": ujson.dumps(systemConfig)})
            return ujson.dumps({"errCode": "0", "msg": "scrolling: {}".format(text)})
        return ujson.dumps({"errCode": "-1", "msg": "text is required."})
    elif mode == "off":
        matrixAnim.stop()
        return ujson.dumps({"errCode": "0", "msg": "matrix off"})
    elif mode == "update":
        # 实时更新亮度/速度/颜色，不重启当前动画或滚动文本（滑动条/取色器变动时调用）
        if "brightness" in request.args:
            try:
                brightness = max(0.01, min(1.0, float(request.args["brightness"])))
                systemConfig["matrixBrightness"] = brightness
                matrixAnim.update_params(brightness=brightness)
            except ValueError:
                pass
        if "speed" in request.args:
            try:
                speed = max(1.0, min(100.0, float(request.args["speed"])))
                systemConfig["matrixSpeed"] = speed
                matrixAnim.update_params(speed=speed)
            except ValueError:
                pass
        if "color" in request.args:
            c = request.args["color"]
            color = None
            if c.startswith("#") and len(c) == 7:
                try:
                    color = (int(c[1:3], 16), int(c[3:5], 16), int(c[5:7], 16))
                except ValueError:
                    pass
            if color is not None:
                systemConfig["matrixColor"] = c
                matrixAnim.update_params(color=color)
        db.save({"systemConfig": ujson.dumps(systemConfig)})
        return ujson.dumps({"errCode": "0", "msg": "matrix params updated"})
    return ujson.dumps({"errCode": "-1", "msg": "unsupported operation."})


@app.get('/scanap')
def handler(request):
    global whenGotoConfigMode
    whenGotoConfigMode = utime.time()
    res = wifi.scanAP()
    return ujson.dumps(res) if len(res) > 0 else "{}"


@app.get('/setwifi')
def handler(request):
    global whenGotoConfigMode
    whenGotoConfigMode = utime.time()
    res = {"errCode": "0", "msg": "success", "APName": "APName", "url": "url"}
    log("setwifi args:{}".format(maskArgs(request.args)))

    # 前端「保存 WiFi」只提交 ssid/pwd/devicename/devicepwd/APName/APPwd；
    # serverurl/sw1name/sw2name 为可选，未提交时保留当前配置值。
    required = ("ssid", "pwd", "devicename", "devicepwd")
    missing = [k for k in required if k not in request.args or request.args[k] == ""]
    if missing:
        res["errCode"] = "-1"
        res["msg"] = "missing required params:{}".format(",".join(missing))
        return ujson.dumps(res)

    ssid = request.args["ssid"]
    pwd = request.args["pwd"]
    if wifi.testWifiConnect(ssid, pwd):
        if "sw1name" in request.args:
            systemConfig["sw1name"] = request.args["sw1name"]
        if "sw2name" in request.args:
            systemConfig["sw2name"] = request.args["sw2name"]
        systemConfig["devicename"] = request.args["devicename"]
        systemConfig["devicepwd"] = request.args["devicepwd"]
        if "serverurl" in request.args:
            systemConfig["serverurl"] = request.args["serverurl"]
        systemConfig["wifiname"] = ssid
        systemConfig["wifipwd"] = pwd
        systemConfig["mode"] = "normal"
        if "deviceusername" in request.args:
            systemConfig["deviceusername"] = request.args["deviceusername"]
        if "APName" in request.args:
            systemConfig["APName"] = request.args["APName"]
        if "APPwd" in request.args:
            systemConfig["APPwd"] = request.args["APPwd"]
        if "APIP" in request.args:
            systemConfig["APIP"] = request.args["APIP"]

        db.save({"systemConfig": ujson.dumps(systemConfig)})
        whenGotoConfigMode = utime.time() - MAX_CONFIG_MODE_TIME_IN_SECONDS + 10
        log("reboot after 10s.")
        createConfigTimer(10)
        res["APName"] = ssid
        res["url"] = wifi.getStationIP() or ""
        res["msg"] = "connect wifi success, reboot after 5s."
    else:
        systemConfig["mode"] = "config"
        res["errCode"] = "-1"
        res["msg"] = "connect wifi failed."
    return ujson.dumps(res)


@app.get('/reset')
def handler(request):
    global whenGotoConfigMode
    whenGotoConfigMode = utime.time()
    res = {"errCode": "0", "msg": "success"}
    if "devicepwd" in request.args and request.args["devicepwd"] == systemConfig["devicepwd"]:
        log("reset config after 5s.")
        lightFSM.close()
        fanFSMInstance.close()
        pumpFSMInstance.close()
        createDefaultConfig()
        whenGotoConfigMode = utime.time() - MAX_CONFIG_MODE_TIME_IN_SECONDS + 5
        createConfigTimer(5)
    else:
        res["errCode"] = "-1"
        res["msg"] = "invalid device passwd."
    return ujson.dumps(res)


@app.get('/restart')
def handler(request):
    global whenGotoConfigMode
    whenGotoConfigMode = utime.time()
    res = {"errCode": "0", "msg": "success"}
    if "devicepwd" in request.args and request.args["devicepwd"] == systemConfig["devicepwd"]:
        log("reboot after 5s.")
        lightFSM.close()
        fanFSMInstance.close()
        pumpFSMInstance.close()
        whenGotoConfigMode = utime.time() - MAX_CONFIG_MODE_TIME_IN_SECONDS + 5
        createConfigTimer(5)
    else:
        res["errCode"] = "-1"
        res["msg"] = "invalid device passwd."
    return ujson.dumps(res)


def runWebApp(name):
    global MAX_CONFIG_MODE_TIME_IN_SECONDS, whenGotoConfigMode

    if "normal" == systemConfig["mode"] and wifi.connectToWifi(systemConfig["wifiname"], systemConfig["wifipwd"]):
        log("connect wifi success.")
        systemConfig["mode"] = "normal"
        stationIP = wifi.getStationIP() or ""
        broadcastName = stationIP + "_" + systemConfig["devicename"]
        wifi.startAP(broadcastName, systemConfig["APPwd"])
    else:
        systemConfig["mode"] = "config"
        log("start config mode...")
        whenGotoConfigMode = utime.time()
        wifi.startAP(systemConfig["APName"], systemConfig["APPwd"])
        createConfigTimer(10)

    log("start web app...")
    app.run(host='0.0.0.0', port=80, debug=False, ssl=None)


def modeTimerHandler(timer):
    global whenGotoConfigMode
    log("config mode left {}s to exit.".format(
        MAX_CONFIG_MODE_TIME_IN_SECONDS - int(utime.time() - whenGotoConfigMode)))
    if wifi.isConnected() or (utime.time() - whenGotoConfigMode) > MAX_CONFIG_MODE_TIME_IN_SECONDS:
        log("reboot now.")
        wifi.stopAP()
        # 短暂延时确保日志输出完成再复位
        utime.sleep_ms(200)
        machine.reset()


_configTimer = None


def createConfigTimer(seconds=10):
    """配置模式看门狗：周期性检查是否应退出配置模式并重启。
    - normal 模式 WiFi 连上后立即重启
    - 配置模式超过 MAX_CONFIG_MODE_TIME_IN_SECONDS 后强制重启
    reset/restart/setwifi 时通过回拨 whenGotoConfigMode 让超时条件尽快满足
    硬件 Timer(3) 只创建一次：setwifi/reset/restart 可能重复调用本函数，
    反复 new Timer(3) 会重复占用同一硬件定时器"""
    global _configTimer
    if _configTimer is None:
        _configTimer = machine.Timer(3)
    _configTimer.init(mode=machine.Timer.PERIODIC, period=seconds * 1000,
                      callback=modeTimerHandler)


# NTP 校时：启动时尝试一次，失败后由主循环每 60s 重试（WiFi 未就绪时跳过）
NTP_RETRY_INTERVAL_MS = 60000
ntpSynced = False
ntpLastTryTick = -NTP_RETRY_INTERVAL_MS  # 负初始值：首轮循环立即尝试


def tryNtpSync():
    global ntpSynced, ntpLastTryTick
    if ntpSynced:
        return
    if not wifi.isConnected():
        return
    now = utime.ticks_ms()
    if utime.ticks_diff(now, ntpLastTryTick) < NTP_RETRY_INTERVAL_MS:
        return
    ntpLastTryTick = now
    try:
        if ntpSync.syncRtc():
            ntpSynced = True
            log("NTP synced, retry disabled.")
    except Exception as e:
        log("[WARN] NTP sync failed:{}".format(e))


# 启动时尝试一次（此时 WiFi 可能尚未连上，失败则由主循环重试）
tryNtpSync()

# 启动 Web 线程
try:
    _thread.stack_size(32 * 1024)
    _thread.start_new_thread(runWebApp, ("Thread:WebApp",))
except OSError as e:
    log("Error starting web thread: {}".format(e))

log("start finish.")

# ===== 主循环 10Hz =====
while True:
    # 主循环活性标记：每轮刷新，feedDog 据此决定是否喂狗
    updateAliveTick()
    now = utime.ticks_ms()
    delta = utime.ticks_diff(now, lastMainTick)
    lastMainTick = now
    runMs += delta
    totalRunTimeMs += delta

    # NTP 校时重试（WiFi 就绪后每 60s 尝试，成功后停止）
    tryNtpSync()

    # 配置热更新：在主线程上下文中执行，避免与 Web 线程竞态
    if _pendingConfigReload:
        _pendingConfigReload = False
        try:
            reloadAllConfig()
        except Exception as e:
            log("[ERROR] reloadAllConfig failed:{}".format(e))
            # 重载失败则保留标志，下一 tick 重试（避免 FSM/BSP 与 systemConfig 状态不一致）
            _pendingConfigReload = True

    # 灯光 FSM（高频处理旋钮）
    try:
        lightFSM.run()
    except Exception as e:
        log("[ERROR] LightFSM.run failed:{}".format(e))

    # 矩阵动画（内部按帧间隔节流）
    matrixAnim.run()

    # 风扇 FSM（1Hz）
    if utime.ticks_diff(now, lastFanTick) >= FSM_SLOW_INTERVAL_MS:
        lastFanTick = now
        try:
            fanFSMInstance.run()
        except Exception as e:
            log("[ERROR] FanFSM.run failed:{}".format(e))

    # 水泵 FSM（1Hz）
    if utime.ticks_diff(now, lastPumpTick) >= FSM_SLOW_INTERVAL_MS:
        lastPumpTick = now
        try:
            pumpFSMInstance.run()
        except Exception as e:
            log("[ERROR] PumpFSM.run failed:{}".format(e))

    # 传感器读取（1Hz 调度，BSP 内部仍有节流作为双重保险；I2C 故障已在 BSP 内捕获）
    if utime.ticks_diff(now, lastSensorTick) >= FSM_SLOW_INTERVAL_MS:
        lastSensorTick = now
        try:
            bspInstance.readSensors()
        except Exception as e:
            log("[ERROR] bsp.readSensors failed:{}".format(e))

    # WiFi 重连（30s，normal 模式；后台线程执行，避免 1s 射频复位阻塞旋钮响应）
    if systemConfig["mode"] == "normal" and \
            utime.ticks_diff(now, lastWifiCheckTick) >= WIFI_RECONNECT_INTERVAL_MS:
        lastWifiCheckTick = now
        if not wifi.isConnected() and not _reconnecting:
            log("WiFi disconnected, try reconnect...")
            _reconnecting = True
            try:
                _thread.start_new_thread(_doReconnect,
                                         (systemConfig["wifiname"], systemConfig["wifipwd"]))
            except OSError as e:
                log("[ERROR] start reconnect thread failed:{}".format(e))
                _reconnecting = False

    # GC（5min，对齐雾化器；前后打印内存信息便于排查泄漏）
    if utime.ticks_diff(now, lastGCTick) >= GC_INTERVAL_MS:
        lastGCTick = now
        log("-------------Before GC-------------")
        mp.mem_info()
        gc.collect()
        log("-------------After  GC-------------")
        mp.mem_info()

    # 配置持久化（1h，防止异常掉电丢失）+ 系统总运行时间
    if utime.ticks_diff(now, lastSaveTick) >= SAVE_INTERVAL_MS:
        lastSaveTick = now
        db.save({"systemConfig": ujson.dumps(systemConfig),
                 "totalRunTime": str(totalRunTimeMs // 1000)})

    # 状态 LED 心跳（2s 翻转）：绿=WiFi已连，蓝=配置模式，红=normal但未连
    if utime.ticks_diff(now, lastLedTick) >= 2000:
        lastLedTick = now
        ledOn = not ledOn
        if ledOn:
            if systemConfig["mode"] == "config":
                bspInstance.setLEDArray((0, 0, 255))
            elif wifi.isConnected():
                bspInstance.setLEDArray((0, 255, 0))
            else:
                bspInstance.setLEDArray((255, 0, 0))
        else:
            bspInstance.setLEDArray((0, 0, 0))

    # 看门狗由 Timer(0) 每 15s 调用 feedDog：
    # 仅当主循环 30s 内刷新过 lastAliveTick 才喂狗，否则让 WDT 触发复位
    utime.sleep_ms(50)  # 20Hz 主循环（调光渐变步长按时间计算，提高频率只为步进更细腻）
