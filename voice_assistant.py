"""
语音助手 — 唤醒词 "computer"
唤醒 → 录音 → ASR → AI 对话 → TTS 朗读
对话统一存入「语音对话」会话，Web 端实时可见
"""

import os
import sys
import time
import wave
import threading
import json
import traceback

import numpy as np
import pyaudio
import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
WAKE_SOUND = os.path.join(DATA_DIR, "wake_sound.wav")

# ── 音频参数 ──────────────────────────────────
SAMPLE_RATE = 16000
CHUNK_DURATION = 0.08
CHUNK_SIZE = int(SAMPLE_RATE * CHUNK_DURATION)  # 1280
FORMAT = pyaudio.paInt16
CHANNELS = 1

# ── VAD / 录音 ────────────────────────────────
SILENCE_THRESHOLD = 400
SILENCE_SEC = 1.5
MAX_RECORD_SEC = 15
MIN_RECORD_SEC = 0.5
SILENCE_FRAMES = int(SILENCE_SEC / CHUNK_DURATION)

# ── 唤醒词 ────────────────────────────────────
WAKE_WORD = "hey_computer"
WAKE_MODEL_PATH = os.path.join(DATA_DIR, "hey_computer.onnx")
WAKE_THRESHOLD = 0.15

# ── API ───────────────────────────────────────
API_BASE = "http://127.0.0.1:8086"
CONV_TITLE = "语音对话"
CONFIG_PATH = os.path.join(DATA_DIR, "config.json")


# ═══════════════════════════════════════════════
#  工具函数
# ═══════════════════════════════════════════════

def load_config():
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)

def rms(audio):
    return float(np.sqrt(np.mean(np.square(audio.astype(np.float64)))))


def play_wav(path):
    try:
        wf = wave.open(path, 'rb')
        pa = pyaudio.PyAudio()
        st = pa.open(format=pa.get_format_from_width(wf.getsampwidth()),
                     channels=wf.getnchannels(), rate=wf.getframerate(),
                     output=True)
        chunk = wf.readframes(1024)
        while chunk:
            st.write(chunk)
            chunk = wf.readframes(1024)
        st.stop_stream(); st.close(); pa.terminate(); wf.close()
    except Exception:
        pass


# ═══════════════════════════════════════════════
#  Flask 后台
# ═══════════════════════════════════════════════

def _run_flask():
    sys.path.insert(0, BASE_DIR)
    from app import app
    app.run(host="127.0.0.1", port=8086, debug=False, use_reloader=False)


def wait_flask(timeout=10):
    start = time.time()
    while time.time() - start < timeout:
        try:
            r = requests.get(f"{API_BASE}/api/conversations", timeout=1)
            if r.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(0.3)
    return False


# ═══════════════════════════════════════════════
#  对话管理
# ═══════════════════════════════════════════════

def get_or_create_voice_conv():
    """查找标题为「语音对话」的会话，不存在则创建"""
    r = requests.get(f"{API_BASE}/api/conversations")
    convs = r.json()
    for c in convs:
        if c.get("title") == CONV_TITLE:
            print(f"[会话] 复用已有「语音对话」: {c['id']}")
            return c["id"]
    r = requests.post(f"{API_BASE}/api/conversations",
                      json={"title": CONV_TITLE})
    conv = r.json()
    print(f"[会话] 新建「语音对话」: {conv['id']}")
    return conv["id"]


def get_conv_list():
    """获取所有对话列表"""
    r = requests.get(f"{API_BASE}/api/conversations")
    return r.json()


def get_conv_title(conv_id):
    """获取指定对话的标题"""
    convs = get_conv_list()
    for c in convs:
        if c["id"] == conv_id:
            return c.get("title", "未知")
    return "未知"


def create_conv(title):
    """创建新对话"""
    r = requests.post(f"{API_BASE}/api/conversations",
                      json={"title": title})
    return r.json()["id"]


# ── 语音命令关键词匹配 ────────────────────────

CREATE_KEYWORDS = ["新建对话", "创建对话", "新对话", "开个对话", "创建一个对话", "建立一个对话"]

SWITCH_KEYWORDS = ["切换到", "切换对话", "打开对话", "进入对话", "换到", "切换至"]

# ── 语速 / 音色命令 ──────────────────────────
SPEED_UP_KW    = ["快一点", "加速", "语速加快", "快点", "说话快点", "读快点"]
SPEED_DOWN_KW  = ["慢一点", "减速", "语速减慢", "慢点", "说话慢点", "读慢点"]
SPEED_RESET_KW = ["语速恢复", "语速默认", "正常语速", "默认语速"]
SPEED_SET_KW   = ["语速调到", "语速设为", "语速调到", "设置语速"]

VOICE_LIST_KW  = ["切换音色", "换声音", "音色列表", "有什么声音", "有哪些声音"]
VOICE_SET_KW   = ["切换音色到", "换成音色", "音色设为", "用声音", "切换为音色"]

DEFAULT_RATE = 3

# 可用音色映射（名称关键词 → token 路径）
VOICE_MAP = {
    "huihui":   ("慧慧 (中文女声)", None),
    "kangkang": ("康康 (中文男声)", r"HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Speech_OneCore\Voices\Tokens\MSTTS_V110_zhCN_KangkangM"),
    "yaoyao":   ("瑶瑶 (中文女声)", r"HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Speech_OneCore\Voices\Tokens\MSTTS_V110_zhCN_YaoyaoM"),
    "zira":     ("Zira (英文美式)", None),
    "hazel":    ("Hazel (英文英式)", None),
}


def match_command(text):
    """
    关键词匹配语音命令。
    返回 (cmd_type, payload)
      cmd_type: "create" / "switch" / "list" / "speed_up" / "speed_down" /
               "speed_reset" / "speed_set" / "voice_list" / "voice_set" / None
      payload: 对话标题 / 语速值 / 音色名 / None
    """
    text_stripped = text.strip()

    # ── 语速命令 ──
    for kw in SPEED_UP_KW:
        if kw in text_stripped:
            return ("speed_up", None)

    for kw in SPEED_DOWN_KW:
        if kw in text_stripped:
            return ("speed_down", None)

    for kw in SPEED_RESET_KW:
        if kw in text_stripped:
            return ("speed_reset", None)

    for kw in SPEED_SET_KW:
        if text_stripped.startswith(kw):
            val = text_stripped[len(kw):].strip()
            try:
                return ("speed_set", int(val))
            except ValueError:
                return ("speed_set", None)

    # ── 音色命令 ──
    for kw in VOICE_LIST_KW:
        if kw in text_stripped:
            return ("voice_list", None)

    for kw in VOICE_SET_KW:
        if text_stripped.startswith(kw):
            name = text_stripped[len(kw):].strip()
            if name:
                return ("voice_set", name)
            else:
                return ("voice_list", None)

    # 快捷音色切换
    name_map = {
        "康康": "kangkang", "男声": "kangkang", "男音": "kangkang",
        "慧慧": "huihui",
        "瑶瑶": "yaoyao",  "女声": "huihui",  "女音": "huihui",
        "zira": "zira", "hazel": "hazel",
    }
    for kw, vkey in name_map.items():
        if kw in text_stripped:
            return ("voice_set", vkey)

    # ── 对话管理命令 ──
    for kw in CREATE_KEYWORDS:
        if text_stripped == kw or text_stripped.startswith(kw):
            return ("create", None)

    for kw in SWITCH_KEYWORDS:
        if text_stripped.startswith(kw):
            title = text_stripped[len(kw):].strip()
            if title.endswith("对话"):
                title = title[:-2].strip()
            if title:
                return ("switch", title)
            else:
                return ("list", None)

    return (None, None)


def handle_command(cmd_type, payload, current_conv_id):
    """
    执行命令，返回 (new_conv_id, speak_text)。
    new_conv_id 为 None 表示无变化。
    """
    if cmd_type == "create":
        title = payload if payload else "未命名对话"
        new_id = create_conv(title)
        return (new_id, f"已创建新对话「{title}」")

    elif cmd_type == "switch":
        convs = get_conv_list()
        # 精确匹配
        for c in convs:
            if c.get("title") == payload:
                return (c["id"], f"已切换到「{payload}」")
        # 模糊匹配（标题包含关键词）
        matches = [c for c in convs if payload in c.get("title", "")]
        if len(matches) == 1:
            c = matches[0]
            return (c["id"], f"已切换到「{c['title']}」")
        elif len(matches) > 1:
            titles = "、".join(f"「{c['title']}」" for c in matches)
            return (None, f"找到多个匹配：{titles}，请说具体一点")
        else:
            return (None, f"未找到对话「{payload}」")

    elif cmd_type == "list":
        convs = get_conv_list()
        if not convs:
            return (None, "当前没有任何对话")
        titles = []
        for i, c in enumerate(convs, 1):
            marker = " ← 当前" if c["id"] == current_conv_id else ""
            titles.append(f"第{i}个：{c['title']}{marker}")
        return (None, "对话列表：" + "；".join(titles))

    return (None, None)


def _clean_for_tts(text):
    """去掉 Markdown 和特殊符号，只保留 TTS 可朗读的纯文字"""
    import re
    # 去掉图片语法 ![alt](url)
    text = re.sub(r'!\[.*?\]\(.*?\)', '', text)
    # 去掉链接语法 [text](url)，保留链接文字
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    # 去掉行内代码 `code`
    text = re.sub(r'`[^`]+`', '', text)
    # 去掉加粗/斜体标记 ** * ~~
    text = re.sub(r'\*{1,3}', '', text)
    text = re.sub(r'~~', '', text)
    # 去掉标题 # 标记（行首的 # 及空格）
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    # 去掉无序列表标记 - * +（行首）
    text = re.sub(r'^[\-\*\+]\s+', '', text, flags=re.MULTILINE)
    # 去掉有序列表标记 1. 2. 等
    text = re.sub(r'^\d+\.\s+', '', text, flags=re.MULTILINE)
    # 去掉水平线 --- ***
    text = re.sub(r'^[\-\*]{3,}\s*$', '', text, flags=re.MULTILINE)
    # 去掉表格分隔符 |
    text = text.replace('|', ' ')
    # 去掉 HTML 标签 <...>
    text = re.sub(r'<[^>]+>', '', text)
    # 去掉反引号代码块标记 ```
    text = text.replace('```', '')
    # 多个连续空行压缩为单个换行
    text = re.sub(r'\n{3,}', '\n\n', text)
    # 去掉行首行尾空白
    text = text.strip()
    return text

def send_to_ai(conv_id, text):
    """发送消息给 AI，返回 (回复文本, 工具步骤列表)"""
    r = requests.post(f"{API_BASE}/api/chat",
                      json={"message": text, "conversation_id": conv_id},
                      timeout=120)
    data = r.json()
    if data.get("error"):
        return f"错误: {data['error']}", []
    return data.get("reply", ""), data.get("tool_steps", [])


# ═══════════════════════════════════════════════
#  语音助手
# ═══════════════════════════════════════════════

ONE_CORE_TOKEN_BASE = r"HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Speech_OneCore\Voices\Tokens"


def _get_all_sapi_voices():
    """返回所有可用 SAPI 语音的 (description, token_path_or_None) 列表。
    OneCore 语音带 token 路径，桌面语音 token 为 None。"""
    voices = []
    # Desktop 语音
    try:
        from win32com.client import Dispatch
        t = Dispatch("SAPI.SpVoice")
        for v in t.GetVoices():
            voices.append((v.GetDescription(), None))
    except Exception:
        pass

    # OneCore 语音（需通过 SetId 设置，不在 GetVoices 中）
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                             r"SOFTWARE\Microsoft\Speech_OneCore\Voices\Tokens")
        i = 0
        while True:
            try:
                sub = winreg.EnumKey(key, i)
                tk = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                    rf"SOFTWARE\Microsoft\Speech_OneCore\Voices\Tokens\{sub}")
                name = winreg.QueryValueEx(tk, "")[0]
                voices.append((name, sub))
                winreg.CloseKey(tk)
                i += 1
            except OSError:
                break
        winreg.CloseKey(key)
    except Exception:
        pass

    return voices


def _set_sapi_voice(tts, voice_name):
    """根据名称设置 SAPI 语音（自动区分桌面 / OneCore）。
    返回更新后的 tts 对象。"""
    from win32com.client import Dispatch

    for desc, token in _get_all_sapi_voices():
        if desc in voice_name:
            if token:
                # OneCore 语音：通过 token ID 设置
                tts.Voice = Dispatch("SAPI.SpObjectToken")
                tts.Voice.SetId(f"{ONE_CORE_TOKEN_BASE}\\{token}")
            else:
                # 桌面语音：通过 GetVoices 匹配
                for v in tts.GetVoices():
                    if voice_name in v.GetDescription():
                        tts.Voice = v
                        break
            return tts

    # Fallback：Huihui 桌面版
    print(f"[TTS] 未找到音色 '{voice_name}'，使用 Huihui 桌面版")
    for v in tts.GetVoices():
        if "Huihui" in v.GetDescription():
            tts.Voice = v
            break
    return tts


class VoiceAssistant:
    def __init__(self):
        self.pa = pyaudio.PyAudio()
        self.oww = None
        self.asr = None
        self.tts = None
        self.running = True
        self.speaking = False       # TTS 朗读期间暂停唤醒词检测
        self.tts_active = False     # TTS 后台线程是否在播
        self.tts_stop_flag = False  # 语音打断标志

        # 从配置文件读取阈值
        try:
            cfg = load_config()
            w = cfg.get("wake", {})
            global WAKE_THRESHOLD, SILENCE_THRESHOLD, SILENCE_SEC, SILENCE_FRAMES
            WAKE_THRESHOLD = w.get("threshold", WAKE_THRESHOLD)
            SILENCE_THRESHOLD = w.get("silence_threshold", SILENCE_THRESHOLD)
            SILENCE_SEC = w.get("silence_sec", SILENCE_SEC)
            SILENCE_FRAMES = int(SILENCE_SEC / CHUNK_DURATION)
            print(f"[配置] 唤醒={WAKE_THRESHOLD}, 静音阈值={SILENCE_THRESHOLD}, 静音时长={SILENCE_SEC}s")
        except Exception:
            pass

    def load_models(self):
        print("[模型] 加载唤醒词模型 ...")
        from openwakeword.model import Model
        self.oww = Model(wakeword_models=[WAKE_MODEL_PATH], inference_framework="onnx")
        print("[模型] 唤醒词就绪")

        print("[模型] 加载 ASR 模型 faster-whisper small ...")
        os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
        from faster_whisper import WhisperModel
        self.asr = WhisperModel("small", device="cpu", compute_type="int8",
                                num_workers=2, cpu_threads=4)
        print("[模型] ASR 就绪")

        print("[模型] 加载 TTS 引擎 (Windows SAPI) ...")
        from win32com.client import Dispatch
        self.tts = Dispatch("SAPI.SpVoice")

        # 从配置文件读取 TTS 设置
        try:
            cfg = load_config()
            tts_cfg = cfg.get("tts", {})
            voice_name = tts_cfg.get("voice", "Microsoft Huihui Desktop")
            self.tts.Rate = tts_cfg.get("rate", 3)
            self.tts.Volume = tts_cfg.get("volume", 100)
            self.processing_rate = tts_cfg.get("processing_rate", 1)
        except Exception:
            voice_name = "Microsoft Huihui Desktop"
            self.tts.Rate = 3
            self.tts.Volume = 100
            self.processing_rate = 1

        # 匹配语音（支持 OneCore）
        self.tts = _set_sapi_voice(self.tts, voice_name)
        print(f"[模型] TTS 就绪 — {self.tts.Voice.GetDescription()}, Rate={self.tts.Rate}")

    def speak(self, text):
        """后台异步朗读，不阻塞主循环（通过 self.tts_stop_flag 支持语音打断）"""
        text = _clean_for_tts(text)
        if not text or not text.strip():
            return

        self.tts_stop_flag = False
        self.tts_active = True

        def _speak_worker():
            import pythoncom
            pythoncom.CoInitialize()
            stopped = False
            try:
                # SVSFlagsAsync = 1: 异步朗读
                self.tts.Speak(text, 1)
                t0 = time.time()
                while not self.tts_stop_flag:
                    pythoncom.PumpWaitingMessages()
                    time.sleep(0.05)
                    try:
                        if self.tts.Status.RunningState == 0:
                            self.tts_stop_flag = False
                            break
                    except Exception:
                        break
                    # 2秒强制退出，回到监听
                    if time.time() - t0 > 5.0:
                        try:
                            rs = self.tts.Status.RunningState
                        except:
                            rs = "?"
                        print(f"[TTS] 超时退出（RunningState={rs}，已等2s）")
                        break
                if self.tts_stop_flag:
                    self.tts.Skip("Sentence", 2 ** 31 - 1)
                    self.tts.Speak("", 3)  # SVSFPurgeBeforeSpeak
                    stopped = True
                    print("[TTS] 已被语音打断")
            except Exception as e:
                print(f"[TTS错误] {e}")
            finally:
                pythoncom.CoUninitialize()
                self.tts_active = False
                if not stopped:
                    time.sleep(0.5)  # 正常播完后回声消散

        self.tts_thread = threading.Thread(target=_speak_worker, daemon=True)
        self.tts_thread.start()

    def wait_speak(self):
        """阻塞等待后台 TTS 完成（用于短命令等不需要打断的场景）"""
        if hasattr(self, 'tts_thread') and self.tts_thread and self.tts_thread.is_alive():
            self.tts_thread.join(timeout=30)
        self.tts_active = False

    def _speak_processing(self):
        """以独立语速朗读 Processing 提示，不随 AI 回复语速变化"""
        saved = self.tts.Rate
        try:
            self.tts.Rate = self.processing_rate
            self.tts.Speak("Processing", 0)
            time.sleep(0.5)
        except Exception as e:
            print(f"[TTS错误] {e}")
        finally:
            self.tts.Rate = saved

    def record_until_silence(self):
        """
        唤醒后录音，VAD 静音检测。
        返回 (audio_bytes, sample_width)
        """
        stream = self.pa.open(format=FORMAT, channels=CHANNELS,
                              rate=SAMPLE_RATE, input=True,
                              frames_per_buffer=CHUNK_SIZE)

        frames = []
        silence_count = 0
        has_speech = False
        record_start = time.time()
        print("[录音] 开始 ...")

        while self.running:
            data = stream.read(CHUNK_SIZE, exception_on_overflow=False)
            frames.append(data)
            audio = np.frombuffer(data, dtype=np.int16)
            energy = rms(audio)

            elapsed = time.time() - record_start

            if energy > SILENCE_THRESHOLD:
                has_speech = True
                silence_count = 0
            else:
                silence_count += 1

            # 静音超时且已检测到语音且超过最短录音 → 结束
            if has_speech and silence_count >= SILENCE_FRAMES and elapsed >= MIN_RECORD_SEC:
                break

            # 超长兜底
            if elapsed >= MAX_RECORD_SEC:
                break

        stream.stop_stream()
        stream.close()

        audio_bytes = b''.join(frames)
        duration = len(audio_bytes) / (SAMPLE_RATE * 2)
        print(f"[录音] 结束，时长 {duration:.1f}s")
        return audio_bytes

    def transcribe(self, audio_bytes):
        """Whisper 转写音频，返回文本或 None"""
        audio_np = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        segments, info = self.asr.transcribe(audio_np, beam_size=5,
                                              language=None,
                                              vad_filter=True,
                                              vad_parameters=dict(
                                                  threshold=0.5,
                                                  min_silence_duration_ms=300
                                              ))
        text = " ".join(s.text.strip() for s in segments).strip()
        return text if text else None

    def _set_voice(self, name):
        """切换音色，返回描述文本"""
        vkey = name.lower().strip()
        if vkey not in VOICE_MAP:
            available = "、".join(f"{v[0]}" for v in VOICE_MAP.values())
            return f"未找到音色「{name}」。可用音色：{available}"

        desc, token_path = VOICE_MAP[vkey]
        if token_path is None:
            # 桌面语音，用描述名称匹配
            for voice in self.tts.GetVoices():
                if vkey in voice.GetDescription().lower():
                    self.tts.Voice = voice
                    return f"已切换到{desc}"
            return f"未找到桌面音色 {desc}"
        else:
            # OneCore 语音，用 token 路径
            from win32com.client import Dispatch
            token = Dispatch("SAPI.SpObjectToken")
            token.SetId(token_path)
            self.tts.Voice = token
            return f"已切换到{desc}"

    def _set_rate(self, rate):
        """设置语速 (-10 ~ 10)，返回描述文本"""
        rate = max(-10, min(10, int(rate)))
        self.tts.Rate = rate
        return f"语速已设为 {rate}"

    def _handle_tts_command(self, cmd_type, payload):
        """处理语速/音色命令，返回 (speak_text, is_command)"""
        if cmd_type == "speed_up":
            new_rate = self.tts.Rate + 2
            return (self._set_rate(new_rate), True)

        elif cmd_type == "speed_down":
            new_rate = self.tts.Rate - 2
            return (self._set_rate(new_rate), True)

        elif cmd_type == "speed_reset":
            return (self._set_rate(DEFAULT_RATE), True)

        elif cmd_type == "speed_set":
            if payload is not None:
                return (self._set_rate(payload), True)
            else:
                return ("请说出语速数值，如：语速调到5", True)

        elif cmd_type == "voice_list":
            lines = ["可用音色："]
            for vkey, (desc, _) in VOICE_MAP.items():
                marker = ""
                try:
                    cur_desc = self.tts.Voice.GetDescription().lower()
                    if vkey in cur_desc:
                        marker = " ← 当前"
                except:
                    pass
                lines.append(f"  {desc}{marker}")
            return ("\n".join(lines), True)

        elif cmd_type == "voice_set":
            return (self._set_voice(payload), True)

        return (None, False)

    def _reload_tts_from_config(self):
        """从 config.json 重新加载并应用 TTS 设置（语音/语速/音量）"""
        try:
            cfg = load_config()
            tts_cfg = cfg.get("tts", {})
            voice_name = tts_cfg.get("voice", "huihui")
            self.tts.Rate = tts_cfg.get("rate", 3)
            self.tts.Volume = tts_cfg.get("volume", 100)
            self.processing_rate = tts_cfg.get("processing_rate", 1)

            # 支持短键（huihui/kangkang/yaoyao）和全名两种格式
            voice_lower = voice_name.lower()
            if voice_lower in VOICE_MAP:
                # 短键：直接用 VOICE_MAP 设置
                desc, token_path = VOICE_MAP[voice_lower]
                if token_path is None:
                    for v in self.tts.GetVoices():
                        if voice_lower in v.GetDescription().lower():
                            self.tts.Voice = v
                            break
                else:
                    from win32com.client import Dispatch
                    token = Dispatch("SAPI.SpObjectToken")
                    token.SetId(token_path)
                    self.tts.Voice = token
            else:
                # 全名：走原有 _set_sapi_voice 路径
                self.tts = _set_sapi_voice(self.tts, voice_name)
        except Exception:
            pass

    def _apply_pending_actions(self, conv_id):
        """读取 pending_action.json，执行 TTS 配置重载和对话切换，返回 (new_conv_id, note)"""
        pending_file = os.path.join(DATA_DIR, "pending_action.json")
        if not os.path.exists(pending_file):
            return (None, "")

        try:
            with open(pending_file, "r") as f:
                actions = json.load(f)
        except Exception:
            return (None, "")

        # 删除文件防止重复执行
        try:
            os.remove(pending_file)
        except Exception:
            pass

        notes = []
        new_conv_id = None

        for action in actions:
            atype = action.get("type", "")
            if atype in ("set_rate", "set_voice"):
                self._reload_tts_from_config()
                if atype == "set_rate":
                    notes.append(f"语速→{action.get('value')}")
                else:
                    notes.append(f"音色→{action.get('value')}")
            elif atype in ("new_conv", "switch_conv"):
                new_conv_id = action.get("conv_id")
                notes.append(f"对话→{action.get('title', new_conv_id)}")
            elif atype == "delete_conv":
                # 如果当前对话被删除，切到最新对话
                if conv_id == action.get("conv_id"):
                    convs = get_conv_list()
                    new_conv_id = convs[0]["id"] if convs else create_conv("新对话")
                    notes.append(f"当前对话已删除，切换→{new_conv_id}")
                else:
                    notes.append(f"删除对话「{action.get('title')}」")

        return (new_conv_id, "; ".join(notes) if notes else "")

    def _reopen_stream(self):
        """关闭旧 stream 并打开新 stream，回归初始监听状态"""
        time.sleep(2.0)  # 等待 TTS 回声充分消散
        if self.oww is not None:
            self.oww.reset()  # 重置 OWW 内部状态，彻底回到初始
        return self.pa.open(format=FORMAT, channels=CHANNELS,
                            rate=SAMPLE_RATE, input=True,
                            frames_per_buffer=CHUNK_SIZE)

    def listen_loop(self, conv_id):
        """主循环：持续监听唤醒词"""
        print(f"[监听] 进入监听模式，说 '{WAKE_WORD}' 唤醒 ...")
        stream = self.pa.open(format=FORMAT, channels=CHANNELS,
                              rate=SAMPLE_RATE, input=True,
                              frames_per_buffer=CHUNK_SIZE)
        self.speaking = False

        while self.running:
            try:
                data = stream.read(CHUNK_SIZE, exception_on_overflow=False)

                if self.speaking:
                    if not self.tts_active:
                        # TTS 播放完毕 → 回到监听
                        print("[完成] 本轮结束，回到监听\n")
                        if self.oww is not None:
                            self.oww.reset()
                        stream = self.pa.open(format=FORMAT, channels=CHANNELS,
                                              rate=SAMPLE_RATE, input=True,
                                              frames_per_buffer=CHUNK_SIZE)
                        self.speaking = False
                    continue

                audio = np.frombuffer(data, dtype=np.int16)
                pred = self.oww.predict(audio)
                score = pred.get(WAKE_WORD, 0.0)

                if score >= WAKE_THRESHOLD:
                    stream.stop_stream()
                    stream.close()

                    print(f"[唤醒] {WAKE_WORD} ({score:.2f})")
                    play_wav(WAKE_SOUND)

                    # 录音
                    audio_bytes = self.record_until_silence()
                    if len(audio_bytes) < SAMPLE_RATE * 2 * MIN_RECORD_SEC:
                        print("[跳过] 录音太短")
                        stream = self._reopen_stream()
                        continue

                    # ASR
                    print("[识别] 转写中 ...")
                    text = self.transcribe(audio_bytes)
                    if not text:
                        print("[识别] 无有效语音")
                        stream = self._reopen_stream()
                        continue

                    print(f"[识别] {text}")

                    # ── 语音命令匹配 ──
                    cmd_type, payload = match_command(text)
                    if cmd_type:
                        print(f"[命令] {cmd_type} {payload or ''}")

                        # 先检查 TTS 控制命令（语速 / 音色）
                        speak_text, is_cmd = self._handle_tts_command(cmd_type, payload)
                        if is_cmd:
                            self.speaking = True
                            self.speak(speak_text)
                            self.wait_speak()
                            print("[完成] TTS 命令执行完毕，回到监听\n")
                            stream = self._reopen_stream()
                            self.speaking = False
                            continue

                        # 对话管理命令
                        new_id, speak_text = handle_command(cmd_type, payload, conv_id)
                        self.speaking = True
                        self.speak(speak_text)
                        self.wait_speak()
                        if new_id:
                            conv_id = new_id
                            print(f"[会话] 已切换到: {conv_id} ({get_conv_title(conv_id)})")
                        print("[完成] 命令执行完毕，回到监听\n")
                        stream = self._reopen_stream()
                        self.speaking = False
                        continue

                    # 播放提示音 → 发送 AI → TTS 朗读回复（后台异步 + 语音打断）
                    print("[AI] 发送中 ...")
                    self.speaking = True
                    play_wav(os.path.join(DATA_DIR, "complete.wav"))
                    reply, tool_steps = send_to_ai(conv_id, text)

                    # 处理 AI 工具调用产生的副作用（TTS 配置变更 / 对话切换）
                    new_cid, action_note = self._apply_pending_actions(conv_id)
                    if new_cid:
                        conv_id = new_cid
                        print(f"[会话] AI 已切换到: {conv_id} ({get_conv_title(conv_id)})")
                    if action_note:
                        print(f"[动作] {action_note}")

                    for step in tool_steps:
                        print(f"[步骤] {step}")
                        # 密码验证音效：步骤中检测"PASSWORD_REQUIRED"→错误
                        if "PASSWORD_REQUIRED" in step:
                            play_wav(os.path.join(DATA_DIR, "error.wav"))
                    # 密码正确：从 AI 回复中检测"密码正确"→验证音效
                    if "密码正确" in reply:
                        play_wav(os.path.join(DATA_DIR, "command_code_verify.wav"))
                    print(f"[AI] {reply}")
                    self._stop_energy_frames = 0
                    self.tts_stop_flag = False
                    self.speak(reply)  # 异步，立即返回

                    # 立即打开流（无延迟），主循环 speaking 分支接管打断检测
                    stream = self.pa.open(format=FORMAT, channels=CHANNELS,
                                          rate=SAMPLE_RATE, input=True,
                                          frames_per_buffer=CHUNK_SIZE)
                    # 注意：self.speaking 保持 True，由主循环判断 TTS 是否结束

            except OSError as e:
                # 音频设备异常，自动重建 stream，失败则循环重试
                errno = getattr(e, 'errno', 'N/A')
                print(f"[音频] 设备异常 (errno={errno})，重建音频流 ...")
                traceback.print_exc()
                try:
                    stream.close()
                except Exception:
                    pass
                for attempt in range(1, 11):
                    try:
                        time.sleep(2)
                        stream = self.pa.open(format=FORMAT, channels=CHANNELS,
                                              rate=SAMPLE_RATE, input=True,
                                              frames_per_buffer=CHUNK_SIZE)
                        if self.oww is not None:
                            self.oww.reset()
                        print(f"[音频] 音频流已重建（第 {attempt} 次尝试）")
                        break
                    except Exception as e2:
                        print(f"[音频] 重建失败（第 {attempt} 次）: {e2}")
                        if attempt == 10:
                            print("[音频] 重建 10 次均失败，退出监听")
                            self.running = False
            except Exception as e:
                traceback.print_exc()
                time.sleep(0.5)

        stream.stop_stream()
        stream.close()

    def cleanup(self):
        self.pa.terminate()


# ═══════════════════════════════════════════════
#  入口
# ═══════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 50)
    print(f"  Voice Assistant — 唤醒词: {WAKE_WORD}")
    print("=" * 50)

    # 1. 启动 Flask
    print("[启动] 后台启动 Web 服务 ...")
    threading.Thread(target=_run_flask, daemon=True).start()

    if not wait_flask():
        print("[错误] Flask 启动超时")
        sys.exit(1)
    print("[启动] Web 服务就绪 (http://127.0.0.1:8086)")

    # 2. 获取/创建语音对话
    conv_id = get_or_create_voice_conv()

    # 3. 初始化语音助手
    va = VoiceAssistant()
    try:
        va.load_models()
        print("\n" + "=" * 50)
        print(f"  一切就绪，说 '{WAKE_WORD}' 开始对话")
        print("  按 Ctrl+C 退出")
        print("=" * 50 + "\n")
        va.listen_loop(conv_id)
    except KeyboardInterrupt:
        print("\n[退出] 再见")
    finally:
        va.cleanup()
