# 全局日志工具：为所有日志输出添加格式化日期时间前缀
# 时间来源：ESP32 系统时钟。NTP 对时成功前显示 1970 起算的默认时间，
# 对时成功后自动变为北京时间，调用方无需感知（见 domain/ntpSync.py）
import utime


def _timeString():
    t = utime.localtime()
    return "{:04d}-{:02d}-{:02d} {:02d}:{:02d}:{:02d}".format(
        t[0], t[1], t[2], t[3], t[4], t[5])


def log(*args):
    print("[{}]".format(_timeString()), *args)
