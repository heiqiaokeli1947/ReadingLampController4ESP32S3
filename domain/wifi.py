# 操作esp32引脚
#from machine import Pin

# 操作时间 延迟几秒等
from domain.LogUtils import log
import time
# 网络相关的函数
import network
import sys

# esp32 引脚2是一颗自带的 led的灯
#light = Pin(2, Pin.OUT)

def connectToWifi(ssid, pwd):
    # wifi模式
    wlan = network.WLAN(network.STA_IF)
    # 激活
    wlan.active(True)
    log("init wifi...")
    try:
        # 连接超时设置：使用单调时钟 ticks_ms，避免 NTP 校时跳变 RTC 导致误判超时
        # （NTP 可能在连接过程中把墙钟从 2000 年跳到当前年份，time.time() 差值会瞬间爆炸）
        start_tick = time.ticks_ms()
        log("start connect (monotonic tick):{}".format(start_tick))
        if not wlan.isconnected():
            log("try to connect ssid:{}".format(ssid))
            wlan.connect(ssid, pwd)
            while not wlan.isconnected():
                log("connect failed,sleep 1s")
                time.sleep(1)
                # 35 秒内没连接上就是超时了（ticks_diff 处理回绕）
                elapsed_ms = time.ticks_diff(time.ticks_ms(), start_tick)
                log("use time:{}s".format(elapsed_ms // 1000))
                if elapsed_ms > 35000:
                    log("connect wifi timeout.")
                    #wlan.active(False)
                    return False
            log("connect success.")
            #light.value(1)
            # 打印 网络信息
            log("ifconfig:", wlan.ifconfig())
            return True
        else:
            log("connect success.")
            #light.value(1)
            # 打印 网络信息
            log("ifconfig:", wlan.ifconfig())
            return True
    except Exception as e:
        sys.print_exception(e)
        log('connect exception.')
        #wlan.active(False)
        return False
    finally:
        log('connectWiFi finish')


def getStationIP():
    # 未连接时返回 None（P1-4 修复：原返回错误字符串 "Station not active or not connected."
    # 会被 truthy 判断误当有效 IP，导致断线时仍以非法超长 SSID 反复启动 AP、LED 误报在线）
    wlan = network.WLAN(network.STA_IF)
    if wlan.active() and wlan.isconnected():
        return wlan.ifconfig()[0]
    else:
        return None


def startReconnect(ssid, pwd):
    # 复位式重连（高可靠极简方案）：断线后每次重连都对 STA 做一次完整射频电源循环
    # active(False) → 1s → active(True) → connect()，强制底层完整重走
    # 扫描→认证→关联→DHCP 全流程。
    # 背景：长跑几十小时后（DHCP 租约到期/信标丢失/deauth/路由重启）STA 可能进入
    # "接口仍 active 但内部关联-DHCP 状态机已卡死"的假活状态，此时对热接口反复
    # connect() 只重发关联请求、无法恢复；只有射频复位才能彻底重建。
    # 由主循环每 30s 在确认 isConnected()==False 后调用一次，30s 周期即天然退避，
    # 无需失败计数；1s sleep 远小于喂狗 30s 活性窗口，不触发 WDT；异常全捕获。
    try:
        wlan = network.WLAN(network.STA_IF)
        wlan.active(False)
        time.sleep(1)
        wlan.active(True)
        wlan.connect(ssid, pwd)
        log("wifi reconnect (radio restart):{}".format(ssid))
        return True
    except Exception as e:
        sys.print_exception(e)
        log('wifi reconnect exception.')
        return False


def testWifiConnect(ssid, pwd):
    log("try to connect ssid:{}".format(ssid))
    # wifi模式
    wlan = network.WLAN(network.STA_IF)
    # 激活
    log("init wifi...")
    wlan.active(False)
    time.sleep(1)
    wlan.active(True)

    try:
        #  连接超时设置：使用单调时钟，避免 NTP 跳变误判
        start_tick = time.ticks_ms()
        log("start test connect (monotonic tick):{}".format(start_tick))
        wlan.connect(ssid, pwd)
        while not wlan.isconnected():
            log("sleep 1s then retry.")
            time.sleep(1)
            elapsed_ms = time.ticks_diff(time.ticks_ms(), start_tick)
            if elapsed_ms > 35000:
                log("test connect failed by timeout.")
                return False
        # 打印 网络信息
        log("test connect success! ifconfig:", wlan.ifconfig())
        return True
    except Exception as e:
        sys.print_exception(e)
        log('test connect exception.')
        #wlan.active(False)
        return False
    finally:
        log('test connect WiFi finish.')


def startAP(apname, appwd, forConfig=False):
    try:
        # 创建Wi-Fi接入点
        ap = network.WLAN(network.AP_IF)
        # 启用接入点
        #ap.active(False)
        #time.sleep(1)
        ap.active(True)
        if forConfig:
            tmpName = apname + "_" + ap.ifconfig()[0]
        else:
            tmpName = apname
        log("start ap:{},{}".format(tmpName, appwd))
        # 设置接入点参数
        ap.config(essid=tmpName, authmode=network.AUTH_WPA_WPA2_PSK, password=appwd)
        # 输出接入点IP地址
        log('AP IP address:{}'.format(tmpName))
        return True
    except Exception as e:
        sys.print_exception(e)
        log('start AP exception.')
        #ap.active(False)
        return False
    finally:
        log('start AP finish.')


def startBroadcastAP(apname, appwd):
    try:
        ap = network.WLAN(network.AP_IF)
        ap.active(True)
        ap.config(essid=apname, authmode=network.AUTH_WPA_WPA2_PSK, password=appwd)
        return True
    except Exception as e:
        sys.print_exception(e)
        log('start AP exception.')
        return False
    finally:
        log('start AP finish.')


def getAPIP():
    ap = network.WLAN(network.AP_IF)
    if ap.active():
        return ap.ifconfig()[0]
    else:
        return "AP not active."


def stopAP():
    try:
        log('stop AP...')
        ap = network.WLAN(network.AP_IF)
        ap.active(False)
        return True
    except Exception as e:
        sys.print_exception(e)
        log('stop AP exception.')
        #ap.active(False)
        return False
    finally:
        log('stop AP finish.')


def isConnected():
    wlan = network.WLAN(network.STA_IF)
    return wlan.isconnected()


def scanAP():
    try:
        log('scan AP...')
        wlan = network.WLAN(network.STA_IF)
        wlan.active(True)
        res = wlan.scan()  #(ssid, bssid, channel, RSSI, security, hidden)
        result = {}
        for item in res:
            if len(item[0]) != 0:
                result[item[0]] = item[3]
        log('Find AP:{}'.format(result))
        return result
    except Exception as e:
        sys.print_exception(e)
        log('scan AP exception.')
        return {}
    finally:
        log('scan AP finish.')