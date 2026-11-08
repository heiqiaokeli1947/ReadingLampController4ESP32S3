from domain.LogUtils import log
import time
import network
import sys


def connectToWifi(ssid, pwd):
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    log("init wifi...")
    try:
        # 连接超时使用单调时钟 ticks_ms，避免 NTP 校时跳变 RTC 导致误判超时
        start_tick = time.ticks_ms()
        log("start connect (monotonic tick):{}".format(start_tick))
        if not wlan.isconnected():
            log("try to connect ssid:{}".format(ssid))
            wlan.connect(ssid, pwd)
            while not wlan.isconnected():
                log("connect failed,sleep 1s")
                time.sleep(1)
                elapsed_ms = time.ticks_diff(time.ticks_ms(), start_tick)
                log("use time:{}s".format(elapsed_ms // 1000))
                if elapsed_ms > 35000:
                    log("connect wifi timeout.")
                    return False
            log("connect success.")
            log("ifconfig:", wlan.ifconfig())
            return True
        else:
            log("connect success.")
            log("ifconfig:", wlan.ifconfig())
            return True
    except Exception as e:
        sys.print_exception(e)
        log('connect exception.')
        return False
    finally:
        log('connectWiFi finish')


def getStationIP():
    # 未连接时返回 None（原返回错误字符串会被 truthy 判断误当有效 IP）
    wlan = network.WLAN(network.STA_IF)
    if wlan.active() and wlan.isconnected():
        return wlan.ifconfig()[0]
    else:
        return None


def startReconnect(ssid, pwd):
    # 复位式重连：断线后对 STA 做完整射频电源循环，
    # active(False) → 1s → active(True) → connect()，强制底层重建关联-DHCP 状态机。
    # 由主循环每 30s 在确认 isConnected()==False 后调用一次，30s 周期即天然退避。
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
    wlan = network.WLAN(network.STA_IF)
    log("init wifi...")
    wlan.active(False)
    time.sleep(1)
    wlan.active(True)

    try:
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
        log("test connect success! ifconfig:", wlan.ifconfig())
        return True
    except Exception as e:
        sys.print_exception(e)
        log('test connect exception.')
        return False
    finally:
        log('test connect WiFi finish.')


def startAP(apname, appwd, forConfig=False):
    try:
        ap = network.WLAN(network.AP_IF)
        ap.active(True)
        if forConfig:
            tmpName = apname + "_" + ap.ifconfig()[0]
        else:
            tmpName = apname
        log("start ap:{},{}".format(tmpName, appwd))
        ap.config(essid=tmpName, authmode=network.AUTH_WPA_WPA2_PSK, password=appwd)
        log('AP IP address:{}'.format(tmpName))
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
        return None


def stopAP():
    try:
        log('stop AP...')
        ap = network.WLAN(network.AP_IF)
        ap.active(False)
        return True
    except Exception as e:
        sys.print_exception(e)
        log('stop AP exception.')
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
        res = wlan.scan()  # (ssid, bssid, channel, RSSI, security, hidden)
        # 改为 list，避免同名 SSID 被 dict 覆盖
        result = []
        for item in res:
            if len(item[0]) != 0:
                result.append({"ssid": item[0], "rssi": item[3]})
        log('Find AP:{}'.format(result))
        return result
    except Exception as e:
        sys.print_exception(e)
        log('scan AP exception.')
        return []
    finally:
        log('scan AP finish.')
