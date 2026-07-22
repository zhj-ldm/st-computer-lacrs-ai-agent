"""
项目依赖一键安装脚本

用法：
    python install_deps.py

说明：
    - 直接使用当前 Python 环境安装依赖（pip install），不创建虚拟环境。
    - 仅安装跨平台依赖；pywin32 / pythoncom / winreg 为 Windows 专属，
      在非 Windows 平台自动跳过（这些模块在 macOS 上不可用，TTS 相关功能仅 Windows 生效）。
    - 语音模型（data/hey_computer.onnx、data/melspectrogram.onnx、
      data/embedding_model.onnx）已随项目附带，无需联网下载。
    - faster-whisper 首次运行会自动下载 small 模型（约 1GB），已配置 hf-mirror.com 镜像。
"""

import os
import sys
import subprocess

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ── 跨平台依赖清单（PyPI 包名） ──
# 注意：pywin32 / pythoncom / winreg 仅 Windows 需要，不在列表中。
DEPS = [
    "flask",
    "requests",
    "numpy",
    "pyaudio",
    "openwakeword",
    "faster-whisper",
    "baidusearch",
    "ddgs",
    "beautifulsoup4",
    "send2trash",
]


def pip_install(pkg):
    """安装单个包，返回是否成功"""
    print(f"\n>> pip install {pkg}")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--upgrade", pkg],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"  安装失败：{result.stderr.strip().splitlines()[-1] if result.stderr else '未知错误'}")
        return False
    print("  安装成功")
    return True


def main():
    print("=" * 50)
    print("  LCARS AI Agent — 依赖安装")
    print("=" * 50)

    # 1. 升级 pip
    print("\n[准备] 升级 pip ...")
    subprocess.run([sys.executable, "-m", "pip", "install", "--upgrade", "pip"],
                   capture_output=True, text=True)

    # 2. 安装依赖
    print(f"\n[安装] 共 {len(DEPS)} 个跨平台依赖：")
    for p in DEPS:
        print(f"  - {p}")

    failed = []
    for pkg in DEPS:
        ok = pip_install(pkg)
        if not ok:
            failed.append(pkg)

    # 3. 结果汇报
    print("\n" + "=" * 50)
    if failed:
        print(f"[完成] 以下 {len(failed)} 个包未安装成功：")
        for p in failed:
            print(f"  - {p}")
        print("\n请根据上述提示解决后重新运行本脚本。")
    else:
        print("[完成] 所有依赖已安装成功。")
        print("\n后续步骤：")
        print("  1. 启动 Web 服务：  python app.py")
        print("  2. 启动语音助手：    python voice_assistant.py")
        print("     （语音/TTS 功能依赖 Windows SAPI，macOS 仅 Web 界面可用）")

    print("=" * 50)


if __name__ == "__main__":
    main()
