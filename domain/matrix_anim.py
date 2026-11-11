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


class Comet(Animation):
    """彗星：明亮头部 + 渐隐拖尾，横向来回扫描。"""

    def __init__(self, speed=0.02):
        self.speed = speed
        self.x = 0.0
        self.dir = 1
        self.t = 0.0

    def update(self, dt_ms):
        self.x += self.dir * self.speed * dt_ms
        if self.x >= 7:
            self.x = 7
            self.dir = -1
        elif self.x <= 0:
            self.x = 0
            self.dir = 1
        self.t += dt_ms * 0.05

    def draw(self, matrix):
        matrix.fill((0, 0, 0))
        h = (self.t * 10) % 360
        head = int(round(self.x))
        # 头部白色
        matrix.set_xy(head, 3, (255, 255, 255))
        matrix.set_xy(head, 4, (255, 255, 255))
        # 拖尾
        for i in range(1, 8):
            tx = head - self.dir * i
            if 0 <= tx < 8:
                b = int(255 * (1 - i / 8))
                c = WS2818Matrix.hsv_to_rgb(h, 1.0, 1.0)
                matrix.set_xy(tx, 3, (int(c[0] * b / 255), int(c[1] * b / 255), int(c[2] * b / 255)))
                matrix.set_xy(tx, 4, (int(c[0] * b / 255), int(c[1] * b / 255), int(c[2] * b / 255)))


class Sparkle(Animation):
    """星光闪烁：随机像素亮起并渐隐。"""

    def __init__(self, count=12):
        self.pixels = []
        for _ in range(count):
            self.pixels.append({"x": urandom.getrandbits(3), "y": urandom.getrandbits(3),
                                 "hue": urandom.getrandbits(8) * 360 / 256,
                                 "phase": urandom.getrandbits(8) / 256.0 * 6.28})

    def update(self, dt_ms):
        for p in self.pixels:
            p["phase"] += dt_ms * 0.005

    def draw(self, matrix):
        matrix.fill((0, 0, 0))
        for p in self.pixels:
            v = (math.sin(p["phase"]) + 1) / 2  # 0~1
            if v > 0.1:
                b = int(v * 255)
                c = WS2818Matrix.hsv_to_rgb(p["hue"], 1.0, 1.0)
                matrix.set_xy(p["x"], p["y"], (int(c[0] * b / 255), int(c[1] * b / 255), int(c[2] * b / 255)))


class Snake(Animation):
    """贪吃蛇：蛇身沿蛇形路径游走，带渐隐拖尾。"""

    def __init__(self, speed=0.015):
        self.speed = speed
        self.pos = 0
        self.segments = []
        self.reset()

    def reset(self):
        self.pos = 0
        self.segments = [0]

    def update(self, dt_ms):
        self.pos += self.speed * dt_ms
        idx = int(self.pos)
        if idx >= 64:
            self.pos = 0
            idx = 0
        self.segments.append(idx)
        if len(self.segments) > 8:
            self.segments.pop(0)

    def _idx_to_xy(self, idx):
        row = idx // 8
        col = idx % 8
        if row % 2 == 1:
            col = 7 - col
        return col, row

    def draw(self, matrix):
        matrix.fill((0, 0, 0))
        for i, s in enumerate(self.segments):
            x, y = self._idx_to_xy(s)
            b = int(255 * (i + 1) / len(self.segments))
            h = (s * 6) % 360
            c = WS2818Matrix.hsv_to_rgb(h, 1.0, 1.0)
            matrix.set_xy(x, y, (int(c[0] * b / 255), int(c[1] * b / 255), int(c[2] * b / 255)))


class Starburst(Animation):
    """星爆：从中心向外辐射的光线，旋转。"""

    def __init__(self, rays=6, speed=0.003):
        self.rays = rays
        self.speed = speed
        self.t = 0.0

    def update(self, dt_ms):
        self.t += dt_ms * self.speed

    def draw(self, matrix):
        matrix.fill((0, 0, 0))
        t = self.t
        for y in range(8):
            for x in range(8):
                dx = x - 3.5
                dy = y - 3.5
                if dx == 0 and dy == 0:
                    matrix.set_xy(x, y, (255, 255, 255))
                    continue
                angle = math.atan2(dy, dx) + t
                dist = (dx * dx + dy * dy) ** 0.5
                v = math.sin(angle * self.rays) * math.sin(dist * 0.8 - t * 5)
                if v > 0:
                    h = (angle * 60 + t * 50) % 360
                    b = int(v * 255)
                    c = WS2818Matrix.hsv_to_rgb(h, 1.0, 1.0)
                    matrix.set_xy(x, y, (int(c[0] * b / 255), int(c[1] * b / 255), int(c[2] * b / 255)))


class Checkerboard(Animation):
    """棋盘格：颜色随时间循环的国际象棋棋盘。"""

    def __init__(self, speed=0.05):
        self.speed = speed
        self.t = 0.0

    def update(self, dt_ms):
        self.t += dt_ms * self.speed

    def draw(self, matrix):
        for y in range(8):
            for x in range(8):
                if (x + y) % 2 == 0:
                    h = self.t % 360
                    matrix.set_xy(x, y, WS2818Matrix.hsv_to_rgb(h, 1.0, 1.0))
                else:
                    h = (self.t + 180) % 360
                    matrix.set_xy(x, y, WS2818Matrix.hsv_to_rgb(h, 1.0, 1.0))


class Cyclon(Animation):
    """赛隆之眼：一个发光点来回扫描，带辉光拖尾。"""

    def __init__(self, speed=0.025):
        self.speed = speed
        self.x = 0.0
        self.dir = 1
        self.t = 0.0

    def update(self, dt_ms):
        self.x += self.dir * self.speed * dt_ms
        if self.x >= 7:
            self.x = 7
            self.dir = -1
        elif self.x <= 0:
            self.x = 0
            self.dir = 1
        self.t += dt_ms

    def draw(self, matrix):
        matrix.fill((0, 0, 0))
        cx = int(round(self.x))
        for x in range(8):
            dist = abs(x - cx)
            b = max(0, int(255 * (1 - dist / 4)))
            if b > 10:
                matrix.set_xy(x, 3, (b, 0, 0))
                matrix.set_xy(x, 4, (b, 0, 0))
                if dist == 0:
                    matrix.set_xy(x, 3, (255, 100, 100))
                    matrix.set_xy(x, 4, (255, 100, 100))


class Spiral(Animation):
    """旋转螺旋：从中心向外的螺旋线随时间旋转。"""

    def __init__(self, speed=0.004):
        self.speed = speed
        self.t = 0.0

    def update(self, dt_ms):
        self.t += dt_ms * self.speed

    def draw(self, matrix):
        matrix.fill((0, 0, 0))
        t = self.t
        for y in range(8):
            for x in range(8):
                dx = x - 3.5
                dy = y - 3.5
                dist = (dx * dx + dy * dy) ** 0.5
                angle = math.atan2(dy, dx)
                v = math.sin(dist * 1.5 - angle * 2 + t * 10)
                if v > 0.3:
                    h = (dist * 40 + t * 50) % 360
                    b = int((v - 0.3) / 0.7 * 255)
                    c = WS2818Matrix.hsv_to_rgb(h, 1.0, 1.0)
                    matrix.set_xy(x, y, (int(c[0] * b / 255), int(c[1] * b / 255), int(c[2] * b / 255)))


class Fire(Animation):
    """火焰：底部上升的火焰效果，红橙黄渐变。"""

    def __init__(self, speed=0.05):
        self.speed = speed
        self.t = 0.0
        self.heat = [[0.0] * 8 for _ in range(8)]

    def update(self, dt_ms):
        self.t += dt_ms * self.speed
        # 底部加热
        for x in range(8):
            self.heat[7][x] = urandom.random() * 0.8 + 0.2
        # 向上传播并冷却
        for y in range(7):
            for x in range(8):
                spread = (self.heat[y + 1][(x - 1) & 7] + self.heat[y + 1][x] +
                          self.heat[y + 1][(x + 1) & 7]) / 3
                self.heat[y][x] = max(0.0, spread - 0.08)

    def draw(self, matrix):
        for y in range(8):
            for x in range(8):
                h = self.heat[y][x]
                if h < 0.05:
                    matrix.set_xy(x, y, (0, 0, 0))
                elif h < 0.3:
                    matrix.set_xy(x, y, (int(h * 850), 0, 0))  # 暗红
                elif h < 0.6:
                    matrix.set_xy(x, y, (255, int((h - 0.3) * 600), 0))  # 橙
                else:
                    matrix.set_xy(x, y, (255, 180 + int((h - 0.6) * 200), int((h - 0.6) * 600)))  # 黄白


class Heartbeat(Animation):
    """心跳：心形图案以心跳节奏跳动。"""

    _HEART = [
        (2, 1), (3, 1), (4, 1), (5, 1),
        (1, 2), (2, 2), (3, 2), (4, 2), (5, 2), (6, 2),
        (1, 3), (2, 3), (3, 3), (4, 3), (5, 3), (6, 3),
        (2, 4), (3, 4), (4, 4), (5, 4),
        (3, 5), (4, 5),
        (3, 6), (4, 6),
    ]

    def __init__(self, period=1000):
        self.period = period
        self.t = 0

    def update(self, dt_ms):
        self.t = (self.t + dt_ms) % self.period

    def draw(self, matrix):
        matrix.fill((0, 0, 0))
        # 双跳心跳曲线
        phase = self.t / self.period
        if phase < 0.15:
            s = phase / 0.15
        elif phase < 0.3:
            s = 1 - (phase - 0.15) / 0.15
        elif phase < 0.4:
            s = 0.3
        elif phase < 0.5:
            s = 0.3 + (phase - 0.4) / 0.1 * 0.7
        elif phase < 0.6:
            s = 1 - (phase - 0.5) / 0.1
        else:
            s = 0.2
        b = int(255 * s)
        for (x, y) in self._HEART:
            matrix.set_xy(x, y, (b, 0, int(b * 0.3)))


class Rings(Animation):
    """涟漪环：从中心向外扩散的同心圆环。"""

    def __init__(self, speed=0.02):
        self.speed = speed
        self.t = 0.0

    def update(self, dt_ms):
        self.t += dt_ms * self.speed

    def draw(self, matrix):
        matrix.fill((0, 0, 0))
        t = self.t
        for y in range(8):
            for x in range(8):
                dx = x - 3.5
                dy = y - 3.5
                dist = (dx * dx + dy * dy) ** 0.5
                # 多个环以不同速度扩散
                v1 = math.sin(dist * 1.5 - t * 6)
                v2 = math.sin(dist * 1.0 - t * 4 + 2)
                v = max(v1, v2)
                if v > 0.5:
                    h = (dist * 50 + t * 30) % 360
                    b = int((v - 0.5) / 0.5 * 255)
                    c = WS2818Matrix.hsv_to_rgb(h, 1.0, 1.0)
                    matrix.set_xy(x, y, (int(c[0] * b / 255), int(c[1] * b / 255), int(c[2] * b / 255)))


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
        "comet": Comet,
        "sparkle": Sparkle,
        "snake": Snake,
        "starburst": Starburst,
        "checkerboard": Checkerboard,
        "cyclon": Cyclon,
        "spiral": Spiral,
        "fire": Fire,
        "heartbeat": Heartbeat,
        "rings": Rings,
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

    def update_params(self, brightness=None, speed=None, color=None):
        """实时更新亮度/速度/颜色，不重启当前动画或滚动文本。
        - brightness 同时写入矩阵驱动（所有动画共用）和 ScrollText 内部缓存
        - speed 仅对具备 speed 属性的动画生效（ScrollText 及大部分内置动画）
        - color 仅对 ScrollText 生效（内置动画有各自配色，不响应外部颜色）"""
        if brightness is not None:
            self.matrix.brightness = brightness
            if self._anim is not None and hasattr(self._anim, 'brightness'):
                self._anim.brightness = brightness
        if speed is not None:
            if self._anim is not None and hasattr(self._anim, 'speed'):
                self._anim.speed = speed
        if color is not None:
            if self._anim is not None and hasattr(self._anim, 'color'):
                self._anim.color = color

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
