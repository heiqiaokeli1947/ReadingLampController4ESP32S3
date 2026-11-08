# NTP 网络对时模块
# WiFi 联网后从互联网 NTP 服务器获取标准时间写入 RTC（北京时间 UTC+8）。
# 对时失败时不改动 RTC，由调用方（main.py 主循环）按周期重试，成功一次后停止。
# 对时成功前系统时间为 1970 起算的默认时间，日志时间戳无参考意义。
import utime
import machine
import socket
import struct
from domain.LogUtils import log

TZ_OFFSET_SECONDS = 8 * 3600  # 北京时间 UTC+8
NTP_HOST = "ntp.aliyun.com"   # 国内 NTP 服务器
NTP_PORT = 123
NTP_TIMEOUT_S = 5             # 单次请求超时（秒）
NTP_DELTA = 2208988800        # NTP 时间基准(1900) 与 Unix 时间基准(1970) 的秒差


def getNtpUtcSeconds():
    # 发送 SNTP 请求（48 字节报文，首字节 0x1B = LI=0, VN=3, Mode=3 client）
    # 成功返回 Unix UTC 秒数，任何失败返回 None，不抛异常
    try:
        addr = socket.getaddrinfo(NTP_HOST, NTP_PORT)[0][-1]
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(NTP_TIMEOUT_S)
        try:
            s.sendto(b"\x1b" + bytes(47), addr)
            data = s.recv(48)
        finally:
            s.close()
        if len(data) != 48:
            return None
        secs = struct.unpack("!I", data[40:44])[0]
        if secs < NTP_DELTA:  # 服务器返回异常时间戳（如 0）
            return None
        return secs - NTP_DELTA
    except (OSError, IndexError):
        return None


def syncRtc():
    # 从 NTP 获取 UTC 时间并写入 RTC（北京时间）。成功返回 True；失败返回 False 且不改动 RTC
    secs = getNtpUtcSeconds()
    if secs is None:
        log("NTP time sync failed, keep RTC unchanged.")
        return False
    local = utime.gmtime(secs + TZ_OFFSET_SECONDS)
    # RTC datetime 格式: (year, month, day, weekday, hour, minute, second, subsecond)
    rtc = machine.RTC()
    rtc.datetime((local[0], local[1], local[2], local[6] + 1,
                  local[3], local[4], local[5], 0))
    log("NTP time sync success, RTC set to {:04d}-{:02d}-{:02d} {:02d}:{:02d}:{:02d}".format(
        local[0], local[1], local[2], local[3], local[4], local[5]))
    return True
