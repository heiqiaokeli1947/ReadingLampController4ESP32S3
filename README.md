# ReadingLampController4ESP32S3

[![Platform](https://img.shields.io/badge/Platform-ESP32--S3-blue)](https://www.espressif.com/en/products/socs/esp32-s3)
[![Firmware](https://img.shields.io/badge/MicroPython-v1.29.0-blue)](https://micropython.org/download/ESP32_GENERIC_S3/)
[![Language](https://img.shields.io/badge/Language-MicroPython-2b5b84)](https://micropython.org/)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)
[![Status](https://img.shields.io/badge/Status-Hardware%20Verified-success)](#验证状态)

> 基于 **ESP32-S3** 的智能阅读台灯控制器，运行 **MicroPython**。旋钮调光调色温、水冷级联散热、8×8 WS2818 RGB 矩阵、WiFi Web 配置与实时监控。

---

## 目录

- [核心特性](#核心特性)
- [硬件引脚映射](#硬件引脚映射)
- [项目结构](#项目结构)
- [快速部署](#快速部署)
- [Web 接口](#web-接口)
- [旋钮控制](#旋钮控制)
- [散热系统](#散热系统)
- [RGB 矩阵](#rgb-矩阵)
- [架构设计](#架构设计)
- [文档](#文档)
- [验证状态](#验证状态)

---

## 核心特性

| 特性 | 说明 |
|------|------|
| 🎛️ **旋钮控制** | 旋转调亮度（±1%/格），按住旋转调色温，按键开关灯，顺时针增亮 |
| 💡 **双色温混光** | 暖黄 + 冷白 LED 独立 PWM，按色温比例分配亮度 |
| 📏 **功率校准** | 内置 23 点黄/白 LED 电流校准表，线性插值修正 PWM-亮度非线性 |
| 🌊 **平滑调光** | 全量程 2s 时间驱动渐变；旋钮单格小变化用 ease-out 平滑过渡，无突变 |
| 🌈 **8×8 RGB 矩阵** | WS2818 灯珠，18 种内置动画（彩虹/呼吸/等离子/生命游戏/火焰等）+ 5×8 字体滚动文本；亮度/速度/颜色运行中实时更新 |
| 🌀 **水冷级联散热** | 灯板温度驱动水泵（一级）→ 散热器出水口温度驱动风扇（二级） |
| 🌡️ **平滑调速** | EMA 温度滤波（α=0.25）+ ±1.5℃ 滞回带 + 25%/s 渐变限速，消除启停震荡 |
| 📊 **Web 监控** | 两 Tab SPA：监控（灯光控制 + 实时状态 + 温度趋势图）/ 设置（阈值/PWM/网络/矩阵/设备） |
| 🔌 **传感器预留** | BMP280 / HDC1080 / BH1750 / PMS5003 驱动已移植，当前未接入硬件 |

---

## 硬件引脚映射

| 类别 | 硬件 | 引脚 | 用途 |
|------|------|------|------|
| I²C | SoftI2C SCL | GPIO7 | LM75A 总线时钟（100 kHz，外置 2.2kΩ 上拉） |
| I²C | SoftI2C SDA | GPIO42 | LM75A 总线数据 |
| GPIO | LED_EN_A | GPIO3 | LED 电源使能 A（推挽，低=关） |
| GPIO | LED_EN_B | GPIO9 | LED 电源使能 B（推挽，低=关） |
| PWM | 风扇 | GPIO8 | 风扇转速（25 kHz） |
| PWM | 水泵 | GPIO18 | 水泵转速（25 kHz） |
| PWM | 暖黄 LED | GPIO17 | 暖黄光 PWM（25 kHz） |
| PWM | 冷白 LED | GPIO16 | 冷白光 PWM（25 kHz） |
| GPIO | 编码器 CLK | GPIO40 | 旋转编码器 A 相（IRQ 双边沿，内部上拉） |
| GPIO | 编码器 DT | GPIO39 | 旋转编码器 B 相（IRQ 双边沿，内部上拉） |
| GPIO | 编码器 KEY | GPIO1 | 编码器按键（低有效，内部上拉） |
| 输出 | WS2812 LED | GPIO48 | RGB 状态指示 |
| 输出 | WS2818 矩阵 | GPIO47 | 8×8 RGB 矩阵（单线 800 kHz） |

**I²C 设备地址：** LM75A（散热器出水口）= `0x4A`，LM75A（灯板）= `0x4F`

---

## 项目结构

```
ReadingLampController4ESP32S3/
├── main.py                      # 主程序（Web 服务 + 主循环）
├── boot.py                      # 启动脚本
├── domain/                      # 业务逻辑层
│   ├── LightControllFSM.py      # 灯光控制状态机（旋钮+调光+校准）
│   ├── FanFSM.py                # 风扇控制状态机（EMA+滞回+渐变限速）
│   ├── PumpFSM.py               # 水泵控制状态机
│   ├── ThermalControlFSM.py     # 温控 FSM 基类（Fan/Pump 继承）
│   ├── matrix_anim.py           # WS2818 矩阵动画引擎（18 动画 + ScrollText）
│   ├── sensorData.py            # 全局传感器数据容器
│   ├── DBUtils.py               # BTree 数据库读写（线程锁串行化）
│   ├── wifi.py                  # WiFi 连接管理 + 复位式重连
│   ├── ntpSync.py               # NTP 网络对时（UTC+8）
│   ├── LogUtils.py              # 全局日志（带时间戳前缀）
│   └── ...
├── driver/                      # 驱动层
│   ├── bsp.py                   # 板级支持包（单例，硬件初始化）
│   ├── ws2818_matrix.py         # WS2818 8×8 RGB 矩阵驱动（RMT）
│   ├── matrix_font.py           # 5×8 字体（A-Z a-z 0-9 标点）
│   ├── lm75a.py                 # LM75A 温度传感器
│   └── bmp280.py / hdc1080.py / bh1750.py / pms5003.py  # 预留传感器
├── lib/                         # 第三方库
│   ├── microdot.py              # 轻量 HTTP 框架
│   └── rotary/                  # 旋转编码器 IRQ 驱动
├── static/                      # Web 前端资源
│   ├── index.html               # SPA 主页面
│   ├── spectre.min.css          # CSS 框架
│   ├── jquery.min.js            # jQuery
│   ├── chart.umd.js             # Chart.js 趋势图
│   └── sweetalert.min.js        # 弹窗提示
├── firmware/                    # MicroPython 固件
│   └── ESP32_GENERIC_S3-SPIRAM_OCT-20260824-v1.29.0.bin
└── Doc/                         # 设计文档
    └── DESIGN.md                # 完整设计文档
```

---

## 快速部署

### 1. 烧录 MicroPython 固件

```bash
# 使用 esptool 烧录（以 COM42 为例）
esptool.py --port COM42 --chip esp32s3 erase_flash
esptool.py --port COM42 --chip esp32s3 \
  write_flash -z 0x0 firmware/ESP32_GENERIC_S3-SPIRAM_OCT-20260824-v1.29.0.bin
```

### 2. 上传项目文件

```bash
# 安装 mpremote
pip install mpremote

# 上传全部文件（目录结构需保持）
mpremote connect COM42 fs cp boot.py :boot.py
mpremote connect COM42 fs cp main.py :main.py
mpremote connect COM42 fs cp -r domain :domain
mpremote connect COM42 fs cp -r driver :driver
mpremote connect COM42 fs cp -r lib :lib
mpremote connect COM42 fs cp -r static :static

# 重启设备
mpremote connect COM42 reset
```

### 3. 配置 WiFi

设备首次启动会开启 AP 热点（默认 `ReadingLamp_xxxx`），连接后访问 `http://192.168.4.1`，进入 **设置 → 网络设置** 扫描并配置 WiFi，保存后设备自动连接到路由器。

> 局域网内也可通过串口查看设备获取的 IP：`mpremote connect COM42 exec "import network; print(network.WLAN(network.STA_IF).ifconfig()[0])"`

### 4. 访问 Web 界面

浏览器打开 `http://<设备IP>/`，默认设备密码 `pengping`。

---

## Web 接口

所有接口需校验 `devicepwd`（通过 query 或 body 传递）。

| 路由 | 功能 |
|------|------|
| `GET /` | 返回 index.html（gzip 压缩） |
| `GET /status` | `mode=get` 查询全部状态；`mode=set` 设置参数 |
| `GET /scanap` | 扫描附近 WiFi AP |
| `GET /setwifi` | 配置 WiFi（ssid/pwd 等必填参数校验） |
| `GET /matrix` | 矩阵控制：`list` / `set` / `scroll` / `off` / `update` |
| `GET /reset` | 恢复出厂设置 |
| `GET /restart` | 重启设备 |

**示例：**

```bash
# 查询状态
curl "http://192.168.30.74/status?devicepwd=pengping&mode=get"

# 设置亮度 80%
curl "http://192.168.30.74/status?devicepwd=pengping&mode=set&brightness=80"

# 播放矩阵彩虹动画
curl "http://192.168.30.74/matrix?devicepwd=pengping&mode=set&name=rainbow"

# 滚动文本
curl "http://192.168.30.74/matrix?devicepwd=pengping&mode=scroll&text=Hello&color=%23ff0000&speed=50"
```

---

## 旋钮控制

| 操作 | 行为 |
|------|------|
| 旋转（不按键） | 亮度 ±1%/格，钳位 0-100% |
| 旋转（按住键） | 色温 ±1%/格（冷白占比 0-100%） |
| 按键按下 | 切换开关灯 |
| 关灯时旋转 | 仅同步基准值，不调节（避免开灯后跳变） |

调光采用时间驱动渐变：全量程 2s，`FADE_TIME_MS=2000`；旋钮单格小变化走 ease-out 平滑过渡，无突兀跳变。

---

## 散热系统

```
灯板 LM75A(0x4F) ──→ PumpFSM ──→ 水泵 PWM（一级散热，关灯后继续循环降温）
                                        │
                                        ▼
散热器出水口 LM75A(0x4A) ──→ FanFSM ──→ 风扇 PWM（二级散热，关灯即停）
```

**控制算法：** EMA 温度滤波（α=0.25）→ ±1.5℃ 滞回带消除临界震荡 → 25%/s 渐变限速防止转速突变。

---

## RGB 矩阵

**8×8 WS2818 矩阵**，数据脚 GPIO47，坐标映射 `rotation=90, serpentine=False`（经像素定位校准）。

**18 种内置动画：** `rainbow` `breathing` `bounce` `plasma` `life` `rain` `matrix` `wave` `comet` `sparkle` `snake` `starburst` `checkerboard` `cyclon` `spiral` `fire` `heartbeat` `rings`

**滚动文本：** 5×8 字体，支持自定义文本、颜色、滚动速度、整体亮度。

**运行中实时更新：** `update_params(brightness/speed/color)` 直接修改当前动画参数，**不重启**，画面无闪烁。Web 端亮度/速度/颜色滑动条变动即下发（120ms 节流）。

---

## 架构设计

```
浏览器 (index.html SPA, gzip)
         │ HTTP + JSON
         ▼
┌─────────────────────────────────────────────────────┐
│                   main.py (主程序)                   │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────┐ │
│  │  Web 线程 │ │  主循环   │ │ 定时任务  │ │ WiFi   │ │
│  │ Microdot │ │ 20Hz FSM │ │ GC/落盘  │ │ 重连   │ │
│  └────┬─────┘ └────┬─────┘ └──────────┘ └────────┘ │
└───────┼───────────┼─────────────────────────────────┘
        ▼           ▼
  ┌───────────────────────────────────────────────┐
  │              domain 业务层                     │
  │  LightControllFSM │ FanFSM │ PumpFSM          │
  │  (旋钮+调光+校准)   (二级散热) (一级散热)       │
  │  matrix_anim │ sensorData │ DBUtils │ wifi    │
  └───────────────────────┬───────────────────────┘
                          ▼
  ┌───────────────────────────────────────────────┐
  │           driver 驱动层 (BSP 单例)             │
  │  lm75a×2 │ RotaryIRQ │ GPIO │ PWM 4ch         │
  │  WS2812 │ WS2818 矩阵                          │
  └───────────────────────────────────────────────┘
```

**核心设计原则：代码稳定性优先。** 已完成硬件验证的代码进入维护模式，仅修复明确 Bug，不主动优化。

---

## 文档

| 文档 | 说明 |
|------|------|
| [Doc/DESIGN.md](Doc/DESIGN.md) | 完整设计文档：架构、引脚、FSM、Web API、安全性、测试规范 |
| [Doc/引脚迁移方案.md](Doc/引脚迁移方案.md) | WROOM-32 → ESP32-S3 引脚迁移记录 |

---

## 验证状态

| 功能 | 状态 | 说明 |
|------|------|------|
| 旋转编码器（亮度/色温 ±1%） | ✅ | 顺时针增亮，方向正确 |
| 编码器按键（开关灯） | ✅ | 短按切换，按住调色温 |
| WS2818 8×8 矩阵 | ✅ | 18 动画 + 滚动文本正常 |
| 矩阵参数实时更新 | ✅ | 亮度/速度/颜色实时下发，不重启 |
| 调光渐变 | ✅ | 旋钮单格有 ease-out 平滑过渡 |
| 系统总运行时间 | ✅ | 随本次运行时间累加，持久化到 DB |
| PWM 四通道 | ✅ | 风扇/水泵/暖黄/冷白占空比正常 |
| LM75A 双路温度 | ✅ | 0x4A/0x4F 读数正常 |
| WiFi Web 服务 | ✅ | 配置/监控/矩阵接口正常 |

---

## License

[MIT](LICENSE)
