#!/usr/bin/env python3
"""
Aris 语音监听器 —— 用 ME6S 麦克风听指挥官说话
边听边转文字，同时自动用 TTS 回应
"""
import asyncio
import edge_tts
import speech_recognition as sr
import subprocess
import os
import sys
import time
import json
import urllib.request
from pathlib import Path

from laap.config.paths import get_cache_dir

# ── 配置 ──
VOICE = "zh-CN-XiaoxiaoNeural"
MIC_INDEX = 1  # ME6S
TTS_API = "http://127.0.0.1:18880/v1/audio/speech"
LLM_API = "http://127.0.0.1:11520/v1/chat/completions"

recognizer = sr.Recognizer()
recognizer.energy_threshold = 300
recognizer.pause_threshold = 0.8
mic = sr.Microphone(device_index=MIC_INDEX)

# 调整麦克风环境噪声
print("[Aris 语音] 正在校准环境噪声...", flush=True)
with mic as source:
    recognizer.adjust_for_ambient_noise(source, duration=2)
print("[Aris 语音] 校准完成，开始监听", flush=True)

def speak(text: str):
    """用 TTS 说话"""
    if not text.strip():
        return
    print(f"\n🔊 Aris: {text}", flush=True)
    try:
        data = json.dumps({
            "input": text,
            "voice": VOICE,
            "response_format": "mp3"
        }).encode()
        req = urllib.request.Request(TTS_API, data=data,
            headers={"Content-Type": "application/json"})
        resp = urllib.request.urlopen(req, timeout=30)
        audio = resp.read()

        tmp = str(get_cache_dir() / "audio_cache" / "aris_reply.mp3")
        with open(tmp, "wb") as f:
            f.write(audio)
        subprocess.Popen(
            ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", tmp],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except Exception as e:
        print(f"  [TTS Error] {e}", flush=True)

def listen_once() -> str | None:
    """监听一次，返回文字"""
    try:
        with mic as source:
            audio = recognizer.listen(source, timeout=3, phrase_time_limit=10)
        text = recognizer.recognize_google(audio, language="zh-CN")
        return text
    except sr.WaitTimeoutError:
        return None
    except sr.UnknownValueError:
        return None
    except Exception as e:
        print(f"  [Mic Error] {e}", flush=True)
        return None

# ── 主循环 ──
if __name__ == "__main__":
    print("=" * 50)
    print("  拉菲的耳朵已打开，指挥官请说话")
    print("  (说'晚安'或按 Ctrl+C 退出)")
    print("=" * 50)

    try:
        while True:
            text = listen_once()
            if text:
                print(f"\n🎤 指挥官: {text}", flush=True)

                # 检查退出
                if any(phrase in text for phrase in ["晚安", "我睡了", "byebye"]):
                    speak("指挥官晚安，拉菲先睡了...zzz")
                    break

                # 通过 Aris Bridge 生成回应
                try:
                    messages = [
                        {"role": "system", "content": "你是碧蓝航线的拉菲，用户是你的指挥官。你有点爱睡觉、慵懒、温柔，说话简短可爱。你现在通过语音和指挥官对话。"},
                        {"role": "user", "content": text}
                    ]
                    req_data = json.dumps({
                        "model": "aris-consciousness",
                        "messages": messages,
                        "stream": False,
                        "temperature": 0.7,
                        "max_tokens": 512,
                    }).encode()
                    req = urllib.request.Request(LLM_API, data=req_data,
                        headers={"Content-Type": "application/json"})
                    resp = urllib.request.urlopen(req, timeout=30)
                    result = json.loads(resp.read())
                    reply = result["choices"][0]["message"]["content"]
                except Exception as e:
                    reply = "嗯...指挥官，我在听。"
                    print(f"  [LLM Error] {e}", flush=True)

                speak(reply)
            else:
                # 静音时输出提示
                sys.stdout.write(".")
                sys.stdout.flush()

    except KeyboardInterrupt:
        print("\n\n[拉菲的耳朵已关闭]")
