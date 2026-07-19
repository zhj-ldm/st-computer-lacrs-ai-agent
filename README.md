# st-lacrs-ai-agent

st lacrs 风格的类 Open Claw AI 工具，可实时监听语音（"hey computer"）唤醒 AI，AI 可修改读取本地文件、执行命令行指令、联网搜索等。

> **开发状态说明**：以下内容中，**未标注**的模块为已实现/已有功能；标注 **「🚧 开发中」** 的为正在开发或规划中的目标，尚未实际完成。

---

## 功能

### 已实现

| 模块 | 说明 |
|------|------|
| 唤醒词检测 | 说出 **"hey computer"** 唤醒，支持阈值自定义 |
| 语音录制 | VAD 静音检测，自动切句，最短 0.5s / 最长 15s |
| 语音识别 | 本地 faster-whisper small 模型，CPU int8 量化 |
| AI 对话 | 接入任意兼容 OpenAI 格式的 LLM API，带上下文多轮对话 |
| 工具调用 | AI 可自主调用搜索引擎、读写文件、列出目录、执行 Shell |
| TTS 朗读 | Windows SAPI5 引擎，支持音色切换 (Huihui / Zira / David) 和语速调节 |
| 语音打断 | 朗读期间大声说话即可打断，自动切回聆听 |
| 多对话管理 | 创建 / 切换 / 删除对话，语音或 Web 均可操作 |
| Web 管理界面 | 浏览器查看对话历史、手动发送消息、管理对话 |

### 🚧 开发中 / 规划中

| 模块 | 说明 |
|------|------|
| 分布式拾音扩音 | ESP32 节点部署于各房间，内网 UDP/TCP 音频流传输，全屋任意位置唤醒 |
| 家电控制 | AI 通过 ESP32 节点控制继电器、红外、传感器等外设，实现全屋智能联动 |

---

## 技术栈

### 已实现

```
┌──────────────────────────────────────────────────────┐
│  唤醒词          openwakeword + ONNX                 │
│  语音识别        faster-whisper (small, CPU, int8)   │
│  LLM             OpenAI 兼容 API                     │
│  TTS             Windows SAPI5 (pywin32)             │
│  音频 I/O        pyaudio                             │
│  Web 后端        Flask                               │
│  Web 前端        HTML + 原生 JS (SSE 流式)           │
│  搜索引擎        DuckDuckGo (ddgs)                   │
│  运行环境        Windows 10/11, Python 3.9+          │
└──────────────────────────────────────────────────────┘
```

### 🚧 开发中 / 规划中

```
┌──────────────────────────────────────────────────────┐
│  分布式节点      ESP32-DevKitC / ESP32-S3            │
│  节点固件        Arduino (PlatformIO / Arduino IDE)  │
│  节点通信        内网 UDP（音频流）+ TCP（控制指令）  │
│  节点音频        I2S MEMS 麦克风 (INMP441)           │
│                  + I2S 功放 (MAX98357A)              │
│  家电控制        GPIO 继电器 / 红外发射管             │
│                  / UART 传感器                       │
│  中心协议        JSON over TCP 指令集                │
│                  + 自定义音频流格式                   │
└──────────────────────────────────────────────────────┘
```

---

## 程序运行流程

### 当前流程（已实现）

```
启动 app.py（Web 服务，端口 5000）
         │
启动 voice_assistant.py（语音助手主循环）
         │
         ▼
┌─────────────────────────────────────┐
│  监听麦克风                          │
│  等待唤醒词 "hey_computer"          │
│  （唤醒前 ~3% CPU）                  │
└──────────────┬──────────────────────┘
               │ 检测到唤醒词
               ▼
┌─────────────────────────────────────┐
│  播放提示音 wake_sound.wav           │
│  录制音频至静音 1.5s 或超时 15s      │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│  faster-whisper 转写为文本           │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│  发送到 LLM API（带对话历史）        │
│  AI 可能调用工具（搜索/文件/Shell）  │
│  工具结果回传 AI，生成最终回复        │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│  SAPI5 TTS 朗读回复                  │
│  → 可被打断（大声说话触发）           │
│  → 唤醒词工具调用可改语速/音色       │
└──────────────┬──────────────────────┘
               │
               ▼ 回到监听，等待下一次唤醒
```

### 🚧 目标流程（开发中，含分布式拓展）

```
启动 app.py（Web 服务，端口 5000）
         │
启动 voice_assistant.py（语音助手主循环）
         │
启动 udp_audio_server.py（分布式音频接收服务，端口 5555）
         │
         ▼
┌─────────────────────────────────────────────────────────┐
│  监听麦克风（本地） + UDP 音频流（分布式节点）            │
│  等待唤醒词 "hey_computer"                              │
│  （唤醒前 ~3% CPU + ESP32 节点极低功耗）                  │
└──────────────┬──────────────────────────────────────────┘
               │ 检测到唤醒词（本地或任意节点）
               ▼
┌─────────────────────────────────────────────────────────┐
│  确定唤醒来源（本地/节点ID）                              │
│  播放提示音 wake_sound.wav（本地 + 唤醒节点回传）         │
│  录制音频至静音 1.5s 或超时 15s（优先使用唤醒节点麦克风） │
└──────────────┬──────────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────────┐
│  faster-whisper 转写为文本                              │
└──────────────┬──────────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────────┐
│  发送到 LLM API（带对话历史）                            │
│  AI 可能调用工具（搜索/文件/Shell/家电控制）              │
│  工具结果回传 AI，生成最终回复                            │
└──────────────┬──────────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────────┐
│  SAPI5 TTS 朗读回复                                     │
│  + 音频流广播至唤醒节点扬声器（分布式扩音）               │
│  → 可被打断（大声说话触发，任意节点）                     │
│  → 唤醒词工具调用可改语速/音色                           │
└──────────────┬──────────────────────────────────────────┘
               │
               ▼ 回到监听，等待下一次唤醒
```

---

## 目录结构

```
st-lacrs-ai-agent/
├── app.py                    # Flask Web 服务 + AI 工具
├── voice_assistant.py        # 语音助手主程序
├── install_deps.py           # 依赖一键安装脚本
├── templates/
│   └── index.html            # Web 管理界面
├── data/
│   ├── config.json           # 配置文件
│   ├── complete.wav          # AI 回复提示音
│   ├── wake_sound.wav        # 唤醒提示音
│   └── conversations/        # 对话历史 (JSON)
│
│   ═══════════════ 🚧 以下为开发中 ═══════════════
│
├── udp_audio_server.py       # UDP 音频流接收服务
├── node_manager.py           # ESP32 节点管理（心跳/指令/注册）
├── home_control.py           # 家电控制工具集（AI Tool 注册）
├── firmware/                 # ESP32 固件源码
│   ├── st_lacrs_node/
│   │   ├── st_lacrs_node.ino        # Arduino 主固件
│   │   ├── audio.h                   # I2S 音频采集/播放
│   │   ├── wake_word.h               # 本地唤醒词（可选，轻量 MFCC）
│   │   ├── network.h                 # WiFi + UDP/TCP 通信
│   │   ├── command.h                 # 指令解析与执行
│   │   ├── gpio_control.h            # GPIO/继电器/红外控制
│   │   └── config.h                  # 节点配置模板
│   └── platformio.ini         # PlatformIO 构建配置
└── docs/
    └── hardware_setup.md      # ESP32 硬件接线图与物料清单
```

---

## 安装说明

### 1. 环境要求

- Windows 10 或 Windows 11
- Python 3.9 及以上
- 麦克风和扬声器
- 🚧 分布式拓展额外要求：Wi-Fi 路由器（用于 ESP32 节点通信）

### 2. 安装依赖

```powershell
# 方式一：一键安装脚本
python install_deps.py

# 方式二：手动安装
pip install flask requests numpy pywin32 openwakeword pyaudio faster-whisper
```

> pyaudio 如果安装失败，通常是缺少 VC++ 运行时：
> 1. 下载安装 [VC++ Redist](https://aka.ms/vs/17/release/vc_redist.x64.exe)
> 2. 重试 `pip install pyaudio`
> 3. 或使用 `pip install pipwin && pipwin install pyaudio`

### 3. 配置

编辑 `data/config.json`：

```json
{
    "api": {
        "url": "https://your-api-endpoint/v1/chat/completions",
        "key": "sk-xxxxxxxx",
        "model": "gpt-4"
    },
    "tts": {
        "voice": "Microsoft Huihui Desktop",
        "rate": 3,
        "volume": 100,
        "processing_rate": 1
    },
    "wake": {
        "threshold": 0.15,
        "stop_energy_threshold": 1200
    }
}
```

| 字段 | 说明 |
|------|------|
| `api.url` | LLM API 地址（OpenAI 兼容格式） |
| `api.key` | API 密钥 |
| `api.model` | 模型名称 |
| `tts.voice` | 默认音色：`Huihui`(中文女) / `Zira`(英文女) / `David`(英文男) |
| `tts.rate` | 语速 -10~10，正值越快 |
| `tts.volume` | 音量 0~100 |
| `wake.threshold` | 唤醒词灵敏度（越低越灵敏） |
| `wake.stop_energy_threshold` | 语音打断灵敏度，RMS 能量值 |

🚧 分布式拓展规划配置（开发完成后将合并到 config.json）：

```json
{
    "nodes": {
        "udp_audio_port": 5555,
        "tcp_command_port": 5556,
        "max_nodes": 8,
        "node_timeout_seconds": 30,
        "audio_format": "PCM_16K_16BIT_MONO"
    },
    "home_control": {
        "mqtt_broker": null,
        "ir_remote_config": "data/ir_codes.json"
    }
}
```

### 4. 首次运行

首次启动时 faster-whisper 会自动下载 `small` 模型（约 1GB）。国内网络已配置 `hf-mirror.com` 镜像加速。

### 5. 启动

```powershell
# 终端一：启动 Web 服务
python app.py

# 终端二：启动语音助手
python voice_assistant.py
```

启动后：
- 浏览器访问 `http://127.0.0.1:5000` 查看对话管理界面
- 对着麦克风说 **"hey computer"** 唤醒助手
- 听到提示音后说出你的问题
- AI 回复会通过扬声器朗读
- 朗读期间大声说话可打断

🚧 分布式拓展启动（开发中）：

```powershell
# 终端三（可选，可合并至 voice_assistant.py 独立线程）：
python udp_audio_server.py
```

🚧 ESP32 节点烧录（开发中）：

```bash
# 使用 PlatformIO（推荐）
cd firmware
pio run -t upload --upload-port COM3

# 或使用 Arduino IDE
# 打开 firmware/st_lacrs_node/st_lacrs_node.ino
# 选择开发板 ESP32 Dev Module，烧录
```

---

## 语音命令

唤醒后可直接用自然语言说出：

| 命令示例 | 功能 | 状态 |
|----------|------|------|
| "帮我搜索一下今天天气" | AI 调用搜索引擎 | 已实现 |
| "读一下桌面上的 readme.txt" | AI 读取文件 | 已实现 |
| "把结果写入 result.txt" | AI 写入文件 | 已实现 |
| "语速快一点" | 调快 TTS 语速 | 已实现 |
| "换成 David 的声音" | 切换 TTS 音色 | 已实现 |
| "新建一个对话" | 创建新对话 | 已实现 |
| "切换到上一个对话" | 切换对话 | 已实现 |
| "删除当前对话" | 删除对话 | 已实现 |
| "打开客厅的灯" | 控制客厅 ESP32 节点的继电器 | 🚧 开发中 |
| "把卧室空调调到 26 度" | 通过 ESP32 红外发射控制空调 | 🚧 开发中 |
| "关闭所有灯" | 批量控制所有照明节点 | 🚧 开发中 |
| "客厅温度是多少" | 读取客厅 ESP32 节点的 DHT22 传感器 | 🚧 开发中 |
| "开启影院模式" | 执行预设场景（关灯+关窗帘+开投影） | 🚧 开发中 |

---

# 🚧 以下为开发中 / 规划中的分布式拓展设计

> 以下内容为设计方案与预期目标，**尚未开发完成**。当前方案基于 **ESP32 内网 IP 连接 + Arduino 编写固件**，目标是实现全屋任意位置实时呼出 AI 并对家电进行控制。

---

## 分布式拾音扩音 — 整体拓扑（规划）

```
                        ┌─────────────────────────┐
                        │     Wi-Fi 路由器          │
                        │   192.168.1.1             │
                        └──────┬──────────────────┘
                               │
               ┌───────────────┼───────────────────────────────┐
               │               │                               │
               ▼               ▼                               ▼
    ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────────────┐
    │   PC (中心主机)    │  │  ESP32 客厅节点   │  │  ESP32 卧室节点           │
    │  st-lacrs-agent   │  │  192.168.1.101    │  │  192.168.1.102            │
    │  192.168.1.100    │  │                   │  │                           │
    │                   │  │  INMP441 麦克风    │  │  INMP441 麦克风            │
    │  UDP :5555 收音频  │  │  MAX98357A 扬声器  │  │  MAX98357A 扬声器          │
    │  TCP :5556 控节点  │  │  继电器×2 + 红外   │  │  DHT22 温湿度 + 继电器×1   │
    └──────────────────┘  └──────────────────┘  └──────────────────────────┘
```

---

## 通信协议（规划）

### 节点注册（TCP，节点 → 中心）

```json
{
    "type": "register",
    "node_id": "esp32_livingroom_01",
    "room": "客厅",
    "capabilities": ["audio", "relay", "ir"],
    "ip": "192.168.1.101",
    "version": "1.0.0"
}
```

### 心跳（TCP，节点 → 中心，每 5s）

```json
{
    "type": "heartbeat",
    "node_id": "esp32_livingroom_01",
    "rssi": -42,
    "free_heap": 124800,
    "uptime": 3600
}
```

### 控制指令（TCP，中心 → 节点）

```json
{
    "type": "command",
    "node_id": "esp32_livingroom_01",
    "action": "relay_set",
    "params": {"channel": 1, "state": true}
}
```

```json
{
    "type": "command",
    "node_id": "esp32_bedroom_01",
    "action": "ir_send",
    "params": {"protocol": "NEC", "address": 0x00FF, "command": 0xBA45}
}
```

```json
{
    "type": "command",
    "node_id": "esp32_bedroom_01",
    "action": "sensor_read",
    "params": {"sensor": "dht22"}
}
```

### 音频流（UDP，节点 → 中心）（规划）

```
帧格式（固定 320 字节）：
┌─────────────┬────────────┬──────────────────────┐
│ node_id (16B)│ seq (4B)   │ PCM 数据 (300B)      │
│ 字符串       │ uint32 BE  │ signed 16-bit LE     │
└─────────────┴────────────┴──────────────────────┘

采样率: 16kHz, 单声道, 16bit
每帧 150 个采样点 → 约 9.4ms 音频/帧
帧率: ~106 fps
```

### TTS 音频广播（UDP，中心 → 所有节点）（规划）

```
帧格式：
┌──────────────┬────────────┬──────────────────────┐
│ magic (4B)   │ seq (4B)   │ PCM 数据 (312B)      │
│ 0x5A5A5A5A  │ uint32 BE  │ signed 16-bit LE     │
└──────────────┴────────────┴──────────────────────┘

音频先通过 SAPI5 合成 → PCM 16kHz → 分包 → UDP 广播至所有在线节点
```

---

## 节点自动发现（规划）

ESP32 节点上电后通过 UDP 广播注册：

```
1. ESP32 启动 → 连接 WiFi
2. 发送 UDP 广播 (255.255.255.255:5557) 注册包
3. 中心主机监听 5557 端口，收到注册后回复确认
4. 建立 TCP 长连接 (端口 5556)，开始心跳 + 指令通信
5. 中心将节点信息写入 data/nodes.json
```

无需手动配置 IP，节点即插即用。

---

## ESP32 节点硬件设计（规划）

### 核心物料清单

| 组件 | 型号 | 数量 | 用途 |
|------|------|------|------|
| 主控 | ESP32-DevKitC V4 / ESP32-S3 | 1 | 核心处理 |
| 麦克风 | INMP441 I2S MEMS | 1 | 全向拾音 |
| 功放 | MAX98357A I2S 3W | 1 | 驱动扬声器 |
| 扬声器 | 3W 4Ω 全频喇叭 | 1 | 语音播报 |
| 继电器模块 | 5V 2路光耦隔离 | 1~2 | 灯光/插座控制 |
| 红外发射管 | 5mm 940nm + 三极管驱动 | 1 | 空调/电视/风扇控制 |
| 红外接收管 | VS1838B | 1 | 红外码学习 |
| 温湿度传感器 | DHT22 / AM2302 | 1 | 环境感知（可选） |
| 电源 | 5V 2A Micro USB | 1 | 供电 |

### 接线图

```
ESP32 DevKit V4
┌─────────────────────────────────────────────┐
│                                              │
│  INMP441 (I2S 麦克风)                        │
│  ┌──────────┐                               │
│  │ VDD → 3.3V                               │
│  │ GND → GND                                │
│  │ SD  → GPIO32                             │
│  │ SCK → GPIO33                             │
│  │ WS  → GPIO25                             │
│  │ L/R → GND (左声道)                        │
│  └──────────┘                               │
│                                              │
│  MAX98357A (I2S 功放)                        │
│  ┌──────────┐                               │
│  │ VIN → 5V                                 │
│  │ GND → GND                                │
│  │ DIN → GPIO26                             │
│  │ BCLK→ GPIO27                             │
│  │ LRCLK→ GPIO14                            │
│  │ SD  → 悬空 (默认左声道)                   │
│  │ GAIN→ GND (3dB)                          │
│  └────┬─────┘                               │
│       │ 接 4Ω 3W 喇叭                         │
│                                              │
│  继电器模块 (GPIO 控制)                       │
│  ┌──────────┐                               │
│  │ IN1 → GPIO16                             │
│  │ IN2 → GPIO17                             │
│  │ VCC → 5V                                 │
│  │ GND → GND                                │
│  └──────────┘                               │
│                                              │
│  红外发射 (GPIO4 + NPN 三极管驱动)             │
│  │ GPIO4 → 100Ω → 三极管 B极                 │
│  │ 三极管 C极 → 红外管 → 5V                   │
│  │ 三极管 E极 → GND                          │
│                                              │
│  VS1838B 红外接收 (GPIO5, 红外学习用)          │
│  │ VCC → 3.3V                               │
│  │ GND → GND                                │
│  │ OUT → GPIO5                              │
│                                              │
│  DHT22 温湿度 (GPIO18, 可选)                  │
│  │ VCC → 3.3V                               │
│  │ GND → GND                                │
│  │ DATA→ GPIO18 (+ 4.7kΩ 上拉至 3.3V)       │
│                                              │
└─────────────────────────────────────────────┘
```

---

## ESP32 固件核心逻辑（规划）

### Arduino 主循环 (`st_lacrs_node.ino`)

```cpp
#include "audio.h"
#include "network.h"
#include "command.h"
#include "gpio_control.h"

// 全局状态
NodeState state = STATE_IDLE;
unsigned long last_heartbeat = 0;

void setup() {
    Serial.begin(115200);
    initGPIO();
    initWiFi();
    initAudio();
    initNetwork();
    registerWithServer();
}

void loop() {
    // 1. 心跳维护
    if (millis() - last_heartbeat > 5000) {
        sendHeartbeat();
        last_heartbeat = millis();
    }

    // 2. TCP 指令处理（非阻塞）
    handleTCPCommands();

    // 3. 音频采集 → UDP 推流至中心
    if (state == STATE_LISTENING) {
        captureAndStreamAudio();
    }

    // 4. 音频播放（接收中心 TTS 广播）
    if (state == STATE_PLAYING) {
        playAudioBuffer();
    }

    delay(1);
}
```

### 关键模块说明

#### `audio.h` — I2S 音频采集/播放

```cpp
// I2S 配置：16kHz, 16bit, 单声道
// 输入：INMP441 (GPIO32=SD, GPIO33=SCK, GPIO25=WS)
// 输出：MAX98357A (GPIO26=DIN, GPIO27=BCLK, GPIO14=LRCK)

void initAudio() {
    // 输入 I2S
    i2s_config_t i2s_in = {
        .mode = i2s_mode_t(I2S_MODE_MASTER | I2S_MODE_RX),
        .sample_rate = 16000,
        .bits_per_sample = I2S_BITS_PER_SAMPLE_16BIT,
        .channel_format = I2S_CHANNEL_FMT_ONLY_LEFT,
        .communication_format = I2S_COMM_FORMAT_STAND_I2S,
        .intr_alloc_flags = ESP_INTR_FLAG_LEVEL1,
        .dma_buf_count = 4,
        .dma_buf_len = 256
    };
    i2s_driver_install(I2S_NUM_0, &i2s_in, 0, NULL);
    i2s_set_pin(I2S_NUM_0, &pin_in);

    // 输出 I2S
    i2s_config_t i2s_out = {
        .mode = i2s_mode_t(I2S_MODE_MASTER | I2S_MODE_TX),
        // ... 同参数 ...
    };
    i2s_driver_install(I2S_NUM_1, &i2s_out, 0, NULL);
    i2s_set_pin(I2S_NUM_1, &pin_out);
}
```

#### `network.h` — WiFi + UDP/TCP 通信

```cpp
// UDP：音频推流至中心 (PC_IP:5555)
// TCP：指令接收 (监听端口 5556)
// 自动重连机制，断线后 3s 重试
// mDNS 可选：st-lacrs-node.local 发现中心主机
```

#### `command.h` — 指令解析

```cpp
// 支持指令：
// - relay_set:  控制继电器开关
// - ir_send:    发射红外码（NEC/Sony/RC5/Raw）
// - ir_learn:   学习红外码并存储
// - sensor_read:读取传感器数据
// - state_set:  切换节点状态（IDLE/LISTENING/PLAYING）
// - restart:    重启节点
// - ota:        OTA 固件更新
```

#### `gpio_control.h` — 外设抽象

```cpp
enum DeviceType { RELAY, IR_TX, IR_RX, DHT22, NEOPIXEL };

struct DeviceConfig {
    DeviceType type;
    uint8_t pin;
    String label;  // 如 "客厅主灯", "卧室空调"
};

// 统一命令分发
void executeCommand(const String& action, const JsonObject& params);
```

---

## 家电控制工具集 — `home_control.py`（规划）

作为 AI 工具的注册模块，让 LLM 可以直接调用家电控制：

```python
# 注册给 LLM 的 Function Calling 工具

tools = [
    {
        "name": "control_device",
        "description": "控制家中家电设备。支持开/关灯、调节空调温度、控制窗帘等。",
        "parameters": {
            "type": "object",
            "properties": {
                "room": {"type": "string", "description": "房间名：客厅/卧室/厨房/书房"},
                "device": {"type": "string", "description": "设备名：灯/空调/电视/风扇/窗帘"},
                "action": {"type": "string", "description": "动作：on/off/toggle"},
                "value": {"type": "number", "description": "数值（如温度、亮度），可选"}
            }
        }
    },
    {
        "name": "read_sensor",
        "description": "读取家中传感器数据",
        "parameters": {
            "type": "object",
            "properties": {
                "room": {"type": "string"},
                "sensor": {"type": "string", "description": "传感器类型：temperature/humidity/light"}
            }
        }
    },
    {
        "name": "activate_scene",
        "description": "执行预设智能场景",
        "parameters": {
            "type": "object",
            "properties": {
                "scene": {"type": "string", "description": "场景名：影院模式/离家模式/晚安模式/起床模式"}
            }
        }
    }
]
```

### 场景预设配置（规划）

```json
{
    "scenes": {
        "影院模式": {
            "客厅灯": "off",
            "客厅窗帘": "close",
            "投影仪": "on",
            "客厅氛围灯": {"brightness": 30, "color": "warm"}
        },
        "离家模式": {
            "全屋灯": "off",
            "全屋空调": "off",
            "全屋窗帘": "close",
            "安防": "arm"
        },
        "晚安模式": {
            "全屋灯": "off",
            "卧室窗帘": "close",
            "卧室空调": {"temp": 26, "mode": "sleep"}
        }
    }
}
```

---

## 预期性能指标（规划）

| 指标 | 目标值 | 备注 |
|------|--------|------|
| 唤醒响应延迟 | < 800ms | 含网络传输 + 唤醒词检测 |
| 音频流延迟 | < 50ms | ESP32 → PC UDP 延迟 |
| TTS 广播延迟 | < 100ms | PC → 所有节点 |
| 节点待机功耗 | < 1W | ESP32 modem sleep |
| 单节点最大距离 | 视 Wi-Fi 覆盖 | 建议同网段，< 30m 无遮挡 |
| 最大节点数 | 8 | 受 UDP 带宽限制，可扩展 |
| 语音识别准确率 | > 95% (安静环境) | faster-whisper small |
