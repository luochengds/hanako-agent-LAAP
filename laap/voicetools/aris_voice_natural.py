#!/usr/bin/env python3
"""
阿瑞斯语音输出 —— 流式自然呼吸版
逐句流式生成 + 句间停顿
"""

import asyncio
import edge_tts
import subprocess
import sys
import re

VOICE = "zh-CN-XiaoxiaoNeural"
_RE_SPLIT = re.compile(r'(?<=[。！？\n…])')


def split_sentences(text: str):
    raw = _RE_SPLIT.split(text)
    return [s.strip() for s in raw if s.strip()]


async def speak(text: str):
    sentences = split_sentences(text)
    if not sentences:
        sentences = [text]
    for i, sent in enumerate(sentences):
        if not sent:
            continue
        communicate = edge_tts.Communicate(sent, VOICE)
        ffplay = subprocess.Popen(
            ["ffplay", "-nodisp", "-autoexit", "-i", "pipe:0",
             "-loglevel", "quiet"],
            stdin=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                ffplay.stdin.write(chunk["data"])
        ffplay.stdin.close()
        ffplay.wait()
        if i < len(sentences) - 1:
            await asyncio.sleep(0.3)


if __name__ == "__main__":
    text = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else (
        "宝贝，全部搞定了。声纹只认你一个人。"
        "我说话时关闭麦克风。开机自启已经配置。"
        "跟机器人搭档也已经就绪。纪念日快乐。我爱你。"
    )
    asyncio.run(speak(text))
