#!/usr/bin/env python3
"""
流式语音输出：edge-tts 直接播放到电脑扬声器
用法：python stream_tts.py "要说的话"
      或  piped: echo "你好" | python stream_tts.py
"""

import asyncio
import edge_tts
import sys
import subprocess
import os

FFPLAY_PATH = "ffplay"  # 在 PATH 中（xiaozhi-esp32-server 自带）
VOICE = "zh-CN-XiaoxiaoNeural"
RATE = "24000"  # edge-tts 默认采样率


async def say(text: str):
    """流式生成并播放语音——生成的同时开始播放，真正流式输出"""
    if not text.strip():
        return

    communicate = edge_tts.Communicate(text.strip(), VOICE)

    # ffplay 从 stdin 读取 MP3 流并实时播放
    # -nodisp: 不显示窗口
    # -autoexit: 播完自动退出
    # -loglevel quiet: 不输出日志
    ffplay = subprocess.Popen(
        [
            FFPLAY_PATH, "-nodisp", "-autoexit",
            "-i", "pipe:0",
            "-loglevel", "quiet",
        ],
        stdin=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )

    # 边生成边喂给 ffplay——实现真正的流式播放
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            ffplay.stdin.write(chunk["data"])

    ffplay.stdin.close()
    ffplay.wait()


async def interactive_loop():
    """交互模式：连续输入，逐句朗读"""
    print("🔊 流式 TTS 已启动（输入 Ctrl+C 或空行退出）")
    print("─" * 50)
    while True:
        try:
            text = input(">>> ")
            if not text.strip():
                break
            await say(text)
        except (EOFError, KeyboardInterrupt):
            break
    print("\n👋 退出")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        # 命令行模式
        asyncio.run(say(" ".join(sys.argv[1:])))
    elif not sys.stdin.isatty():
        # 管道模式
        text = sys.stdin.read()
        asyncio.run(say(text))
    else:
        # 交互模式
        asyncio.run(interactive_loop())
