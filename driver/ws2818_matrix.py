# ws2818_matrix.py — 8x8 WS2818 矩阵硬件抽象层
# 协议与 WS2812 相同（单线 800kHz，24-bit GRB），MicroPython neopixel 模块直接驱动。
from machine import Pin
import neopixel


class WS2818Matrix:
    """8x8 WS2818 矩阵封装。提供坐标 API + 蛇形走线映射 + HSV 颜色 + 全局亮度。

    用法:
        m = WS2818Matrix(47, 8, 8)
        m.set_xy(0, 0, (255, 0, 0))   # 左上角红点
        m.fill((0, 0, 0))             # 清屏
        m.show()
    """

    def __init__(self, pin, width=8, height=8, serpentine=True, rotation=0):
        self.w = width
        self.h = height
        self._serpentine = serpentine
        self._rotation = rotation % 360
        self._np = neopixel.NeoPixel(Pin(pin), width * height)
        self._brightness = 1.0

    # ---------- 坐标映射 ----------
    def _rotate(self, x, y):
        """按旋转角度变换 (x, y)。rotation: 0/90/180/270 度顺时针。"""
        r = self._rotation
        if r == 0:
            return x, y
        if r == 90:
            return self.h - 1 - y, x
        if r == 180:
            return self.w - 1 - x, self.h - 1 - y
        # 270
        return y, self.w - 1 - x

    def _index(self, x, y):
        """(x, y) → 线性索引。蛇形走线：偶数行左→右，奇数行右→左。"""
        x, y = self._rotate(x, y)
        if self._serpentine and (y & 1):
            return y * self.w + (self.w - 1 - x)
        return y * self.w + x

    # ---------- 像素操作 ----------
    def set_xy(self, x, y, color):
        if 0 <= x < self.w and 0 <= y < self.h:
            self._np[self._index(x, y)] = self._scale(color)

    def get_xy(self, x, y):
        if 0 <= x < self.w and 0 <= y < self.h:
            return self._np[self._index(x, y)]
        return (0, 0, 0)

    def fill(self, color):
        c = self._scale(color)
        buf = self._np
        for i in range(self.w * self.h):
            buf[i] = c

    def clear(self):
        self.fill((0, 0, 0))

    def show(self):
        self._np.write()

    # ---------- 全局亮度 ----------
    @property
    def brightness(self):
        return self._brightness

    @brightness.setter
    def brightness(self, value):
        self._brightness = max(0.0, min(1.0, float(value)))

    def _scale(self, color):
        if self._brightness >= 1.0:
            return color
        b = self._brightness
        return (int(color[0] * b), int(color[1] * b), int(color[2] * b))

    # ---------- 颜色工具 ----------
    @staticmethod
    def hsv_to_rgb(h, s, v):
        """HSV → RGB。h: 0-360, s: 0-1, v: 0-1。返回 (r, g, b) 0-255。"""
        h = h % 360.0
        s = max(0.0, min(1.0, s))
        v = max(0.0, min(1.0, v))
        c = v * s
        x = c * (1 - abs((h / 60.0) % 2 - 1))
        m = v - c
        if h < 60:
            r, g, b = c, x, 0
        elif h < 120:
            r, g, b = x, c, 0
        elif h < 180:
            r, g, b = 0, c, x
        elif h < 240:
            r, g, b = 0, x, c
        elif h < 300:
            r, g, b = x, 0, c
        else:
            r, g, b = c, 0, x
        return (int((r + m) * 255), int((g + m) * 255), int((b + m) * 255))
