# matrix_anim.py — 8x8 矩阵动画
# 遵循现有 FSM 架构：run() 由主循环驱动（与 lightFSM/fanFSM 同模式），不另起线程。
import math
import utime
import urandom
from driver.ws2818_matrix import WS2818Matrix


class Animation:
    def update(self, dt_ms):
        pass

    def draw(self, matrix):
        pass

    def reset(self):
        pass


class Rainbow(Animation):
    """彩虹流动 + 正弦波浪扭曲。"""

    def __init__(self, speed=100.0):
        self.speed = speed
        self.t = 0.0
        self._sin = math.sin

    def update(self, dt_ms):
        self.t += dt_ms * self.speed / 1000.0

    def draw(self, matrix):
        sin = self._sin
        t = self.t
        for y in range(8):
            for x in range(8):
                wave = sin((x + t * 0.05) * 0.8) * 30 + sin((y + t * 0.03) * 0.6) * 20
                h = (t + (x + y) * 22.5 + wave) % 360.0
                matrix.set_xy(x, y, WS2818Matrix.hsv_to_rgb(h, 1.0, 1.0))


class Breathing(Animation):
    """彩虹呼吸：颜色随色相循环，亮度正弦呼吸。"""

    def __init__(self, period=1800):
        self.period = period
        self.t = 0
        self.hue = 0.0

    def update(self, dt_ms):
        self.t = (self.t + dt_ms) % self.period
        self.hue = (self.hue + dt_ms * 0.08) % 360.0

    def draw(self, matrix):
        s = (1 - math.cos(2 * math.pi * self.t / self.period)) / 2
        s = s * s  # 平方曲线，呼吸感更强
        c = WS2818Matrix.hsv_to_rgb(self.hue, 1.0, 1.0)
        matrix.fill((int(c[0] * s), int(c[1] * s), int(c[2] * s)))


class BouncingDot(Animation):
    """发光弹跳球 + 拖尾。"""

    def __init__(self, color=(255, 255, 255), speed=0.018):
        self.color = color
        self.speed = speed
        self.trail = []
        self.reset()

    def reset(self):
        self.x = 0.0
        self.y = 0.0
        self.dx = self.speed
        self.dy = self.speed * 0.7
        self.trail = []

    def update(self, dt_ms):
        self.x += self.dx * dt_ms
        self.y += self.dy * dt_ms
        bounced = False
        if self.x <= 0:
            self.x = 0
            self.dx = abs(self.dx)
            bounced = True
        elif self.x >= 7:
            self.x = 7
            self.dx = -abs(self.dx)
            bounced = True
        if self.y <= 0:
            self.y = 0
            self.dy = abs(self.dy)
            bounced = True
        elif self.y >= 7:
            self.y = 7
            self.dy = -abs(self.dy)
            bounced = True
        self.trail.append((int(round(self.x)), int(round(self.y)), 0 if bounced else 1))
        if len(self.trail) > 6:
            self.trail.pop(0)

    def draw(self, matrix):
        matrix.fill((0, 0, 0))
        # 拖尾渐变
        for i, (tx, ty, _) in enumerate(self.trail):
            b = int(255 * (i + 1) / len(self.trail) * 0.4)
            matrix.set_xy(tx, ty, (b, b, b))
        # 主球（碰撞时闪白）
        head = self.trail[-1]
        if head[2] == 0:
            matrix.set_xy(head[0], head[1], (255, 255, 255))
        else:
            ix, iy = int(round(self.x)), int(round(self.y))
            matrix.set_xy(ix, iy, self.color)


class Plasma(Animation):
    """等离子：多正弦波叠加的彩色流动。"""

    def __init__(self, speed=0.004):
        self.speed = speed
        self.t = 0.0
        self._sin = math.sin

    def update(self, dt_ms):
        self.t += dt_ms * self.speed

    def draw(self, matrix):
        sin = self._sin
        t = self.t
        for y in range(8):
            for x in range(8):
                v = (sin(x * 0.8 + t) + sin(y * 0.8 + t * 1.3) +
                     sin((x + y) * 0.5 + t * 0.7) +
                     sin((x * x + y * y) ** 0.5 * 0.5 + t * 1.5))
                h = (v * 60 + 180) % 360
                matrix.set_xy(x, y, WS2818Matrix.hsv_to_rgb(h, 1.0, 1.0))


class GameOfLife(Animation):
    """康威生命游戏，随机初始，环面边界。"""

    def __init__(self, gen_interval=350):
        self.gen_interval = gen_interval
        self.reset()

    def reset(self):
        self._grid = [[urandom.getrandbits(1) for _ in range(8)] for _ in range(8)]
        self._acc = 0

    def _evolve(self):
        g = self._grid
        new = [[0] * 8 for _ in range(8)]
        for y in range(8):
            for x in range(8):
                n = 0
                for dy in (-1, 0, 1):
                    for dx in (-1, 0, 1):
                        if dx == 0 and dy == 0:
                            continue
                        n += g[(y + dy) & 7][(x + dx) & 7]
                if g[y][x]:
                    new[y][x] = 1 if n in (2, 3) else 0
                else:
                    new[y][x] = 1 if n == 3 else 0
        alive = sum(sum(r) for r in new)
        self._grid = new if alive > 0 else [[urandom.getrandbits(1) for _ in range(8)] for _ in range(8)]

    def update(self, dt_ms):
        self._acc += dt_ms
        if self._acc >= self.gen_interval:
            self._acc -= self.gen_interval
            self._evolve()

    def draw(self, matrix):
        for y in range(8):
            for x in range(8):
                if self._grid[y][x]:
                    # 青绿色，带一点亮度变化
                    matrix.set_xy(x, y, (0, 255, 120))
                else:
                    matrix.set_xy(x, y, (0, 0, 0))


class Rain(Animation):
    """彩色流星雨，带拖尾。"""

    def __init__(self, drop_count=10, speed=0.025):
        self.drops = []
        for _ in range(drop_count):
            self.drops.append({
                "x": urandom.getrandbits(3),
                "y": -urandom.getrandbits(4),
                "speed": speed * (0.5 + urandom.random()),
                "hue": urandom.getrandbits(8) * 360 / 256,
                "trail": [],
            })

    def reset(self):
        for d in self.drops:
            d["x"] = urandom.getrandbits(3)
            d["y"] = -urandom.getrandbits(4)
            d["hue"] = urandom.getrandbits(8) * 360 / 256
            d["trail"] = []

    def update(self, dt_ms):
        for d in self.drops:
            d["y"] += d["speed"] * dt_ms
            iy = int(d["y"])
            d["trail"].append(iy)
            if len(d["trail"]) > 3:
                d["trail"].pop(0)
            if d["y"] > 8:
                d["x"] = urandom.getrandbits(3)
                d["y"] = -1
                d["hue"] = urandom.getrandbits(8) * 360 / 256
                d["trail"] = []

    def draw(self, matrix):
        matrix.fill((0, 0, 0))
        for d in self.drops:
            c = WS2818Matrix.hsv_to_rgb(d["hue"], 1.0, 1.0)
            for i, ty in enumerate(d["trail"]):
                if 0 <= ty < 8:
                    b = int((i + 1) / len(d["trail"]) * 255)
                    matrix.set_xy(d["x"], ty, (int(c[0] * b / 255), int(c[1] * b / 255), int(c[2] * b / 255)))


class MatrixRain(Animation):
    """数字雨（黑客帝国风格）：绿色字符雨下落。"""

    def __init__(self, columns=8, speed=0.03):
        self.columns = []
        for _ in range(columns):
            self.columns.append({
                "y": urandom.getrandbits(3) * -1,
                "speed": speed * (0.6 + urandom.random() * 0.8),
                "len": 2 + urandom.getrandbits(2),
            })

    def reset(self):
        for c in self.columns:
            c["y"] = urandom.getrandbits(3) * -1
            c["len"] = 2 + urandom.getrandbits(2)

    def update(self, dt_ms):
        for c in self.columns:
            c["y"] += c["speed"] * dt_ms
            if c["y"] - c["len"] > 8:
                c["y"] = -c["len"]
                c["speed"] = 0.03 * (0.6 + urandom.random() * 0.8)
                c["len"] = 2 + urandom.getrandbits(2)

    def draw(self, matrix):
        matrix.fill((0, 0, 0))
        for x, c in enumerate(self.columns):
            head = int(c["y"])
            for i in range(c["len"]):
                y = head - i
                if 0 <= y < 8:
                    if i == 0:
                        matrix.set_xy(x, y, (200, 255, 200))  # 头部亮白绿
                    else:
                        b = int(255 * (1 - i / c["len"]) * 0.8)
                        matrix.set_xy(x, y, (0, b, 0))  # 尾部渐暗绿


class Wave(Animation):
    """涟漪波：从中心向外扩散的彩色波纹。"""

    def __init__(self, speed=0.012):
        self.speed = speed
        self.t = 0.0
        self._sin = math.sin

    def update(self, dt_ms):
        self.t += dt_ms * self.speed

    def draw(self, matrix):
        sin = self._sin
        t = self.t
        for y in range(8):
            for x in range(8):
                dx = x - 3.5
                dy = y - 3.5
                dist = (dx * dx + dy * dy) ** 0.5
                v = sin(dist * 1.2 - t * 8)
                h = (v * 120 + 200) % 360  # 青蓝紫范围
                bright = (v + 1) / 2
                c = WS2818Matrix.hsv_to_rgb(h, 1.0, bright)
                matrix.set_xy(x, y, c)


class ScrollText(Animation):
    """文本滚动：5x8 字符，从右向左循环滚动。"""

    def __init__(self, text="", speed=20, color=(0, 255, 120), brightness=1.0):
        from driver import matrix_font
        self._font = matrix_font
        self.set_text(text)
        self.speed = speed
        self.color = color
        self.brightness = max(0.0, min(1.0, brightness))

    def set_text(self, text):
        # 将文本渲染为一个宽 buffer：每字符 5 列 + 1 列间距
        cols = []
        for ch in text:
            data = self._font.get_char(ch)
            cols.extend(data)
            cols.append(0x00)  # 字符间 1 列空白
        cols.extend([0x00] * 8)  # 尾部空白，让文字滚出屏幕
        self._cols = cols
        self._offset = 0

    def update(self, dt_ms):
        if not self._cols:
            return
        self._offset += dt_ms * self.speed / 1000.0
        if self._offset >= len(self._cols):
            self._offset = 0

    def _color_with_brightness(self):
        r, g, b = self.color
        br = self.brightness
        return (int(r * br), int(g * br), int(b * br))

    def draw(self, matrix):
        n = len(self._cols)
        if n == 0:
            matrix.fill((0, 0, 0))
            return
        off = int(self._offset)
        c = self._color_with_brightness()
        for x in range(8):
            col = self._cols[(off + x) % n]
            for y in range(8):
                if col & (1 << y):
                    matrix.set_xy(x, y, c)
                else:
                    matrix.set_xy(x, y, (0, 0, 0))


class MatrixAnim:
    """矩阵动画管理：run() 由主循环调用（与 FSM 同模式），内部按帧间隔刷新。"""

    _BUILTIN = {
        "rainbow": Rainbow,
        "breathing": Breathing,
        "bounce": BouncingDot,
        "plasma": Plasma,
        "life": GameOfLife,
        "rain": Rain,
        "matrix": MatrixRain,
        "wave": Wave,
    }

    def __init__(self, matrix, fps=24, brightness=0.7):
        self.matrix = matrix
        self.matrix.brightness = brightness
        self._interval = max(1, 1000 // fps)
        self._last = utime.ticks_ms()
        self._current = None
        self._anim = None

    def list(self):
        return list(self._BUILTIN.keys())

    def play(self, name):
        if name in self._BUILTIN:
            self._anim = self._BUILTIN[name]()
            self._current = name

    def scroll_text(self, text, color=(0, 255, 120), brightness=1.0, speed=20):
        """以滚动文本模式播放（5x8 字符）。"""
        self._anim = ScrollText(text, speed=speed, color=color, brightness=brightness)
        self._current = "text"

    def current(self):
        return self._current

    def stop(self):
        self._anim = None
        self._current = None
        self.matrix.clear()
        self.matrix.show()

    def run(self):
        """主循环每轮调用；按帧间隔决定是否刷新。"""
        if self._anim is None:
            return
        now = utime.ticks_ms()
        dt = utime.ticks_diff(now, self._last)
        if dt < self._interval:
            return
        self._last = now
        try:
            self._anim.update(dt)
            self._anim.draw(self.matrix)
            self.matrix.show()
        except Exception as e:
            from domain.LogUtils import log
            log("[ERROR] matrix animation failed: {}".format(e))
