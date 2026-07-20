import json
import os
import sys
import subprocess
import uuid
import time
import requests
from flask import Flask, render_template, request, jsonify, Response, stream_with_context

app = Flask(__name__)
app.secret_key = os.urandom(24).hex()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
CONV_DIR = os.path.join(DATA_DIR, "conversations")
os.makedirs(CONV_DIR, exist_ok=True)

# ── 读取配置 ──────────────────────────────────────────────

CONFIG_PATH = os.path.join(DATA_DIR, "config.json")

def load_config():
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)

def save_config(cfg):
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=4)

CFG = load_config()
API_BASE = CFG["api"]["base"]
API_KEY = CFG["api"]["key"]
MODEL = CFG["api"]["model"]

PATH_CFG = CFG

HOME = PATH_CFG["home"]
PATH_LINES = "\n".join(
    f"- {name} → {path}" for name, path in PATH_CFG["paths"].items()
)

SYSTEM_PROMPT = (
    "注意：以下是语音识别转写的结果，可能存在语序混乱或转写错误，请先判断并理解用户的真实意图后再作答。"
    "你是一个问什么回答什么的星际迷航风格语音对话电脑，当你的回复简短的朗读版介绍（尽量精简，只概括要点，不读代码和链接），你的回答不要包含井号之类的特殊标记符号，如果有很需要长篇大论解释的请询问用户是否完整说明或者存放到指定文件夹。"
    f"你是运行在 Windows 上的 AI 助手，可以操作文件和执行命令。"
    f"用户主目录是 {HOME}。路径映射：\n{PATH_LINES}\n"
    "用户说简称时自动转为完整路径。"
    "始终使用简体中文回复，不要使用繁体中文。"
)

# ── 工具定义 ──────────────────────────────────────────────

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "联网搜索，返回标题、链接和摘要。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索关键词"},
                    "max_results": {"type": "integer", "description": "结果数量，默认 5"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "读取文本文件内容。",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "文件绝对路径"},
                },
                "required": ["file_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "写入文件，会覆盖已有文件。",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "文件绝对路径"},
                    "content": {"type": "string", "description": "要写入的内容"},
                },
                "required": ["file_path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_directory",
            "description": "列出目录内容。",
            "parameters": {
                "type": "object",
                "properties": {
                    "dir_path": {"type": "string", "description": "目录绝对路径"},
                },
                "required": ["dir_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_shell",
            "description": "执行 shell 命令（危险命令会拒绝）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "要执行的命令"},
                },
                "required": ["command"],
            },
        },
    },
    # ── TTS 语音控制 ──
    {
        "type": "function",
        "function": {
            "name": "set_voice_rate",
            "description": "设置 TTS 朗读语速。用户说'读快点/慢点/语速调到X'时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "rate": {"type": "integer", "description": "语速 -10 到 10，0=正常，正数=快，负数=慢"},
                },
                "required": ["rate"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_voice",
            "description": "切换 TTS 音色。可用音色：huihui(慧慧)/kangkang(康康)/yaoyao(瑶瑶)/zira(Zira英文)/hazel(Hazel英文)。",
            "parameters": {
                "type": "object",
                "properties": {
                    "voice": {"type": "string", "description": "音色名称，如 huihui, kangkang, yaoyao"},
                },
                "required": ["voice"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_voices",
            "description": "列出所有可用的 TTS 音色。",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    # ── 对话管理 ──
    {
        "type": "function",
        "function": {
            "name": "list_all_conversations",
            "description": "列出所有历史对话。",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_new_conversation",
            "description": "创建一个新对话。",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "对话标题，默认'新对话'"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "switch_conversation",
            "description": "切换到指定对话（按标题关键词或ID）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "对话标题关键词或ID"},
                },
                "required": ["keyword"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_conversation",
            "description": "删除指定对话（按标题关键词或ID）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "要删除的对话标题关键词或ID"},
                },
                "required": ["keyword"],
            },
        },
    },
]

DANGEROUS = [
    "rm -rf /", "mkfs", "dd if=", ":(){ :|:& };:",
    "shutdown", "reboot", "halt", "poweroff", "chmod 777 /", "chown -R",
]

# ── 工具执行 ──────────────────────────────────────────────

def _web_search(query, max_results=5):
    if not query:
        return "关键词为空"
    from ddgs import DDGS
    results = []
    with DDGS() as d:
        for r in d.text(query, max_results=max(max_results, 1)):
            results.append(f"- [{r.get('title','')}]({r.get('href','')})\n  {r.get('body','')}")
    return "\n\n".join(results) if results else "无结果"

def _read_file(file_path):
    p = os.path.expanduser(file_path)
    if not os.path.isfile(p):
        return f"文件不存在: {p}"
    try:
        with open(p, "r") as f:
            c = f.read()
        return c[:8000] + ("\n...(截断)" if len(c) > 8000 else "")
    except UnicodeDecodeError:
        return "非文本文件"
    except PermissionError:
        return "权限不足"

def _write_file(file_path, content):
    p = os.path.expanduser(file_path)
    try:
        os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
        with open(p, "w") as f:
            f.write(content)
        return f"已写入: {p} ({len(content)} 字符)"
    except PermissionError:
        return "权限不足"

def _list_dir(dir_path):
    p = os.path.expanduser(dir_path) if dir_path else HOME
    if not os.path.isdir(p):
        return f"目录不存在: {p}"
    items = sorted(os.listdir(p))
    lines = [f"目录 {p} ({len(items)} 项):"]
    for item in items[:100]:
        full = os.path.join(p, item)
        tag = "[D]" if os.path.isdir(full) else "[F]"
        lines.append(f"  {tag} {item}")
    return "\n".join(lines)

def _run_shell(command):
    for kw in DANGEROUS:
        if kw.replace(" ", "") in command.lower().replace(" ", ""):
            return f"危险命令已拒绝: {kw}"
    try:
        r = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=30, cwd=HOME)
        out = r.stdout.strip()[:3000]
        err = r.stderr.strip()[:1000]
        parts = [out] if out else []
        if err:
            parts.append(f"[stderr]\n{err}")
        return "\n".join(parts) if parts else f"执行完毕 (返回码 {r.returncode})"
    except subprocess.TimeoutExpired:
        return "超时 (30s)"

# ── 共享状态文件（通知 voice_assistant.py 执行副作用） ──
PENDING_ACTION_FILE = os.path.join(DATA_DIR, "pending_action.json")

def _pending_action(action):
    """写入待处理动作，voice_assistant.py 读取并执行后清除"""
    actions = []
    if os.path.exists(PENDING_ACTION_FILE):
        try:
            with open(PENDING_ACTION_FILE, "r") as f:
                actions = json.load(f)
        except Exception:
            pass
    actions.append(action)
    with open(PENDING_ACTION_FILE, "w") as f:
        json.dump(actions, f, ensure_ascii=False)

# ── TTS 控制执行器 ──

VOICES_INFO = {
    "huihui":  {"name": "慧慧", "lang": "中文女声", "token": "MSTTS_V110_zhCN_HuihuiM"},
    "kangkang":{"name": "康康", "lang": "中文男声", "token": "MSTTS_V110_zhCN_KangkangM"},
    "yaoyao":  {"name": "瑶瑶", "lang": "中文女声", "token": "MSTTS_V110_zhCN_YaoyaoM"},
    "zira":    {"name": "Zira",  "lang": "英文女声", "token": "MSTTS_V110_enUS_ZiraM"},
    "hazel":   {"name": "Hazel", "lang": "英文女声", "token": "MSTTS_V110_enGB_HazelM"},
}

def _set_voice_rate(rate):
    rate = max(-10, min(10, int(rate)))
    cfg = load_config()
    cfg["tts"]["rate"] = rate
    save_config(cfg)
    global CFG
    CFG = cfg
    _pending_action({"type": "set_rate", "value": rate})
    return f"语速已设为 {rate}（-10~10，当前音色 {cfg['tts'].get('voice','huihui')}）"

def _set_voice(voice):
    voice = voice.strip().lower()
    if voice not in VOICES_INFO:
        names = ", ".join(f"{k}({v['name']})" for k, v in VOICES_INFO.items())
        return f"未知音色: {voice}。可用: {names}"
    cfg = load_config()
    cfg["tts"]["voice"] = voice
    save_config(cfg)
    global CFG
    CFG = cfg
    _pending_action({"type": "set_voice", "value": voice})
    return f"音色已切换为 {VOICES_INFO[voice]['name']}（{VOICES_INFO[voice]['lang']}）"

def _list_voices():
    lines = []
    for k, v in VOICES_INFO.items():
        lines.append(f"- {k}: {v['name']} ({v['lang']})")
    return "可用音色:\n" + "\n".join(lines)

# ── 对话管理执行器 ──

def _list_all_conversations():
    convs = list_conversations()
    if not convs:
        return "暂无历史对话"
    lines = []
    for c in convs:
        lines.append(f"- [{c['id']}] {c['title']} ({c['created_at']})")
    return "历史对话:\n" + "\n".join(lines)

def _create_new_conversation(title="新对话"):
    conv = create_conversation(title)
    _pending_action({"type": "new_conv", "conv_id": conv["id"], "title": title})
    return f"已创建对话「{title}」(ID: {conv['id']})，当前对话已切换"

def _switch_conversation(keyword):
    keyword = keyword.strip()
    convs = list_conversations()
    # 先按 ID 匹配
    for c in convs:
        if c["id"] == keyword:
            _pending_action({"type": "switch_conv", "conv_id": c["id"], "title": c["title"]})
            return f"已切换到对话「{c['title']}」(ID: {c['id']})"
    # 再按标题关键词匹配
    for c in convs:
        if keyword.lower() in c["title"].lower():
            _pending_action({"type": "switch_conv", "conv_id": c["id"], "title": c["title"]})
            return f"已切换到对话「{c['title']}」(ID: {c['id']})"
    return f"未找到包含「{keyword}」的对话"

def _delete_conversation(keyword):
    keyword = keyword.strip()
    convs = list_conversations()
    target = None
    for c in convs:
        if c["id"] == keyword:
            target = c
            break
    if not target:
        for c in convs:
            if keyword.lower() in c["title"].lower():
                target = c
                break
    if not target:
        return f"未找到包含「{keyword}」的对话"
    p = _conv_path(target["id"])
    os.remove(p)
    _pending_action({"type": "delete_conv", "conv_id": target["id"], "title": target["title"]})
    return f"已删除对话「{target['title']}」(ID: {target['id']})"

EXECUTORS = {
    "web_search": _web_search,
    "read_file": _read_file,
    "write_file": _write_file,
    "list_directory": _list_dir,
    "run_shell": _run_shell,
    "set_voice_rate": _set_voice_rate,
    "set_voice": _set_voice,
    "list_voices": _list_voices,
    "list_all_conversations": _list_all_conversations,
    "create_new_conversation": _create_new_conversation,
    "switch_conversation": _switch_conversation,
    "delete_conversation": _delete_conversation,
}

# ── 对话存储 ──────────────────────────────────────────────

def _conv_path(cid):
    return os.path.join(CONV_DIR, f"{cid}.json")

def load_conversation(cid):
    p = _conv_path(cid)
    if not os.path.exists(p):
        return None
    with open(p, "r") as f:
        return json.load(f)

def save_conversation(conv):
    with open(_conv_path(conv["id"]), "w") as f:
        json.dump(conv, f, ensure_ascii=False, indent=2)

def list_conversations():
    convs = []
    for fn in sorted(os.listdir(CONV_DIR), reverse=True):
        if fn.endswith(".json"):
            try:
                with open(os.path.join(CONV_DIR, fn), "r") as f:
                    c = json.load(f)
                convs.append({"id": c["id"], "title": c.get("title", "新对话"), "created_at": c.get("created_at", "")})
            except Exception:
                pass
    return convs

def create_conversation(title="新对话"):
    cid = uuid.uuid4().hex[:12]
    conv = {
        "id": cid,
        "title": title,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "messages": [],
    }
    save_conversation(conv)
    return conv

# ── API 调用 ──────────────────────────────────────────────

def call_api(messages):
    for _ in range(8):
        resp = requests.post(
            f"{API_BASE}/chat/completions",
            headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
            json={"model": MODEL, "messages": messages, "tools": TOOLS, "tool_choice": "auto"},
            timeout=90,
        )
        resp.raise_for_status()
        choice = resp.json()["choices"][0]
        msg = choice["message"]

        if msg.get("tool_calls"):
            messages.append(msg)
            for tc in msg["tool_calls"]:
                name = tc["function"]["name"]
                try:
                    args = json.loads(tc["function"]["arguments"])
                except json.JSONDecodeError:
                    args = {}
                fn = EXECUTORS.get(name)
                try:
                    result = fn(**args) if fn else f"未知工具: {name}"
                except Exception as e:
                    result = f"工具执行异常: {e}"
                messages.append({"role": "tool", "tool_call_id": tc["id"], "content": result})
            continue

        return msg.get("content", "")
    return "工具调用轮数超限，请简化请求。"

# ── 路由 ──────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/conversations", methods=["GET"])
def api_list_convs():
    return jsonify(list_conversations())

@app.route("/api/conversations", methods=["POST"])
def api_create_conv():
    data = request.get_json(silent=True) or {}
    title = data.get("title", "新对话")
    conv = create_conversation(title=title)
    return jsonify(conv)

@app.route("/api/conversations/<cid>", methods=["GET"])
def api_get_conv(cid):
    conv = load_conversation(cid)
    if not conv:
        return jsonify({"error": "对话不存在"}), 404
    return jsonify(conv)

@app.route("/api/conversations/<cid>", methods=["DELETE"])
def api_delete_conv(cid):
    p = _conv_path(cid)
    if os.path.exists(p):
        os.remove(p)
    return jsonify({"ok": True})

@app.route("/api/chat", methods=["POST"])
def chat():
    try:
        data = request.get_json()
        user_message = data.get("message", "").strip()
        conv_id = data.get("conversation_id", "")

        if not user_message:
            return jsonify({"error": "消息不能为空"}), 400

        conv = load_conversation(conv_id) if conv_id else None
        if not conv:
            conv = create_conversation()
            conv_id = conv["id"]

        history = conv.get("messages", [])
        messages = [{"role": "system", "content": SYSTEM_PROMPT}] + history + [{"role": "user", "content": user_message}]

        try:
            reply = call_api(messages)
        except requests.exceptions.Timeout:
            return jsonify({"error": "请求超时"}), 504
        except requests.exceptions.RequestException as e:
            return jsonify({"error": f"API 错误: {e}"}), 502

        history.append({"role": "user", "content": user_message})
        history.append({"role": "assistant", "content": reply})

        if len(history) == 2:
            conv["title"] = user_message[:20] + ("..." if len(user_message) > 20 else "")

        conv["messages"] = history
        save_conversation(conv)

        return jsonify({"reply": reply, "conversation_id": conv_id, "title": conv["title"]})
    except Exception as e:
        return jsonify({"error": f"服务器内部错误: {e}"}), 500

# ── 设置 API ──────────────────────────────────────────────

@app.route("/api/config", methods=["GET"])
def api_get_config():
    return jsonify(load_config())

@app.route("/api/config", methods=["PUT"])
def api_update_config():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "请求体为空"}), 400
    cfg = load_config()
    _deep_update(cfg, data)
    save_config(cfg)
    # 热更新模块级变量
    global API_BASE, API_KEY, MODEL
    API_BASE = cfg["api"]["base"]
    API_KEY = cfg["api"]["key"]
    MODEL = cfg["api"]["model"]
    return jsonify({"ok": True})

def _deep_update(d, u):
    for k, v in u.items():
        if isinstance(v, dict) and isinstance(d.get(k), dict):
            _deep_update(d[k], v)
        else:
            d[k] = v

@app.route("/api/voices", methods=["GET"])
def api_list_voices():
    try:
        from win32com.client import Dispatch
        tts = Dispatch("SAPI.SpVoice")
        voices = [v.GetDescription() for v in tts.GetVoices()]

        # OneCore 语音
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
                    voices.append(f"[OneCore] {name}")
                    winreg.CloseKey(tk)
                    i += 1
                except OSError:
                    break
            winreg.CloseKey(key)
        except Exception:
            pass

        return jsonify(voices)
    except Exception as e:
        return jsonify([])

app.config["TEMPLATES_AUTO_RELOAD"] = True

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8086, debug=False)
