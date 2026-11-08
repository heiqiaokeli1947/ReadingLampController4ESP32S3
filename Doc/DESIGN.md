# 阅读台灯控制器设计文档 (DESIGN.md)

> 本设计文档按当前代码实现刷新（2026-11-08），覆盖从 ESP32-WROOM-32 迁移至 ESP32-S3 后的完整形态，架构对齐 Aotomizer4ESP32S3 雾化器项目。所有结论均可由源码逐行佐证。

---

## 1. 项目概述

### 1.1 项目定位
基于 **ESP32-S3** 的智能阅读台灯控制器，运行 **MicroPython** 固件。核心功能：旋钮调节亮度/色温（暖黄+冷白双色 PWM 混光）、水冷级联散热（灯板温度驱动水泵 → 散热器出水口温度驱动风扇）、双路 LM75A 温度监测与平滑调速（EMA 滤波 + 滞回带 + 渐变限速）、WiFi Web 配置界面与实时监控。预留 BMP280/HDC1080/BH1750/PMS5003 传感器接口（驱动已移植，当前未接入硬件）。

### 1.2 核心特性

| 特性 | 说明 |
|------|------|
| 旋钮控制 | 旋转调亮度（0-100%），按住旋转调色温（0-100% 冷白占比），按键开关灯 |
| 双色温混光 | 暖黄 LED + 冷白 LED 独立 PWM，按色温比例分配亮度 |
| 功率校准 | 内置黄/白 LED 电流校准表，线性插值修正 PWM-亮度非线性 |
| 平滑调光 | 全量程 2s 的时间驱动渐变（`FADE_TIME_MS=2000`），开关灯/调亮度/调色温均无突变 |
| 风扇温控 | 散热器出水口 LM75A(0x4A) 温度线性映射风扇转速，二级散热，关灯即停 |
| 水泵温控 | 灯板 LM75A(0x4F) 温度线性映射水泵转速，一级散热，关灯后继续循环降温 |
| 平滑调速 | EMA 温度滤波（α=0.25）+ ±1.5℃ 滞回 + 25%/s 渐变限速，消除启停震荡与转速跳变 |
| Web 管理界面 | 单页应用，两 Tab：监控（首屏即灯光控制）/ 设置 |
| 设置防覆盖 | 设置页编辑后暂停自动回填 5s；保存失败立即用设备当前参数回填 |
| WiFi 双模式 | STA 连接 + AP 配网（300s 超时重启） |
| 断线自愈 | 复位式射频重连，后台线程不阻塞主循环 |
| 数据持久化 | BTree 数据库，线程锁串行化 |
| 状态指示 | WS2812 RGB LED（绿=在线/蓝=配网/红=断线） |
| 看门狗 | 活性检测式条件喂狗（主循环卡死 → WDT 复位） |
| NTP 对时 | 联网后校时 RTC 为北京时间，重试至成功 |
| 全局日志时间戳 | `log()` 带 `[YYYY-MM-DD HH:MM:SS]` 前缀 |

### 1.3 技术栈

| 类别 | 技术 |
|------|------|
| MCU | ESP32-S3-DevKitC-1 |
| 固件 | MicroPython（ESP32_GENERIC_S3-SPIRAM_OCT） |
| Web 框架 | Microdot（独立线程运行，32KB 栈） |
| 数据库 | ubtree (BTree) |
| 前端 | 原生 JS + jQuery + Spectre CSS + SweetAlert + Chart.js |
| 传感器协议 | I²C (LM75A ×2) |
| 输入 | 旋转编码器（CLK/DT IRQ + KEY） |
| 静态资源 | gzip 预压缩（总传输量 -73%） |

### 1.4 速记卡（关键参数）

| 项目 | 值 |
|------|-----|
| 通信协议 | HTTP/1.1 + JSON（GET 请求） |
| Web 端口 | 80 |
| 主循环频率 | 20 Hz（`sleep_ms(50)`） |
| 传感器采集 | 主循环时间驱动 1 Hz（BSP 内部节流） |
| WDT 超时 | 60 s，Timer(0) 每 15 s 条件喂狗 |
| I²C 速率 | 100 kHz（SoftI2C, GPIO7 SCL / GPIO42 SDA） |
| PWM 频率 | 25 kHz（风扇/水泵/暖黄/冷白） |
| NTP 服务器 | ntp.aliyun.com:123 |
| 配网 AP | `ReadingLamp`，密码 `APPwd` |

---

## 2. 目录结构

```
ReadingLampController4ESP32S3/
├── boot.py                    # 启动脚本（当前为空，可预留 WebREPL）
├── main.py                    # 主入口：Web 服务、FSM 调度、定时任务
├── mydb                       # BTree 数据库文件（运行时生成）
│
├── domain/                    # 业务逻辑层
│   ├── LightControllFSM.py    # 灯光控制状态机（旋钮+调光+校准）
│   ├── FanFSM.py              # 风扇控制状态机（EMA滤波+滞回+渐变限速）
│   ├── PumpFSM.py             # 水泵控制状态机（EMA滤波+滞回+渐变限速）
│   ├── sensorData.py          # 全局传感器数据容器（含预留字段）
│   ├── DBUtils.py             # BTree 数据库读写（线程锁串行化）
│   ├── wifi.py                # WiFi 连接管理 + 复位式重连
│   ├── ntpSync.py             # NTP 网络对时（北京时间 UTC+8）
│   ├── AACOps.py              # 湿球温度计算（预留，当前未接入温湿度）
│   ├── LogUtils.py            # 全局日志（log() 带时间戳前缀）
│   └── fileUtils.py           # 文件工具
│
├── driver/                    # 驱动层
│   ├── bsp.py                 # 板级支持包（单例，硬件初始化与访问）
│   ├── lm75a.py               # LM75A 温度传感器（I²C 0x4A/0x4F）
│   ├── bmp280.py              # BMP280 气压/温度（预留死代码）
│   ├── hdc1080.py             # HDC1080 温湿度（预留死代码）
│   ├── bh1750.py              # BH1750 光照（预留死代码）
│   └── pms5003.py             # PMS5003 PM2.5（预留死代码）
│
├── lib/                       # 第三方库
│   ├── microdot.py            # 轻量级 Web 框架
│   └── rotary/                # 旋转编码器库
│       ├── rotary.py          # 平台无关状态机
│       └── rotary_irq_esp.py  # ESP32/S3 硬件 IRQ 适配
│
├── static/                    # 前端静态资源（含 .gz 预压缩版）
│   ├── index.html             # 主页面（单文件 SPA）
│   ├── jquery.min.js[.gz]     # jQuery
│   ├── spectre.min.css[.gz]   # Spectre CSS
│   ├── sweetalert.min.js[.gz] # 弹窗组件
│   ├── chart.umd.js[.gz]      # 图表组件
│   └── favicon.ico[.gz]
│
└── Doc/                       # 文档
    ├── DESIGN.md              # 本设计文档
    └── 引脚迁移方案.md         # WROOM-32 → S3 引脚映射详情
```

---

## 3. 硬件资源与引脚分配

### 3.0 水冷级联散热拓扑

**关键结构：水泵串联在水路中间，不是与灯板/散热器并列的外设。** 灯板与散热器通过闭合水路连接，水泵负责驱动冷却液循环。

```
   ┌──────────────┐   冷却液流出   ┌──────────────┐
   │   LED 灯板    │ ───────────▶ │   循环水泵     │
   │  LM75A 0x4F  │  （热源侧）    │  pumpPwm G18  │
   └──────▲───────┘               └──────┬───────┘
          │                              │ 泵入散热器
          │ 冷却液回流                     ▼
          │                     ┌──────────────────┐
          └─────────────────────│   水冷散热器      │
                                │  LM75A 0x4A      │
                                │  （出水口侧测温）  │
                                │  风扇 fanPwm G8  │
                                └────────┬─────────┘
                                         │ 被动放热不足时强制对流
                                         ▼
                                     环境空气
```

**级联散热的分层响应：**

| 层级 | 传感器 | 执行器 | 启动条件 | 停机条件 |
|------|--------|--------|----------|----------|
| 一级：主动循环 | LM75A 0x4F（灯板） | 水泵（GPIO18） | 灯板温度 ≥ `LEDLThreshold`(35) | 灯板温度 ≤ `LEDLThreshold` − 1.5（关灯后仍继续循环至降温） |
| 二级：强制风冷 | LM75A 0x4A（散热器出水口） | 风扇（GPIO8） | 出水口温度 ≥ `fanLThreshold`(30) | 出水口温度 ≤ `fanLThreshold` − 1.5，**或关灯立即停转**（避免风扇噪音） |

**设计说明：**

- **为什么 0x4A 装在出水口侧**：出水口温度 = 散热器放热之后的冷却液温度，它偏高说明散热器"被动散热已经不够"，正好对应风扇的启动条件。放在进水口侧无法反映散热器的放热能力。
- **级联是物理耦合，代码无需显式串联**：灯板热量 → 水路 → 散热器 → 空气。代码里两个 FSM 各管各的传感器，联动由热力学自然形成（灯板热 → 水泵转 → 散热器温度升高 → 风扇转）。
- **停机策略差异**：水泵关灯后继续跑（余热冷却，防止灯板温度回冲），风扇关灯立即停（噪音优先）。
- **故障安全**：任一路传感器读数失效（-9999）时，开灯状态下该路全速 100% 保护；关灯状态不空转。

### 3.1 引脚映射总表

| 类别 | 硬件 | 引脚 | 上下拉 | 用途 |
|------|------|------|--------|------|
| I²C | SoftI2C SCL | GPIO7 | 外置 2.2kΩ | LM75A 总线时钟，100 kHz |
| I²C | SoftI2C SDA | GPIO42 | 外置 2.2kΩ | LM75A 总线数据 |
| GPIO 输出 | LED_EN_A | GPIO3 | — | LED 电源使能 A（推挽，低=关） |
| GPIO 输出 | LED_EN_B | GPIO9 | — | LED 电源使能 B（推挽，低=关） |
| PWM 输出 | 风扇 | GPIO8 | — | 风扇转速，25 kHz |
| PWM 输出 | 水泵 | GPIO18 | — | 水泵转速，25 kHz |
| PWM 输出 | 暖黄 LED | GPIO17 | — | 暖黄光 PWM，25 kHz |
| PWM 输出 | 冷白 LED | GPIO16 | — | 冷白光 PWM，25 kHz |
| GPIO 输入 | 编码器 CLK | GPIO40 | PULL_UP | 旋转编码器 A 相（IRQ 双边沿） |
| GPIO 输入 | 编码器 DT | GPIO39 | PULL_UP | 旋转编码器 B 相（IRQ 双边沿） |
| GPIO 输入 | 编码器 KEY | GPIO1 | PULL_UP | 编码器按键，低有效 |
| 输出 | WS2812 LED | GPIO48 | — | RGB 状态指示（NeoPixel，RMT） |

**I²C 设备地址：** LM75A(散热器出水口)=0x4A，LM75A(灯板)=0x4F。

**死代码引脚（HardI2C，仅保留定义未实例化）：**

| 类别 | 硬件 | 引脚 | 用途 |
|------|------|------|------|
| I²C（死） | HardI2C SCL | GPIO2 | 原 BMP280/HDC1080 总线，当前未接入 |
| I²C（死） | HardI2C SDA | GPIO41 | 原 BMP280/HDC1080 总线，当前未接入 |

### 3.2 引脚分配合理性分析

**合理性结论：整体合理，无冲突；迁移改动量小（仅 4 根线移位），Strapping pin 已验证可用。**

| 维度 | 分析 |
|------|------|
| **迁移策略** | 物理位置优先：WROOM-32 位置 N → S3 位置 N，10 根线直接平移；4 根因 PSRAM(UART0 复用区)就近移位（详见 Doc/引脚迁移方案.md） |
| **ESP32-S3 有效范围** | 全部使用 GPIO 1-9 / 16-18 / 39-42 / 48 范围内的有效引脚，未使用 PSRAM 保留区（GPIO26-32）与 USB D+/D-（GPIO19/20） |
| **Strapping pin 注意** | ESP32-S3 Strapping 引脚为 GPIO0/3/45/46。本项目仅使用 GPIO3（LED_EN_A 推挽输出），雾化器项目已验证可作普通 GPIO，不影响启动；GPIO0/45/46 未使用，安全。**JTAG 引脚（GPIO39/40/41/42）非 Strapping**，作 GPIO 仅丧失 JTAG 调试能力：GPIO39/40 用于编码器、GPIO42 用于 I²C SDA、GPIO41 为死代码 HardI2C，均不影响上电启动 |
| **功能分组** | PWM 四通道集中在左列 GPIO8/16/17/18；编码器 CLK/DT 相邻（GPIO39/40）；I²C 分置两列（GPIO7 + GPIO42，与老项目一致）；LED_EN_A/B 分置两侧便于走电源 |
| **输入保护** | 编码器 CLK/DT/KEY 均内部上拉，断线=高=静止态，安全；按键低有效 |
| **I²C 上拉** | BSP 未启用内部上拉，依赖外置 2.2kΩ；100 kHz 稳定 |
| **资源占用** | GPIO 用 12 个（+2 死代码），PWM 用 4/8 通道（LEDC，剩余 4 通道可扩展），I²C 用 1（SoftI2C），Timer 用 2（0/3），WDT 1。剩余 GPIO、Timer 1/2、UART、ADC、SPI 均可扩展 |

**潜在改进点（非阻塞）：**
- PWM 当前用 4/8 LEDC 通道，剩余 4 通道可直接扩展；若需更多通道再考虑软件 PWM
- 编码器 KEY 占用 GPIO1，部分 S3 核心板 GPIO1 为 U0TXD，若接 USB-串口桥可能影响调试串口（不影响 WiFi 控制，硬件实测为准）

### 3.3 PWM 通道映射

| 通道 | 引脚 | 硬件 | 频率 | 占空比范围 |
|------|------|------|------|-----------|
| fanPwm | GPIO8 | 风扇 | `fanPwmFreq`(25k) | `fanPwmMin`~`fanPwmMax`(15~100%) |
| pumpPwm | GPIO18 | 水泵 | `pumpPwmFreq`(25k) | `pumpPwmMin`~`pumpPwmMax`(15~100%) |
| yellowPwm | GPIO17 | 暖黄 LED | `yellowPwmFreq`(25k) | `yellowPwmMin`~`yellowPwmMax`(15~100%) |
| whitePwm | GPIO16 | 冷白 LED | `whitePwmFreq`(25k) | `whitePwmMin`~`whitePwmMax`(15~100%) |

### 3.4 PWM 初始化与更新（内存安全 + 配置热更新）

`driver/bsp.py`：PWM 对象**仅首次 `setConfig()` 时构造**（`initHW()`），此后参数变更走 `updatePWM()` 原地更新，不重建对象：

```python
# initHW()：首次构造，duty=0
self._pwmChannels = {
    "fanPwm": PWM(Pin(8), freq=25000, duty=0),
    "pumpPwm": PWM(Pin(18), freq=25000, duty=0),
    "yellowPwm": PWM(Pin(17), freq=25000, duty=0),
    "whitePwm": PWM(Pin(16), freq=25000, duty=0),
}

# updatePWM()：仅更新频率，不改动占空比
# 占空比由各 FSM 在 reloadConfig 后通过 _configDirty 标记重新应用
for ch, key in (...):
    newFreq = int(self.config[key])
    if self._pwmFreq.get(ch) != newFreq:
        self._pwmChannels[ch].freq(newFreq)
        self._pwmFreq[ch] = newFreq
```

**关键设计**：`updatePWM` 不重置 duty 为 0，避免保存任意配置时把运行中的灯/风扇/水泵瞬断。FSM 通过 `_configDirty` 标记在下一轮强制重应用当前目标值（含新的 min/max）。

---

## 4. 系统架构

### 4.1 分层架构图

```
┌──────────────────────────────────────────────────────────────────┐
│                        main.py                                   │
│  ┌────────────┐  ┌───────────────┐  ┌─────────────────────────┐  │
│  │ Web 线程    │  │  FSM 调度      │  │ Timer + WDT + 定时任务  │  │
│  │ (32KB 栈)   │  │ (20Hz 主循环)   │  │ (时间驱动，与频率解耦)   │  │
│  └─────┬──────┘  └──────┬────────┘  └──────────┬──────────────┘  │
│        │                │                       │                 │
│        ▼                ▼                       ▼                 │
│  ┌───────────────────────────────────────────────────────────┐   │
│  │                    domain 业务层                           │   │
│  │  ┌─────────────────────────────────────────────────────┐   │   │
│  │  │         ThermalControlFSM (温控基类)                 │   │   │
│  │  │  EMA 滤波 + 滞回带 + 渐变限速 + 停机逻辑              │   │   │
│  │  └─────────────────────────────────────────────────────┘   │   │
│  │           ▲                    ▲                          │   │
│  │           │继承                │继承                      │   │
│  │  ┌────────┴────────┐  ┌───────┴────────┐                  │   │
│  │  │    FanFSM       │  │   PumpFSM      │                  │   │
│  │  │  (二级散热)      │  │  (一级散热)     │                  │   │
│  │  └─────────────────┘  └────────────────┘                  │   │
│  │  LightControllFSM │ sensorData │ DBUtils │ wifi │ ntpSync │   │
│  └──────────────────────────┬────────────────────────────────┘   │
│                             │                                    │
│                             ▼                                    │
│  ┌───────────────────────────────────────────────────────────┐   │
│  │              driver 驱动层 (BSP 单例)                       │   │
│  │  lm75a ×2 │ 编码器(RotaryIRQ) │ GPIO │ PWM 4ch │ WS2812    │   │
│  └──────────────────────────┬────────────────────────────────┘   │
│                             │                                    │
│                             ▼                                    │
│  ┌───────────────────────────────────────────────────────────┐   │
│  │                   ESP32-S3 硬件                            │   │
│  └───────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────┘
         │ HTTP + JSON
         ▼
┌──────────────────────────────────────────────────────────────────┐
│                 浏览器 (index.html SPA, gzip 压缩)               │
│  [监控] 灯光控制 · 状态 · 趋势   │  [设置] 阈值 · PWM · 网络 · 设备  │
└──────────────────────────────────────────────────────────────────┘
```

### 4.2 线程模型

| 线程 | 栈 | 职责 | 阻塞风险 |
|------|-----|------|----------|
| 主线程 | 默认 | 主循环（20Hz FSM + NTP + 定时任务） + Timer 回调 | `connectToWifi` 开机阻塞 ~36s（设计内） |
| Web 线程 | 32KB | Microdot HTTP 服务 | 静态文件流式发送 |
| WiFi 重连 | 默认 | `startReconnect` 射频复位（含 1s sleep） | 后台线程，不阻塞主循环 |

**线程安全：** 数据库操作通过 `dbLock` 串行化；FSM 与 BSP 仅主线程访问；传感器数据由主循环写、FSM/Web 读（无锁，依赖 MicroPython GIL 与标量原子性）；**配置热更新通过 `_pendingConfigReload` 标志在主线程上下文中执行 `reloadAllConfig`**，Web 线程只修改 `systemConfig` 字典并置标志，避免跨线程竞争修改 FSM/BSP 状态。

### 4.3 模块职责

| 模块 | 职责 | 运行周期 |
|------|------|----------|
| main.py | 主入口、Web 服务、FSM 调度、定时器 | 持续 |
| BSP | 硬件初始化、传感器读取、PWM/编码器/LED 控制 | 被调用 |
| LightControllFSM | 旋钮调光/调色温状态机 | 主循环 20Hz |
| FanFSM | 散热器出水温度调速状态机（EMA+滞回+限速） | 主循环 1Hz |
| PumpFSM | 水泵温度调速状态机（EMA+滞回+限速） | 主循环 1Hz |
| sensorData | 全局数据容器（含预留字段） | 被引用 |
| DBUtils | BTree 持久化（线程锁） | 被调用 |
| wifi | WiFi 连接 + 复位式重连 + AP | 后台 |
| ntpSync | SNTP 校时（北京时间） | 主循环轮询 |
| LogUtils | 全局日志 `log()` | 被调用 |

---

## 5. 核心模块详解

### 5.1 main.py — 主入口

**启动时序：**
```
boot → 加载配置(DB+默认合并) → 生成 deviceId → BSP 初始化 → FSM 初始化
  → WDT + Timer(0) 条件喂狗 → 启动 Web 线程 → 主循环 20Hz
```

**配置加载：** DB 值与 `defaultSystemConfig` 合并，老库缺字段取默认；JSON 损坏回退出厂默认；合并结果不落库（下次保存时持久化）。

**主循环（20Hz，`sleep_ms(50)`）：**
1. `updateAliveTick()` — 刷新活性时间戳，并统计主循环实测频率 `loopHz`（每 5s 一次）
2. `tryNtpSync()` — NTP 对时（联网后）
3. **`_pendingConfigReload` 检查** — 若 Web 线程已置位，在主线程上下文执行 `reloadAllConfig()`（避免跨线程竞态）
4. `lightFSM.run()` — 灯光 FSM（旋钮 20Hz 响应）
5. `fanFSMInstance.run()` — 风扇 FSM（1Hz）
6. `pumpFSMInstance.run()` — 水泵 FSM（1Hz）
7. `bspInstance.readSensors()` — LM75A 读取（1Hz，BSP 内部节流，含老化判定与总线自愈）
8. WiFi 断线重连（normal 模式每 30s，后台线程）
9. 定时任务（时间驱动）：GC 5min / LED 翻转 2s / 配置+系统总运行时间落盘 1h

**系统运行统计（main.py 主循环内）：**
- `runMs` — 本次上电运行毫秒数，每 tick 累加，输出 `runTime = runMs // 1000`
- `totalRunTimeMs` — 跨开机累计系统运行毫秒数，开机从 DB 键 `totalRunTime`（秒）恢复，每 tick 累加，随 1h 落盘任务写回 DB
- `powerOnCount` — 系统总上电次数，开机从 DB 读取后 +1 并立即写回 DB

**看门狗：** WDT 60s，Timer(0) 每 15s 回调 `feedDog`，仅当 `ticks_diff(now, lastAliveTick) < 30s` 时喂狗。主循环卡死 → 停止喂狗 → WDT 复位。

**Timer(3) 配置模式看门狗：** `createConfigTimer` 周期性检查是否应退出配置模式并重启（WiFi 连上 或 超时 300s）。定时器对象为单例，重复调用只重新 `init`，不会重复占用硬件定时器。

### 5.2 BSP — 板级支持包

**单例模式**（`__new__` + `_initialized` 防重复）。

**关键方法：**

| 方法 | 功能 |
|------|------|
| `setConfig(config)` / `initHW()` / `updatePWM()` | PWM 单次构造 + 原地更新频率（不重置 duty） |
| `readSensors()` | 1Hz 节流读取 LM75A；单次失败保留上次值；10s 老化置 -9999；连续 30 次失败重建 I²C 总线；全缺失 60s 重扫 |
| `recoverI2C()` | 重建 SoftI2C 并重新绑定 LM75A（总线锁死自愈路径） |
| `setPwm(ch, freq, min, max, percent, reverse)` | 0-1000 映射到 min~max 占空比，频率未变跳过 `freq()` |
| `enableLED(status)` | LED 电源使能 A+B 同步开关 |
| `setLEDArray(color)` | WS2812 RGB 颜色 |
| `getknob()` | 返回 (RotaryIRQ 对象, KEY 电平) |

**`setPwm` 占空比计算：**
```python
base = (minDuty / 100.0) * 1023          # 最小占空比对应计数值
full = (maxDuty - minDuty) / 100.0 * 1023 # 可调范围对应计数值
duty = full * (percent / 1000.0) + base   # 线性映射
```

**死传感器处理函数：** `bmp280TimerHandler` / `hdc1080TimerHandler` / `bh1750TimerHandler` / `pms5003TimerHandler` 均为 `pass` 桩，读取逻辑已注释，硬件接入后取消注释即可。

### 5.3 LightControllFSM — 灯光控制状态机

**执行流程：** INIT → 每 tick 顺序执行 `checkSystemEnableStatus()` → `processKnob()` → `fitPower()`。
`STATUS` 常量（INIT/READY/SYS_ENABLED/FIT_POWER）仅用于初始化判定，不再做状态轮转——三个环节都无副作用，每 tick 全跑才能保证每个 tick 都推进一次渐变步长（否则渐变总时长会被状态轮转放大数倍）。

**旋钮交互：**

| 操作 | 条件 | 行为 |
|------|------|------|
| 旋转（不按键） | `lastKnobValue != value` && `knobKey=1` && 灯开 | 亮度 ±2%/格，钳位 0-100 |
| 旋转（按住键） | `lastKnobValue != value` && `knobKey=0` && 灯开 | 色温 ±2%/格，钳位 0-100 |
| 按键按下（下降沿） | `lastKnobKey != knobKey` && `knobKey=0` | 切换开关灯 |
| 关灯时旋转 | 灯关 | 只同步 `lastKnobValue` 基准，不调节；否则开灯后首次旋转会按累积差值跳变 |

**色温混光：**
```
yellowBrightness = brightness * (100 - colorTemperature) / 100
whiteBrightness  = brightness * colorTemperature / 100
```
`colorTemperature=0` → 纯暖黄；`colorTemperature=100` → 纯冷白。

**功率校准：** 内置黄/白 LED 电流校准表（23 点），`calibratePower` 按目标电流线性插值反查 PWM 百分比，修正 LED 非线性。

**平滑调光：** 步长按时间计算，全量程（0→100%）固定 `FADE_TIME_MS=2000`：

```
step = 100 * 本次 tick 间隔(ms) / FADE_TIME_MS
*BrightnessTemp 向 *Brightness 逼近 step，剩余差值不足 step 时直接落到目标
```

主循环 20Hz 下每步约 2.5%，40 次走完全量程；因步长与频率解耦，即使主循环被阻塞、tick 间隔变大（如 300ms），也能在剩余时间内补上、总时长仍约 2s。`_offApplied` 标记避免关灯态重复写 PWM=0；`*BrightnessTemp` 通过 `yellowApplied`/`whiteApplied` 暴露到 `/status` 便于确认调光是否真正落到硬件。

**渐变耗时（按 2s 全量程折算，实测相符）：**

| 场景 | 变化量 | 耗时 |
|------|--------|------|
| 开关灯 / 滑块拉到另一端 | 100% | 2.0 s |
| 亮度 70 → 100 | 30% | 0.6 s |
| 旋钮单格 | 2% | 约 40 ms（视觉上即时响应） |

实测数据（亮度 0→100）：`t=1.1s 48.6%` → `t=1.7s 78.6%` → `t=2.33s 100%`（含 HTTP 往返约 0.3s），反向量程同样约 2s。

**开关灯一致性：** 无论旋钮按键还是 Web/接口关灯，都会把 `*BrightnessTemp` 清零。因为关灯分支会把 PWM 写 0，若中间值保留原亮度，再开灯时"中间值==目标值"就不会重写 PWM，灯将点不亮。

**参数持久化与开机记忆：** `brightness` 与 `colorTemperature` 均写入 btree 数据库（键名同名），下次开机从 DB 恢复：

| 字段 | Web 设置 | 旋钮调节 | 开机恢复 |
|------|----------|----------|----------|
| `colorTemperature` | `setColorTemperature` 即时写 DB | `saveData()` 变更检测写 DB（`lastColorTemperature` 比对，未变不写） | `__init__` 从 DB 读取，默认 50 |
| `brightness` | `setBrightness` 即时写 DB | `saveData()` 变更检测写 DB（`lastBrightness` 比对，未变不写） | `__init__` 从 DB 读取，默认 0 |

开灯时（`setOnOff(True)`）若 `brightness <= 0` 则兜底置 30，否则直接使用恢复值——实现"下次开机开灯即恢复上次关灯前亮度"。

**亮度滑到 0 的语义：** `setBrightness(0)` 等同于关灯：**调用 `setOnOff(False, auto=True)` 走完整关灯逻辑**，包括：置 `onOffStatus=False`、写 PWM=0、清零 `_continuousOnMs`、重置 `_eyeRemindActive`、清零 `_delayedOffPending`、立即落盘 `ledTotalRunTime`。这保证亮度滑块拉到底端时灯真正熄灭，且累计点亮时长、护眼提醒状态、延迟关灯倒计时全部正确清理，与旋钮/Web 关灯行为完全一致。`auto=True` 绕过延迟关灯倒计时（亮度为 0 即立即关灯）。

**历史 Bug（已修复）：** 原实现直接置 `onOffStatus=False` 而不调用 `setOnOff`，导致 `_continuousOnMs` 未清零、`_eyeRemindActive` 未重置、`ledTotalRunTime` 未落盘。修复后 `setBrightness(0)` 与手动关灯走同一路径。

**累计点亮时长：** `totalRunTimeMs` 仅在 `onOffStatus=True` 时累加（`run()` 中 `if self.onOffStatus: totalRunTimeMs += delta`），关灯时停止计时。该值持久化到 DB 键 `ledTotalRunTime`，采用**双触发落盘策略**降低 flash 磨损：
1. 定时节流：`saveData()` 中距上次保存 ≥ 60s 才写一次；
2. 关灯立即写：`setOnOff(False, auto=False/True)` 实际关灯时立即落盘，避免掉电丢失最后一段点亮时间。

另有 `ledRunTimeMs` 为本上电周期内的点亮时长，开机清零。

**延迟关灯：** 配置 `delayedOff`（0/1）+ `delayedOffTime`（3~300s）。开灯时记录 `_onSinceMs`，`run()` 中若 `delayedOff==1` 且开灯时长 ≥ `delayedOffTime`，自动调用 `setOnOff(False, auto=True)` 关灯。

**状态字段 `_delayedOffPending`：** 用户手动关灯且 `delayedOff==1` 时置位，表示"正在倒计时、到点再关"；实际关灯（`auto=True`）或 `delayedOff` 关闭时清零。`/status?mode=get` 返回 `delayedOffPending` 供前端显示倒计时状态。

**手动关灯行为：** Web 开关 / 旋钮按键在 `delayedOff==1` 时**不立即关灯**，而是重置 `_onSinceMs` 重新开始倒计时，到点后再由自动路径关灯；`delayedOff==0` 时手动关灯立即生效。`setOnOff` 的 `auto` 参数区分自动触发（实际关灯）与用户手动（延迟关灯开启时转为倒计时）。`delayedOff` 状态通过 `/status?mode=set` 持久化，监控页快捷场景区的「延迟关灯」按钮切换该状态。

**`delayedOff` 由关→开的跳变修复：** 若灯已亮且 `delayedOff` 从 0 切到 1，`run()` 中检测到 `delayed and not self._lastDelayedOff` 时重置 `_onSinceMs = runTimeCounterMs`，避免历史已亮时长立即触发自动关灯。注意 `self.config` 与 `systemConfig` 是同一 dict，Web 线程改值后主循环立即看到新值，因此跳变检测必须在 `run()` 内完成，不能只依赖 `reloadConfig`。

**视疲劳提醒：** 配置 `eyeRemindInterval`（0=关闭，5~60 分钟）。`run()` 中跟踪 `_continuousOnMs`（连续开灯时长，关灯清零），达到 `eyeRemindInterval` 后触发 10s 脉冲：`fitPower()` 用三角波因子（4 个周期 × 2.5s，亮度在当前值的 10%~100% 间振荡）缩放黄/白通道目标亮度，不修改用户设定的 `brightness`。脉冲期间**绕过 `FADE_TIME_MS=2000` 渐变**，直接将 PWM 输出设为调制后目标，否则 2s 渐变会压缩脉冲幅度使其几乎不可见。脉冲结束后 `_continuousOnMs` 清零，可再次触发。

**配置热更新：** `reloadConfig` 置 `_configDirty=True`，`fitPower` 强制重应用两路 PWM（用新的 min/max 重新计算 duty）。

### 5.4 ThermalControlFSM — 温控基类（新增）

**设计目的：** 消除 FanFSM 与 PumpFSM 间 95% 的重复代码。两个 FSM 仅在传感器源、阈值键、PWM 通道、停机条件上有差异，核心控制算法（EMA 滤波 + 滞回带 + 渐变限速 + 停机逻辑）完全一致。

**基类封装：** `domain/ThermalControlFSM.py` 提供完整的温控 FSM 实现，子类通过 `params` dict 注入差异点：

| 参数 | FanFSM | PumpFSM | 说明 |
|------|--------|---------|------|
| `name` | 'Fan' | 'Pump' | 日志标签 |
| `temp_getter` | `lambda: sensorData.LM75FanTemp` | `lambda: sensorData.LM75LedTemp` | 温度数据源 |
| `h_key` / `l_key` | fanHThreshold / fanLThreshold | LEDHThreshold / LEDLThreshold | 阈值配置键 |
| `pwm_ch` / `pwm_prefix` | fanPwm / fanPwm | pumpPwm / pumpPwm | PWM 通道与配置前缀 |
| `stop_when_light_off` | True | False | 关灯是否立即停转 |
| `run_time_db_key` | fanTotalRunTime | pumpTotalRunTime | 累计运行时长 DB 键 |
| `speed_key` / `temp_key` | fanSpeed / fanTemp | pumpSpeed / ledTemp | 状态字段名 |

**继承优势：**
- 改一处自动同步另一处（如修复限速逻辑、调整滤波系数）
- 每个子类仅 ~20 行（原 ~200 行），代码量减少 90%
- 新增温控设备时只需实例化基类并传入不同 params

### 5.5 FanFSM — 风扇控制状态机（二级散热）

继承自 `ThermalControlFSM`，差异点通过 `params` 注入。

**状态枚举：** INIT(0) → EVAL(1)（每 tick 评估温度并按限速调整 PWM）

**控制算法（EMA 滤波 + 滞回带 + 渐变限速）：**
- 散热器出水口温度（LM75A 0x4A，即被动放热后的冷却液温度）经 EMA 滤波（α=0.25）后用于决策
- 风扇属二级散热：只有散热器被动放热不足、出水口温度超阈值时才启动
- 目标转速线性映射：
  - `filteredTemp >= fanHThreshold` → 100%
  - `fanLThreshold + 1.5 < filteredTemp < fanHThreshold` → 线性插值
  - `filteredTemp <= fanLThreshold - 1.5` → 0%（停转）
  - 滞回带内（±1.5°C）保持当前目标转速，消除临界点震荡
- PWM 输出经渐变限速（25%/秒）平滑过渡，避免电流冲击
- 关灯立即停转（`getLightStatus()==False` 时直接写 PWM=0），避免风扇噪音
- 传感器失效（-9999）或 `fanHThreshold <= fanLThreshold` 时故障安全：全速 100%

**算法参数（`FanFSM.py` 模块常量，PumpFSM 同名同值）：**

| 常量 | 值 | 含义 |
|------|-----|------|
| `TEMP_FILTER_ALPHA` | 0.25 | 温度 EMA 滤波系数，约 4 次采样（4s）达到稳态，抑制单点毛刺 |
| `TEMP_HYSTERESIS` | 1.5 | 启停滞回带（℃），阈值附近不反复启停 |
| `SPEED_RATE_LIMIT` | 25.0 | 转速渐变限速（%/秒），PWM 平滑过渡、避免电流冲击 |

**内部字段命名（两个 FSM 对称）：**

| 字段 | 含义 |
|------|------|
| `rawFanTemp` / `rawLedTemp` | 传感器原始读数（未滤波，仅用于日志） |
| `filteredFanTemp` / `filteredLedTemp` | EMA 滤波后的温度，控制决策只用它 |
| `targetSpeed` | 温度映射得到的目标转速（0~100） |
| `appliedSpeed` | 经限速后的实际输出转速，写入 PWM 的就是它 |
| `lastPwmSpeed` | 上次写入 PWM 的值（-1 强制首次写入），用于去重避免重复写 |
| `lastSpeedAdjustMs` | 上次限速计算的单调时钟基准 |

**为何只有两态（而不是拆成一串状态）**：限速公式 `maxChange = 25%/s × 距上次调速的间隔` 依赖"每 tick 都算一次"。若把评估、过温、保速拆成多个状态轮流执行，一个调速周期就会跨 3 个 tick，间隔被放大到 3s，`maxChange` 随之变成 75%/tick，限速形同失效、转速仍会跳变。因此 INIT 之后只保留 EVAL 一态，每个 tick 都重新评估 + 限速。

**`applySpeedLimit` 的 elapsed 钳制（防主循环阻塞导致跳变）**：`elapsed = ticks_diff(runTimeCounterMs, lastSpeedAdjustMs)`。正常 1Hz tick 下 `elapsed ≈ 1000ms`，`maxChange = 25%`。但主循环被 GC（5min）、WiFi 射频重连、配置重载等阻塞时，`runTimeCounterMs` 会一次性累加 2~5s，导致 `elapsed` 异常增大、`maxChange` 超过 100，`appliedSpeed` 直接跳到 `targetSpeed`，PWM 突变。**修复：将 `elapsed` 钳制到 1500ms**（单 tick 最大变化 37.5%），保证即使主循环长时间阻塞，转速也按限速渐变。`lastSpeedAdjustMs` 每 tick 顶部刷新为当前 `runTimeCounterMs`，下一轮 `elapsed` 回归正常值。

### 5.6 PumpFSM — 水泵控制状态机（一级散热）

继承自 `ThermalControlFSM`，差异点通过 `params` 注入。

**与 FanFSM 的核心差异：** **不判断灯光状态**（`stop_when_light_off=False`），水泵串联在灯板与散热器之间，关灯后仍继续循环带走灯板余热，直到灯板温度降到 `LEDLThreshold - 1.5` 以下才停转（停机完全由温度决定）。

**传感器失效（-9999）时：** 开灯全速保护，关灯不空转。

**水泵停机时的 `lastSpeedAdjustMs` 复位（与风扇的差异）**：风扇关灯时每 tick 走 `setDeviceToReadyStatus()`，该函数会把 `lastSpeedAdjustMs` 刷新为当前 `runTimeCounterMs`，因此风扇重新启动时 `elapsed` 总是约 1 个 tick。水泵正常运行中不调用 `setDeviceToReadyStatus`，仅靠 `applySpeedLimit` 顶部的 `lastSpeedAdjustMs = runTimeCounterMs` 刷新。为保证水泵停机后再次启动时也能从小步长平滑爬升，`applySpeedLimit` 末尾追加：当 `targetSpeed == 0 and appliedSpeed == 0` 时，再次确认 `lastSpeedAdjustMs = runTimeCounterMs`（对齐风扇 `setDeviceToReadyStatus` 的复位语义）。

**elapsed 钳制**：与 FanFSM 完全相同，`applySpeedLimit` 中将 `elapsed` 钳制到 1500ms，防止主循环阻塞导致 PWM 跳变。

### 5.7 sensorData — 全局数据容器

**单例，property 访问。** 当前字段：

| 字段 | 来源 | 说明 |
|------|------|------|
| tempLM75_1 / LM75FanTemp | LM75A 0x4A | 水冷散热器出水口侧温度（实际接入） |
| tempLM75_2 / LM75LedTemp | LM75A 0x4F | 灯板温度（实际接入） |
| tempLM75_3 | 预留 | 第三路 LM75（未接入） |
| **temp / humi** | **预留** | HDC1080 温湿度（驱动已移植） |
| **presure / altitude / tempBMP280** | **预留** | BMP280 气压/海拔（驱动已移植） |
| **luminance** | **预留** | BH1750 照度（驱动已移植） |
| **pm25** | **预留** | PMS5003 PM2.5（驱动已移植） |

**无效值：** 全部初始 -9999。

### 5.7 DBUtils — 数据库工具

**btree + 模块级 `_thread` 锁。** 所有方法 `acquire → try/finally(操作+flush+closeDB+release)`。Key/Value 均为字符串，使用时手动类型转换。

---

## 6. 传感器驱动

### 6.1 LM75A（I²C 0x4A / 0x4F）
- 11 位温度分辨率（0.125℃），-55~125℃
- 开机实例化逐个 `try/except OSError`：传感器缺失/总线故障时降级为 `None`，不影响整机启动
- BSP `readSensors()` 每 1s 读取一次；对象为 `None` 时跳过读取，温度保持无效值 -9999
- 单次读失败：保留上次有效值，故障/恢复日志仅在状态翻转时打印一次（不刷屏）
- **数据老化**：超过 10s（`_SENSOR_STALE_MS`）无有效值 → 置 -9999，FSM 按故障安全策略全速散热
- **总线自愈**：连续 30 次（`_I2C_MAX_FAIL_COUNT`）读失败 → 重建 SoftI2C 并重新绑定传感器对象
- **热插拔**：两路传感器全缺失时每 60s（`_I2C_RECOVER_RETRY_MS`）重试扫描，接入后自动恢复

### 6.2 死传感器驱动（预留）
驱动文件已从老项目移植：`bmp280.py`、`hdc1080.py`、`bh1750.py`、`pms5003.py`。BSP 中对应 handler 为 `pass` 桩。硬件接入后：
1. 在 BSP `__init__` 实例化驱动对象
2. 在 `readSensors()` 中取消注释读取逻辑
3. sensorData 字段已就绪，自动透传到 Web

### 6.3 I²C 总线

| 项目 | 值 |
|------|-----|
| 实现 | SoftI2C |
| SCL/SDA | GPIO7 / GPIO42 |
| 速率 | 100 kHz |
| 设备 | LM75A(0x4A) + LM75A(0x4F) |
| 上拉 | 外置电阻 |

---

## 7. Web API

| 路由 | 功能 |
|------|------|
| `GET /` | 返回 index.html（gzip） |
| `GET /static/<path>` | 静态资源（gzip 预压缩） |
| `GET /favicon.ico` | 图标（gzip） |
| `GET /status` | mode=get 查询状态 / mode=set 设置参数 |
| `GET /scanap` | 扫描 WiFi AP |
| `GET /setwifi` | 设置 WiFi（必填参数校验 + 日志脱敏） |
| `GET /reset` | 恢复出厂 |
| `GET /restart` | 重启设备 |

**响应格式：** 所有接口返回 `Content-Type: text/plain` 的 JSON 字符串（非 `application/json`），前端统一 `JSON.parse(resp)` 解析，避免 jQuery 按 content-type 自动解析导致类型不一致。

### 7.1 /status?mode=get
返回完整系统状态 JSON，含传感器数据、配置参数、FSM 状态、运行统计。

**主要字段：**

| 字段 | 说明 |
|------|------|
| `errCode` | `"0"` 成功，`"-1"` 失败 |
| `lightStatus` / `onOffStatus` | 灯光实际通断 / 目标开关 |
| `brightness` / `colorTemperature` | 目标亮度与色温 |
| `yellowBrightness` / `whiteBrightness` | 目标黄/白通道亮度（按色温拆分） |
| `yellowApplied` / `whiteApplied` | 渐变后的实际输出亮度（PWM 当前值） |
| `ledTotalRunTime` | LED 累计点亮秒数（跨开机持久化，仅开灯累加） |
| `ledRunTime` | LED 本次上电点亮秒数（运行时，开机清零） |
| `runTime` | 系统本次上电运行秒数 |
| `totalRunTime` | 系统总运行秒数（跨开机持久化，始终累加） |
| `powerOnCount` | 系统总上电次数（开机 +1 并持久化） |
| `eyeRemindActive` | 视疲劳提醒脉冲是否进行中 |
| `delayedOff` / `delayedOffTime` | 延迟关灯开关（0/1）与延时秒数（3~300） |
| `delayedOffPending` | 延迟关灯倒计时进行中标志（true=用户已关灯、到点自动关；false=正常关灯或未开启延迟关灯） |
| `eyeRemindInterval` | 视疲劳提醒间隔分钟数（0=关闭，5~60） |
| `pumpSpeed` / `fanSpeed` | 水泵/风扇实际转速百分比 |
| `tempLM75_1` / `tempLM75_2` | 原始温度：散热器出水口(0x4A) / 灯板(0x4F)，无效值 -9999 |
| `fanTemp` / `ledTemp` | 两路 FSM 内部 EMA 滤波后的温度 |
| `loopHz` | 主循环实测频率（每 5s 更新，用于发现阻塞掉速） |

**安全约束：** `devicepwd`、`wifipwd`、`wifipwdDefault` 三个密码类字段**不下发**。前端不依赖它们（WiFi 密码框留空重填、设备密码框用本地默认值），避免任何持有 `devicepwd` 的客户端拿到 WiFi 明文密码。`APPwd` 仍需下发用于回填 AP 密码输入框。

### 7.2 /status?mode=set
**先校验后应用：** `validateSetArgs()` 对全部数值参数做范围校验 + 跨字段一致性（`fanL<fanH`、`LEDL<LEDH`、`*PwmMin<*PwmMax`），任一不合法返回 `errCode=-1` 且不应用任何修改。

支持参数：`fanHThreshold`、`fanLThreshold`、`LEDHThreshold`、`LEDLThreshold`、`fanPwmFreq/Min/Max`、`pumpPwmFreq/Min/Max`、`yellowPwmFreq/Min/Max`、`whitePwmFreq/Min/Max`、`fanDelayTime`、`delayedOff`、`delayedOffTime`、`eyeRemindInterval`、`sw1name`、`sw2name`。

### 7.3 配置热更新流程
```
前端 Apply → GET /status?mode=set → validateSetArgs → db.save
  → 置 _pendingConfigReload = True（Web 线程，不直接改 FSM）
  → 主循环检测到标志 → reloadAllConfig()（主线程上下文）
    → bsp.setConfig (updatePWM 仅改频率，不重置 duty)
    → lightFSM.reloadConfig (_configDirty=True)
    → fanFSM.reloadConfig (_configDirty=True)
    → pumpFSM.reloadConfig (_configDirty=True)
  → 下一轮 FSM tick 强制重应用 PWM（用新 min/max 计算 duty）
```
**设计要点：** Web 线程与主循环不再竞争修改 FSM/BSP 内部状态，`reloadAllConfig` 统一在主线程执行，杜绝 PWM 寄存器与 `_configDirty` 标记的并发冲突。

### 7.4 /setwifi

设置 WiFi 与设备信息。**必填参数仅 4 个**（历史教训：早期版本把 `serverurl`/`sw1name`/`sw2name` 也列为必填，但前端从不发送，导致 WiFi 保存永远失败）：

| 参数 | 必填 | 说明 |
|------|------|------|
| `ssid` | ✅ | WiFi 名称 |
| `pwd` | ✅ | WiFi 密码 |
| `devicename` | ✅ | 设备名（兼 AP SSID） |
| `devicepwd` | ✅ | 设备密码 |
| `serverurl` | ❌ | 服务器 URL，未提交时保留当前配置值 |
| `sw1name` | ❌ | 开关 1 名称，未提交时保留当前值 |
| `sw2name` | ❌ | 开关 2 名称，未提交时保留当前值 |

任一必填参数缺失或为空返回 `errCode=-1`。保存后重启进入 STA 连接流程。日志经 `maskArgs` 脱敏，不打印 `pwd`/`devicepwd` 明文。

---

## 8. 前端架构

### 8.1 页面结构（两 Tab）

单文件 SPA：`static/index.html`（原生 JS + jQuery + Spectre CSS + SweetAlert + Chart.js），无构建步骤，改完直接重新 gzip 上传。

Tab 由 jQuery 事件驱动（`.tab[data-tab=x]` ↔ `.tab-panel#panel-x`），**只有两个页签**：

| Tab | 面板 ID | 内容 |
|-----|---------|------|
| 📊 监控 | `panel-monitor` | ① 灯光控制：开关按钮（开灯时背景色随色温从 3000K 暖黄渐变到 6000K 冷白）/ 亮度 / 色温（显示 3000~6000K）/ 快捷场景（暖光·中性·冷白·延迟关灯开关）<br>② 散热系统 + 系统状态 两张卡片（双列，散热系统在前；系统状态仅含 5 项运行统计：LED本次点亮/LED累计点亮/系统总运行/系统本次运行/上电次数，开关·亮度·色温已归入灯光控制卡片）<br>③ 温度与散热趋势图 |
| ⚙️ 设置 | `panel-settings` | ① 散热阈值（散热器出水温度/LED温度/风扇调整延迟）② 延迟关灯与护眼（延迟关灯时间 3~300s、视疲劳提醒间隔 0~60min）③ PWM 四通道参数 ④ 网络设置（WiFi 扫描 / AP 热点）⑤ 设备管理（重启 / 恢复出厂） |

**设计原则：** 灯光控制是使用频率最高的操作，放在监控页首屏，页面一打开就能用；设置页只放低频的写入型参数，避免高频操作被埋在二级页签里。

### 8.2 数据同步与防覆盖

统一 2s 轮询 `GET /status?mode=get`，一次响应同时喂给监控区和设置区：

| 机制 | 实现位置 | 作用 |
|------|----------|------|
| 轮询 | `setInterval(refresh, 2000)` | 全站统一刷新节奏 |
| 监控回填 | `updateMonitor(d)` | 状态卡片、图表、灯光滑块实时跟随 |
| 设置回填 | `syncSettingsForm(d, force)` | 设置参数实时跟随设备 |
| 编辑保护 | `lastSettingsEdit` + `SETTINGS_IDLE_MS=5000` | 用户改动参数后 5s 内整轮跳过回填，防止输入中途被覆盖 |
| 焦点保护 | `$el.is(':focus')` | 正在输入的那个输入框单独跳过 |
| 保存后同步 | `resumeSettingsSync()` + `refresh()` | 成功或失败都立即用设备值回填一次 |

**时序：**

```
用户输入(input/change) → lastSettingsEdit = now
        │
每 2s → refresh() → syncSettingsForm()
        │
   now - lastSettingsEdit < 5000ms ──▶ 跳过本轮回填（保护输入）
        │
        └─ ≥ 5000ms ──▶ 按设备值回填（停手后自动恢复同步）

用户点保存 → /status?mode=set → validateSetArgs
        ├─ 成功：落库 + 主线程热更新（见 7.3）→ resumeSettingsSync() → 立即回填
        └─ 失败：errCode=-1，不应用任何修改 → resumeSettingsSync() → 回填成设备实际值（相当于 UI 回滚）
```

**为什么用时间窗口而不是"脏标记"**：脏标记会让改动过的字段永久不再同步，设备侧变化（旋钮、其他客户端、接口调用）永远看不到；时间窗口只保护"正在编辑"的那几秒，停手后自动恢复同步。

### 8.3 趋势图

- Chart.js 折线图，采样上限 `MAX_POINTS = 60`（2s × 60 ≈ 最近 2 分钟）
- 双 Y 轴：左轴温度（℃），右轴转速（%）
- 6 条数据集：散热器出水温度、LED(灯板)温度、风扇转速、水泵转速（虚线）、高温阈值参考线、低温阈值参考线
- `refresh()` 每轮调用 `pushChart(d)` 追加一点并 `shift()` 淘汰最老点，长时间挂机内存不增长；无效值 -9999 写 null 断开曲线

### 8.4 静态资源 gzip 压缩

设备端按 `Accept-Encoding` 直接返回 `.gz`，浏览器无感解压：

| 文件 | 原始 | 压缩后 | 压缩率 |
|------|------|--------|--------|
| index.html | 30.5 KB | 7.6 KB | 25% |
| chart.umd.js | 200.6 KB | 68.1 KB | 34% |
| jquery.min.js | 85.5 KB | 29.7 KB | 35% |
| spectre.min.css | 45.6 KB | 9.5 KB | 21% |
| sweetalert.min.js | 39.9 KB | 11.6 KB | 29% |
| favicon.ico | 66.1 KB | 12.1 KB | 18% |
| **合计** | **468.0 KB** | **138.7 KB** | **30%** |

**重新生成命令**（改完 index.html 必须同步重压，否则浏览器拿到的仍是旧 .gz）：

```powershell
python -c "import gzip; d=open('static/index.html','rb').read(); open('static/index.html.gz','wb').write(gzip.compress(d, 9, mtime=0))"
```

### 8.5 响应式布局

监控页用 CSS Grid 排版，核心栅格类：

| 类名 | 桌面端 | 移动端（≤768px） | 用途 |
|------|--------|------------------|------|
| `.grid-2` | `1fr 1fr` | `1fr` | 散热系统 / 系统状态 两张卡片的外层容器 |
| `.grid-4` | `repeat(4, 1fr)` | `repeat(2, 1fr)` | 卡片内指标网格 + 快捷场景按钮 |
| `.grid-5` | `repeat(5, 1fr)` | `repeat(2, 1fr)` | 系统状态卡片的 5 项运行统计指标 |

**移动端断点 `@media (max-width: 768px)`：**

```css
.grid-2 { grid-template-columns: 1fr; }            /* 两张卡片上下堆叠 */
.grid-4 { grid-template-columns: repeat(2, 1fr); gap: 10px; }  /* 指标/按钮 2×2 */
.grid-5 { grid-template-columns: repeat(2, 1fr); gap: 10px; }  /* 系统状态 5 项统计 2 列排布 */
.metric { padding: 10px; }                          /* 内边距 14→10px */
.metric .value { font-size: 1.4rem; }               /* 数值 1.8→1.4rem */
```

**设计要点：**
- 卡片外层 `.grid-2` 移动端降为单列，避免窄屏双列卡片内容挤压
- 卡片内部 `.grid-4`（4 个指标块）移动端保持双列而非单列——单列时每个指标占满整行、数值 `1.8rem` 过大，双列 2×2 排布信息密度更合理
- 同步收紧 metric 的 padding 与数值字号，避免双列后内容过挤

---

## 9. 数据流

### 9.1 传感器数据流
```
主循环 20Hz → bsp.readSensors() (1Hz 节流) → LM75A 0x4A/0x4F → sensorData.LM75FanTemp / LM75LedTemp
```

### 9.2 FSM 控制流
```
主循环 20Hz → LightControllFSM.run() → 每 tick 执行：系统使能 → 读编码器 → 渐变输出
                                     → 写 yellowPwm/whitePwm + LED_EN
主循环 1Hz  → FanFSM.run() → 读 LM75FanTemp → 写 fanPwm（仅灯开时，关灯即停）
主循环 1Hz  → PumpFSM.run() → 读 LM75LedTemp → 写 pumpPwm（按温度，关灯后继续降温）
```

### 9.3 参数设置流
```
前端 Apply → GET /status?mode=set → validateSetArgs → db.save → reloadAllConfig
```

### 9.4 前端刷新流
```
setInterval 2s → GET /status?mode=get
  ├─ updateMonitor(d)      → 状态卡片 / 趋势图 / 灯光滑块
  └─ syncSettingsForm(d)   → 设置表单（编辑中或编辑后 5s 内跳过）
```

---

## 10. 配置参数

### 10.1 PWM 参数

| 参数 | 默认值 | 范围 | 说明 |
|------|--------|------|------|
| `fanPwmFreq` | 25000 | 1-78125 | 风扇 PWM 频率 (Hz) |
| `fanPwmMin` | 15 | 0-100 | 风扇最小占空比 (%) |
| `fanPwmMax` | 100 | 0-100 | 风扇最大占空比 (%) |
| `pumpPwmFreq` | 25000 | 1-78125 | 水泵 PWM 频率 |
| `pumpPwmMin` | 15 | 0-100 | 水泵最小占空比 |
| `pumpPwmMax` | 100 | 0-100 | 水泵最大占空比 |
| `yellowPwmFreq` | 25000 | 1-78125 | 暖黄 LED PWM 频率 |
| `yellowPwmMin` | 15 | 0-100 | 暖黄最小占空比 |
| `yellowPwmMax` | 100 | 0-100 | 暖黄最大占空比 |
| `whitePwmFreq` | 25000 | 1-78125 | 冷白 LED PWM 频率 |
| `whitePwmMin` | 15 | 0-100 | 冷白最小占空比 |
| `whitePwmMax` | 100 | 0-100 | 冷白最大占空比 |

### 10.2 温度阈值

| 参数 | 默认值 | 范围 | 说明 |
|------|--------|------|------|
| `fanHThreshold` | 40 | -20~120 | 风扇全速温度 (℃) |
| `fanLThreshold` | 30 | -20~120 | 风扇启动温度 (℃) |
| `LEDHThreshold` | 45 | -20~120 | 水泵全速温度 (℃) |
| `LEDLThreshold` | 35 | -20~120 | 水泵启动温度 (℃) |

### 10.3 其他

| 参数 | 默认值 | 范围 | 说明 |
|------|--------|------|------|
| `fanDelayTime` | 5 | 1-3600 | **当前未使用**：调速已改为每 tick 按时间限速，不再依赖固定间隔；参数仍保留在配置与校验中 |
| `delayedOff` | 0 | 0-1 | 延迟关灯开关：1=开灯后到 `delayedOffTime` 自动关灯 |
| `delayedOffTime` | 60 | 3-300 | 延迟关灯时长（秒） |
| `eyeRemindInterval` | 0 | 0, 5-60 | 视疲劳提醒间隔（分钟，0=关闭），开灯超此时长触发 10s 明暗脉冲 |

---

## 11. 无效值体系
**统一 -9999。** 传感器数据初始 -9999；LM75A 单次读取失败时保留上次有效值（不立即置 -9999）；连续 10s 无有效值（数据老化）后置 -9999，FSM 按故障安全策略全速散热。

---

## 12. WiFi / NTP / 计时约定

### 12.1 WiFi
- 开机 STA 连接（≤36s），失败转 AP 配网（300s 重启）
- AP SSID：`ReadingLamp`（可配置 `devicename`），密码 `APPwd`
- **断线重连：** 主循环每 30s 检查，断线后启动后台线程调 `startReconnect()` 做完整射频电源循环（`active(False)→sleep(1)→active(True)→connect()`），`_reconnecting` 标志防并发

### 12.2 NTP
- 联网后从 ntp.aliyun.com 获取 UTC+8 写入 RTC
- 未成功每 60s 重试（ticks_ms 节流），成功后停止重试

### 12.3 计时约定（禁止混用）

| 类别 | 时间源 | 用途 |
|------|--------|------|
| 单调节拍 | `ticks_ms()` + `ticks_diff` | 一切时长/超时/周期判定 |
| 墙钟 | `utime.time()` / RTC | 日志时间戳、NTP 周期 |

**原则：**
- 所有周期/定时行为基于"距上次 ≥ 阈值"
- 长寿命"距开机时长"值**逐轮累加小间隔**，禁止 `ticks_diff(now, bootTickMs)`（超 6.21 天变负）
- 配置项单位保持秒，读取处 ×1000 转 ms

---

## 13. 性能分析

### 13.1 已实施的性能优化

| 优化点 | 效果 |
|--------|------|
| 静态资源 gzip 预压缩 | 传输量 468KB → 139KB（-70%） |
| 主循环 20Hz | 旋钮响应延迟 ≤50ms，渐变步进约 2.5%/步 |
| 时间驱动定时 | 与轮询频率解耦，提频后周期不变 |
| 毫秒级累计计时 | 避免 NTP 跳变 + 整除累计误差 |
| PWM 单次构造 | 无内存泄漏，运行中无输出毛刺 |
| `setPwm` 频率去重 | 频率未变跳过 `freq()` 调用，避免毛刺 |
| `_offApplied` 标记 | 关灯态不重复写 PWM=0 |
| saveData 变更检测 | 亮度/色温未变不写 Flash，减少磨损 |
| DB 线程锁 | 防并发损坏 |
| 活性检测式 WDT | 主循环卡死可复位 |
| WiFi 重连后台线程 | 1s 射频复位不阻塞旋钮响应 |
| `_pendingConfigReload` 标志 | 配置重载统一在主线程执行，消除 Web 线程与主循环竞态 |
| 重连线程 try/except | 线程创建失败时重置 `_reconnecting`，避免永久无法重连 |
| WiFi 密码日志脱敏 | `connectToWifi`/`testWifiConnect` 不再明文打印密码 |
| 三个 FSM 均"每 tick 全流程" | 不做状态轮转：轮转会稀释每 tick 的有效动作，导致限速窗口/渐变速率只有设计值的 1/3 |
| 停机只写一次 PWM | 关灯态 `setDeviceToReadyStatus` 去重，避免每秒重复写占空比 |
| 配置定时器单例 | `Timer(3)` 只创建一次，避免 setwifi/reset/restart 重复占用硬件定时器 |
| GET 不下发密码字段 | `devicepwd`/`wifipwd`/`wifipwdDefault` 从响应剔除 |
| FSM 限速 elapsed 钳制 1500ms | 主循环阻塞（GC/WiFi 重连/配置重载）导致 `runTimeCounterMs` 跳变时，`elapsed` 钳制到 1.5s，单 tick 转速变化 ≤37.5%，避免 PWM 突变 |
| `setBrightness(0)` 等同关灯 | 亮度滑到 0 时直接关灯并清 `_delayedOffPending`，避免"灯不关 / 倒计时残留" |
| `ledTotalRunTime` 60s 节流 + 关灯即写 | 由每 10s 无条件写改为 60s 节流 + 关灯立即落盘，大幅降低 flash 磨损 |
| FSM `config.get()` 防 KeyError | FanFSM/PumpFSM 由 `self.config["key"]` 改为 `self.config.get("key", default)`，配置缺字段不崩溃 |

### 13.2 资源占用
- Flash：源码 + 静态资源（含 .gz）约 1.5MB
- RAM：MicroPython 堆，GC 每 5 分钟回收
- GPIO：12 个，剩余充足
- 定时器：Timer 0(WDT) / 3(配置模式)，Timer 1/2 空闲
- PWM：4 通道全用

---

## 14. 可扩展能力分析

### 14.1 已预留的扩展点

| 扩展点 | 现状 | 接入方式 |
|--------|------|----------|
| **BMP280** | 驱动已移植 + sensorData 字段就绪 | BSP `__init__` 实例化 → `readSensors` 取消注释 |
| **HDC1080** | 驱动已移植 + sensorData 字段就绪 | 同上 |
| **BH1750** | 驱动已移植 + sensorData 字段就绪 | 同上（I²C 地址 0x23/0x5C，可与 LM75A 共总线） |
| **PMS5003** | 驱动已移植 + sensorData 字段就绪 | 同上（UART） |
| **第三路 LM75** | sensorData.tempLM75_3 已定义 | BSP 增加实例 + readSensors 读取 |
| **Timer 1/2** | 未使用 | 新增定时任务 |
| **ADC** | 未使用 | 模拟量传感器 |

### 14.2 扩展指南（接入 BMP280 示例）
```
1. driver/bsp.py __init__: self.__bmp280 = bmp280.BMP280(self.softI2C)
2. driver/bsp.py readSensors:
     try: self.__sensorData.presure = self.__bmp280.getPress()
     except OSError: pass
3. main.py /status?mode=get: res 已包含 presure（透传）
4. static/index.html: 前端展示（参考 luminance 实现）
```

---

## 15. 已知问题 / Known Issues

**低优先级：**

| # | 描述 | 优先级 |
|---|------|--------|
| 1 | AACOps.py（湿球温度计算）已移植但温湿度传感器未接入，当前未使用 | 低 |
| 2 | 死传感器驱动（bmp280/hdc1080/bh1750/pms5003）保留，硬件未接入 | 低 |
| 3 | boot.py 为空，可启用 WebREPL | 低 |
| 4 | 无 OTA 能力，固件更新需串口刷写 | 低 |
| 5 | HardI2C 引脚定义（GPIO2/41）保留但未实例化 | 低 |
| 6 | 配置字典实时读取的微竞态：FSM 通过 `self.config`（与 `systemConfig` 同一对象）实时读取阈值，Web 线程多键更新瞬间可能读到新旧混合值；影响极小（阈值配对临时不一致时 `denom<=0` 兜底全速一拍），与雾化器项目行为一致 | 低 |
| 7 | 编码器 KEY 占用 GPIO1，部分 S3 核心板 GPIO1 为 U0TXD，若接 USB-串口桥可能影响调试串口输出 | 低 |
| 9 | `fanDelayTime` 已成为死配置：调速改用每 tick 时间限速后无代码读取，仅保留定义与校验（不影响功能，保留是为了老库兼容） | 低 |

---

## 16. 烧录与部署流程

### 16.1 固件刷写
1. 安装 MicroPython（ESP32-S3 Octal-SPIRAM 固件）
2. 使用 Thonny 或 `esptool.py` 写入固件
3. 上传全部源码与静态资源到设备根目录及 `static/` 目录

### 16.2 文件更新安全流程（硬约束）
程序含看门狗复位逻辑，**上传文件前必须先复位并停在调试状态**：
1. 按设备 RST 按钮复位，Thonny 中断在 `>>>` REPL
2. 用 `mpremote` 或 Thonny 文件管理器上传文件
3. **单端口单进程**：禁止并行
4. 上传后逐个校验文件大小
5. 再次硬复位运行

### 16.3 首次启动
1. 上电 → STA 尝试连接 WiFi（≤36s 阻塞）
2. 失败 → 进入 AP 配网模式（SSID：`ReadingLamp`，密码 `APPwd`）
3. 浏览器访问 192.168.4.1，配置 WiFi 并保存
4. 设备 300s 后自动重启，正常连接 WiFi 后 LED 转绿色

---

## 17. 调试经验与验证规范

> 本节沉淀项目迁移与调试过程中的关键经验、约定和教训，供后续维护参考。目标是让新会话能复现同等质量的排查与修复。

### 17.1 设备连接与验证工作流

| 项目 | 值 |
|------|-----|
| 串口 | COM42，波特率 115200 |
| 设备 IP | 192.168.30.74 |
| 设备密码 | `pengping` |
| 上传工具 | `mpremote` |

**上传命令**（Windows PowerShell）：
```powershell
mpremote connect COM42 cp <local_file> :<remote_path>
mpremote connect COM42 reset
```

**状态查询**（上传后等待约 14s 启动完成）：
```powershell
$H = @{'Cache-Control' = 'no-cache'}
Invoke-RestMethod "http://192.168.30.74/status?devicepwd=pengping&mode=get" -Headers $H
```

**串口日志**：用 `serial.Serial('COM42', 115200)` 或 `mpremote connect COM42` 捕获 FSM 运行日志。

### 17.2 FSM 日志时序约定（极易误判，务必牢记）

**所有 FSM 的 `run()` 中，日志打印在 `evaluate()` 调用之前。** 这意味着：
- 第 N 个 tick 打印的日志，反映的是**第 N-1 个 tick `evaluate()` 执行后的状态**；
- 第 N 个 tick `evaluate()` 的结果，要到**第 N+1 个 tick 的日志**才会显示；
- 配置热更新（`reloadConfig`）的效果，也会延后一个 tick 才在日志中体现。

**排查调速问题时**：不要因为某条日志显示的 `targetSpeed` 与预期不符就判定逻辑错误——先确认这条日志对应的是哪一轮 `evaluate`。正确做法是连续观察 2~3 条日志，确认状态变化是否在一个 tick 的延迟后正确出现。

### 17.3 核心教训：主循环阻塞会破坏时间基准

**现象**：水泵/风扇 PWM 突然跳变（如 0→50→75→100），或超过阈值后不转。

**根因**：FSM 的限速公式 `maxChange = SPEED_RATE_LIMIT × elapsed / 1000` 中，`elapsed = ticks_diff(runTimeCounterMs, lastSpeedAdjustMs)`。`runTimeCounterMs` 是逐 tick 累加的，**主循环被阻塞时它会一次性跳变大值**。常见阻塞源：

| 阻塞源 | 频率 | 典型耗时 |
|--------|------|----------|
| `gc.collect()` | 每 5 min | 数百 ms ~ 1s |
| WiFi 射频重连 `startReconnect` | 断线后 30s 一次 | ~1s（含 `sleep(1)`） |
| `reloadAllConfig` + `db.save` | 配置保存时 | 数十 ms ~ 数百 ms |
| 静态文件大响应发送 | Web 请求时 | 取决于文件大小 |

当 `elapsed` 跳到 2~5s 时，`maxChange = 25 × 5 = 125`，超过 100，`appliedSpeed` 直接等于 `targetSpeed`，限速失效、PWM 突变。

**修复**：`applySpeedLimit` 中将 `elapsed` 钳制到 1500ms（单 tick 最大变化 37.5%）。`lastSpeedAdjustMs` 仍每 tick 刷新，下一轮回归正常。

**风扇为何未暴露此 bug**：风扇关灯时每 tick 走 `setDeviceToReadyStatus()`，该函数重置 `lastSpeedAdjustMs = runTimeCounterMs`，相当于每 tick 都"归零"计时基准，所以即使 `runTimeCounterMs` 跳变，风扇的 `elapsed` 也总是约 1 tick。水泵正常运行不调用 `setDeviceToReadyStatus`，因此需要额外的钳制保护（以及停机时的复位）。

### 17.4 FSM 设计铁律

1. **每 tick 全流程，不做状态轮转**：`evaluate()` 必须每个 tick 都执行（评估温度 + 限速 + 写 PWM）。若拆成"评估态/调速态/保速态"轮流执行，限速窗口会被放大 N 倍（N=状态数），`maxChange` 相应放大，限速形同虚设。灯光 FSM 同理——`checkSystemEnableStatus → processKnob → fitPower` 每 tick 顺序全跑，不拆状态。

2. **FanFSM 与 PumpFSM 对称修改**：两者算法、参数常量、字段命名完全一致，只在停机条件上有差异。改一处必须同步另一处，否则行为不一致。

3. **配置访问用 `config.get(key, default)`**：禁止 `self.config["key"]` 直接索引。配置来自 DB + 默认值合并，老库可能缺字段，直接索引会抛 `KeyError` 导致 FSM 崩溃。

4. **停机去重写 PWM**：`setDeviceToReadyStatus` 用 `lastPwmSpeed` 判断，仅在配置变更或上次非 0 时写 PWM，避免每秒重复写占空比。

### 17.5 配置与持久化约定

- **`self.config` 与 `systemConfig` 是同一 dict 对象**：Web 线程修改 `systemConfig` 后，主循环 FSM 立即看到新值。因此**跳变检测（如 `delayedOff` 0→1）必须在 `run()` 内完成**，不能只依赖 `reloadConfig` 回调。
- **`ledTotalRunTime` 双触发落盘**：60s 节流 + 关灯立即写。不要回退到"每 10s 无条件写"，flash 磨损严重。
- **亮度/色温用变更检测**：`saveData()` 中 `lastBrightness`/`lastColorTemperature` 比对，未变不写 DB。

### 17.6 常见排查清单

| 现象 | 排查方向 |
|------|----------|
| 水泵/风扇转速突变 | 检查 `elapsed` 是否被钳制（1500ms）；确认主循环是否有新增阻塞源 |
| 水泵超阈值不转 | 确认 `LEDLThreshold`/`LEDHThreshold` 配置合理；检查 `pumpPwmMin` 是否过低（默认 15 可克服静摩擦）；看日志中 `targetSpeed` 是否为 0 |
| 亮度滑到 0 灯不关 | 确认 `setBrightness(0)` 走了关灯分支（写 PWM=0 + 清 `_delayedOffPending`） |
| 延迟关灯开启后立即关灯 | 确认 `delayedOff` 0→1 跳变时 `_onSinceMs` 被重置（在 `run()` 内检测） |
| WiFi 保存失败 | 确认 `/setwifi` 必填参数仅 `ssid/pwd/devicename/devicepwd`，前端未发送的参数不应设为必填 |
| 配置修改后 PWM 瞬断 | 确认 `updatePWM` 不重置 duty，FSM 通过 `_configDirty` 标记在下一轮重应用 |

---

## 18. 待验证项 / TODO

> 项目迁移（WROOM-32 → ESP32-S3）后尚未在硬件上验证的功能，需上电实测确认。

| # | 待验证项 | 涉及硬件/引脚 | 验证方法 | 优先级 |
|---|----------|---------------|----------|--------|
| 1 | **旋转编码器（CLK/DT）** | GPIO40(CLK) / GPIO39(DT) | 旋转旋钮，观察亮度/色温是否平滑变化（±2%/格），无丢步或跳变；串口日志确认 `lastKnobValue` 正常更新 | 高 |
| 2 | **编码器按键（KEY）** | GPIO1 | 短按切换开关灯；长按 + 旋转调色温；注意 GPIO1 在部分 S3 核心板为 U0TXD，若接 USB-串口桥可能冲突（已知问题 #7） | 高 |
| 3 | **编码器内部上拉有效性** | GPIO39/40/1 | 确认 `Pin.PULL_UP` 在 S3 上生效，断线时为高电平（静止态），旋转时边沿触发正常 | 中 |

---

## 19. 待实施优化：编码器驱动升级（machine.Encoder 硬件 PCNT）

> **状态：待实施** — 当前先完成第 18 节硬件验证，确认编码器硬件正常后再启动本优化。
> **决策日期：2026-11-08**

### 19.1 背景与动机

当前编码器驱动使用第三方库 `lib/rotary/`（Mike Teachman micropython-rotary），采用软件 GPIO 中断 + 8 状态正交状态机解码。经评估，驱动本身算法正确，但存在以下可优化点：

| # | 问题 | 影响 |
|---|------|------|
| 1 | 占用 2 个 GPIO 中断（CLK/DT 双边沿） | 主循环 20Hz 被频繁打断，影响调度稳定性 |
| 2 | 无硬件去抖 | 靠状态机容错，毛刺仍可能产生误计数 |
| 3 | 分辨率低（全步进 = 4 边沿 1 计数） | 旋钮调节粒度粗 |
| 4 | 按键（KEY）无软件去抖 | 一次按下可能触发多次开关灯（原有 bug，与驱动无关但一并修复） |
| 5 | 快速旋转时 `delt` 无单 tick 限幅 | 亮度可能一次跳变 10~20% |

### 19.2 方案：使用 MicroPython 官方 `machine.Encoder`

MicroPython **v1.27+** 原生提供 `machine.Encoder` 类（项目固件 v1.29.0 已支持），基于 ESP32-S3 硬件 PCNT（脉冲计数器）外设实现正交解码。

**核心代码形态（待实施时写入 `driver/bsp.py`）：**

```python
from machine import Pin, Encoder

# 替换 RotaryIRQ 实例化
self.knob = Encoder(
    0,                                      # PCNT 单元 id（ESP32-S3 有 8 个，0~7）
    Pin(self.PIN_ROTARY_CLK, Pin.IN, Pin.PULL_UP),
    Pin(self.PIN_ROTARY_DT, Pin.IN, Pin.PULL_UP),
    filter_ns=1000,                         # 硬件 glitch filter，去抖
    phases=4                                # 4x 正交解码，分辨率 x4
)
# getknob() 接口不变，仍返回 (self.knob, self.knobKey.value())
```

### 19.3 方案对比

| 维度 | RotaryIRQ（当前） | machine.Encoder（待实施） |
|------|-------------------|--------------------------|
| 解码实现 | 软件 IRQ + 状态机 | 硬件 PCNT |
| CPU 中断开销 | 2 个 IRQ，每边沿触发 | **零中断**，硬件自动计数 |
| 去抖 | 无（状态机容错） | **`filter_ns` 硬件滤波** |
| 分辨率 | 1x（4 边沿 = 1 计数） | 1x / 2x / 4x 可选（推荐 4x） |
| 丢脉冲风险 | IRQ 阻塞时可能丢 | **硬件计数，永不丢** |
| 计数器位宽 | 任意精度整数 | 16 位有符号（±32768 翻转） |
| 第三方依赖 | `lib/rotary/`（2 个文件） | **官方内置 API，无依赖** |
| 按键处理 | 单独 KEY 引脚 | 单独 KEY 引脚（不变） |

**计数器溢出说明**：PCNT 为 16 位有符号，value 会在 ±32768 翻转。但业务逻辑只计算 `delt = current - last`，20Hz 轮询间隔（50ms）内不可能旋转 32767 格，因此 delt 计算永远正确，溢出不影响调光。

### 19.4 改动清单（核心业务逻辑不变）

> **关键结论**：`LightControllFSM.processKnob()` 的 if-elif 分支结构一行都不用改，仅调整步进系数。

| 文件 | 改动内容 | 性质 |
|------|----------|------|
| `driver/bsp.py` | `RotaryIRQ` → `machine.Encoder`；`getknob()` 接口不变（仍返回 `(obj, key_level)`） | 驱动替换 |
| `domain/LightControllFSM.py` | 步进系数 `delt * 2` → `delt * 0.5`（phases=4 时，保持每机械格 2% 亮度） | 参数调整 |
| `domain/LightControllFSM.py` | 按键去抖：20ms 窗口内忽略重复下降沿（修复原有 bug） | 缺陷修复 |
| `lib/rotary/` | 整个目录可删除 | 清理依赖 |

**步进系数换算表**（保持"1 机械格 = 2% 亮度"不变）：

| phases 参数 | 分辨率倍率 | 亮度步进系数 |
|-------------|-----------|-------------|
| 1 | 1x | `* 2`（与当前相同） |
| 2 | 2x | `* 1` |
| 4（推荐） | 4x | `* 0.5` |

### 19.5 前置条件（必须先完成）

1. **第 18 节硬件验证通过**：编码器 CLK/DT/KEY 在当前 rotary 库驱动下功能正常，排除硬件接线问题
2. **固件 API 可用性确认**：在 REPL 中执行 `from machine import Encoder` 确认 v1.29.0 固件已启用该类
3. **PCNT filter 范围确认**：实测 `filter_ns` 参数的有效范围（PCNT filter 时钟约 80MHz，最大约 1023 周期 ≈ 12.8μs）

### 19.6 实施步骤（待启动时按序执行）

1. REPL 验证 `machine.Encoder` 可用，记录可用的 PCNT id 与 filter 范围
2. 修改 `bsp.py`：替换编码器实例化，保持 `getknob()` 接口不变
3. 修改 `LightControllFSM.py`：调整步进系数 + 增加按键去抖
4. 上传测试，验证：旋转方向、每格亮度变化、按键开关灯、快速旋转无跳变
5. 验证通过后删除 `lib/rotary/` 目录
6. 更新本章节状态为"已实施"

### 19.7 验证标准

| 验证项 | 预期结果 |
|--------|----------|
| 顺时针旋转 | 亮度增加，每格约 2% |
| 逆时针旋转 | 亮度减少，每格约 2% |
| 按住 + 旋转 | 色温变化，每格约 2% |
| 短按按键 | 开关灯切换一次，无重复触发 |
| 快速旋转 | 亮度平滑变化，无突变（delt 限幅生效） |
| 主循环频率 | `loopHz` 稳定在 20Hz 附近，无 IRQ 打断导致的掉速 |

---

## 20. 代码优化记录（2026-11-09）

### 20.1 优化概述

本次优化针对系统架构、功能、性能、可靠性四个维度，共实施 10 项改进，硬件验证全部通过。

| 维度 | 优化项数 | 关键改进 |
|------|----------|----------|
| 可靠性 | 3 | setBrightness(0) 修复、lm75a.config() 修复、reloadAllConfig 异常恢复 |
| 架构 | 2 | FanFSM/PumpFSM 基类提取、BSP 延迟导入 |
| 性能 | 3 | fileUtils.isFileExist 优化、readSensors 调度优化、WiFi scanAP 修复 |
| 代码质量 | 2 | processKnob 重复代码清理、wifi.py 注释清理 |

**代码变化：** +99 行 / -452 行（净减 353 行），主要来自 FanFSM/PumpFSM 基类提取。

### 20.2 高优先级修复（可靠性 Bug）

#### 1. `setBrightness(0)` 关灯逻辑不完整

**问题：** 亮度滑到 0 时直接置 `onOffStatus=False`，未走 `setOnOff` 完整流程，导致：
- `_continuousOnMs` 未清零（视疲劳提醒计时不准）
- `_eyeRemindActive` 未重置（护眼状态残留）
- `ledTotalRunTime` 未落盘（累计点亮时长丢失）

**修复：** 改为调用 `setOnOff(False, auto=True)`，复用完整关灯逻辑。`auto=True` 绕过延迟关灯倒计时。

**验证：** 硬件测试通过，ledTotalRunTime 正确落盘（30483s），再次开灯正常恢复。

#### 2. `lm75a.config()` 部分参数不写寄存器

**问题：** 原实现仅在 `os_fault_queue` 非 None 时才 `writeto_mem`，单独设置 `shutdown/os_mode/os_polarity` 不生效。

**修复：** 引入 `changed` 标志，任一参数非 None 即写入硬件。

#### 3. `reloadAllConfig` 异常后状态不一致

**问题：** 异常时 `_pendingConfigReload` 已清但 FSM/BSP 未更新，systemConfig 已被 Web 线程修改。

**修复：** 异常时将标志置回 `True`，下一 tick 重试，避免配置丢失。

### 20.3 架构优化

#### 4. FanFSM/PumpFSM 基类提取

**问题：** 两个 FSM 95% 代码重复，改一处需同步另一处，维护风险高。

**修复：** 新增 `domain/ThermalControlFSM.py` 基类，封装 EMA 滤波 + 滞回带 + 渐变限速全部逻辑。子类通过 `params` dict 注入差异点。

**效果：** 每个 FSM 从 ~200 行缩减到 ~20 行，代码量减少 90%，改一处自动同步。

#### 5. BSP 延迟导入死传感器驱动

**问题：** 启动时导入 bmp280/hdc1080/bh1750/pms5003，浪费 RAM 和导入时间。

**修复：** 注释顶层导入，硬件接入后在 handler 内按需 import。

### 20.4 性能优化

#### 6. `fileUtils.isFileExist` 优化

**问题：** 每次 `uos.listdir(dir)` 遍历整个目录。

**修复：** 改用 `uos.stat()` + `try/except OSError`，O(1) 判定。

#### 7. `readSensors` 调度优化

**问题：** 20Hz 主循环中空转（内部 1Hz 节流）。

**修复：** 主循环用 1Hz 调度，BSP 内部节流保留作双重保险。

#### 8. `wifi.scanAP()` 同名覆盖修复

**问题：** 返回 dict 用 SSID 作 key，同名 AP 被覆盖。

**修复：** 改为 `list[dict]`，每项含 `ssid` 和 `rssi`。同步修改前端 `index.html`。

### 20.5 代码质量优化

#### 9. `processKnob` 重复代码清理

**问题：** 3 处重复计算 `yellowBrightness/whiteBrightness`。

**修复：** 统一调用 `_recalcBrightness()`。

#### 10. wifi.py 清理 + 健壮性

- 删除未使用的 `startBroadcastAP`
- 清理 10+ 行注释掉的代码
- `getAPIP` 未激活时返回 `None`（与 `getStationIP` 一致）
- `validateSetArgs.effVal` 改用 `systemConfig.get(key, 0)` 兜底防 `KeyError`

### 20.6 硬件验证结果

| 测试项 | 结果 | 关键数据 |
|--------|------|----------|
| 模块导入 | ✅ 8/8 通过 | ThermalControlFSM/FanFSM/PumpFSM/LightFSM/bsp/lm75a/wifi/fileUtils |
| FSM 实例化 | ✅ 通过 | 状态字段完整，配置加载正常 |
| 编码器 | ✅ 正常 | GPIO40/39 初始化成功，值读取正常 |
| PWM 通道 | ✅ 4/4 通过 | fan/pump/yellow/white 占空比设置正常 |
| LM75A 传感器 | ✅ 正常 | 0x4A=24.0°C, 0x4F=24.1°C |
| setBrightness(0) | ✅ 修复确认 | 关灯逻辑完整，数据落盘 |
| FSM 集成运行 | ✅ 5 秒无异常 | 温度滤波、阈值判断、配置热更新正常 |
| 配置热更新 | ✅ 生效 | fanHThreshold 40→35 立即生效 |
| 30 秒稳定性 | ✅ 600 循环 0 错误 | 平均 19.4Hz，内存变化 -240B |

### 20.7 待手动验证项

| 项目 | 原因 | 建议 |
|------|------|------|
| 编码器物理旋转 | 测试时无操作 | 手动旋转验证方向/步进 |
| 编码器按键 | 测试时无操作 | 短按验证开关灯 |
| 温度阈值触发 | 环境温度低于阈值 | 加热灯板验证风扇/水泵启动 |
| Web 接口完整流程 | 需浏览器操作 | 访问配置页面验证保存/重载 |

### 20.8 相关文件变更

| 文件 | 变更类型 | 说明 |
|------|----------|------|
| `domain/ThermalControlFSM.py` | 新增 | 温控 FSM 基类 |
| `domain/FanFSM.py` | 重构 | 继承基类，从 198 行减至 20 行 |
| `domain/PumpFSM.py` | 重构 | 继承基类，从 199 行减至 21 行 |
| `domain/LightControllFSM.py` | 修复 | setBrightness(0) 完整关灯逻辑 |
| `driver/lm75a.py` | 修复 | config() 任一参数即写寄存器 |
| `driver/bsp.py` | 优化 | 死传感器驱动延迟导入 |
| `domain/fileUtils.py` | 优化 | isFileExist 改用 uos.stat |
| `domain/wifi.py` | 修复+清理 | scanAP 返回 list，删除未用函数 |
| `main.py` | 优化 | readSensors 调度，reloadAllConfig 重试 |
| `static/index.html` | 适配 | scanAP 返回格式变更 |
| `static/index.html.gz` | 重新生成 | 8230→8215 字节 |

