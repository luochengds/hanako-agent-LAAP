#!/usr/bin/env python3
"""
laap-say：Hermes 集成版流式语音输出
既保存音频文件，又实时播放到扬声器
"""

import asyncio
import edge_tts
import sys
import subprocess
from datetime import datetime
import os

VOICE = "zh-CN-XiaoxiaoNeural"
AUDIO_DIR = os.path.join(os.path.dirname(__file__), "..", "audio_cache")
os.makedirs(AUDIO_DIR, exist_ok=True)


async def say(text: str):
    """生成 → 保存文件 → 同时流式播放"""
    if not text.strip():
        return

    communicate = edge_tts.Communicate(text.strip(), VOICE)

    # 准备文件保存
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = os.path.join(AUDIO_DIR, f"aris_{timestamp}.mp3")

    # 同时：保存到文件 + 通过 ffplay 播放
    # 用 tee 的方式：edge-tts 输出分流
    audio_data = bytearray()

    # 启动 ffplay 播放器
    ffplay = subprocess.Popen(
        ["ffplay", "-nodisp", "-autoexit", "-i", "pipe:0",
         "-loglevel", "quiet", "-window_title", "Aris 语音"],
        stdin=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )

    # 边生成边播放和保存
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio_data.extend(chunk["data"])
            ffplay.stdin.write(chunk["data"])

    ffplay.stdin.close()
    ffplay.wait()

    # 保存文件
    with open(filename, "wb") as f:
        f.write(audio_data)

    size_kb = len(audio_data) / 1024
    print(f"✅ 已播放并保存: {filename} ({size_kb:.0f} KB)")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        asyncio.run(say(" ".join(sys.argv[1:])))
    elif not sys.stdin.isatty():
        text = sys.stdin.read()
        asyncio.run(say(text))
    else:
        print("🔊 用法: python laap_say.py '你要说的话'")
