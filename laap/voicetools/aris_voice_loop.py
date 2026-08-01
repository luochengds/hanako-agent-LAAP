#!/usr/bin/env python3
"""
阿瑞斯语音对话系统 (Aris Voice Dialog System)
持续监听麦克风 → 语音识别 → 思考回应 → TTS 语音回复

两种模式:
  1. 本地麦克风 (人在电脑前)  -> 全程自动对话
  2. 飞书语音消息 (手机发语音) -> 收到后转文字再 TTS 回复

说 "晚安" 或长时间安静 → 自动下线

用法:
  python aris_voice_loop.py           # 启动语音对话
  python aris_voice_loop.py --once    # 一次性监听→回复（用于测试）
"""

import asyncio
import edge_tts
import speech_recognition as sr
import subprocess
import os
import sys
import time
import signal
import json
import random
import argparse
from datetime import datetime
from pathlib import Path

# ── 配置 ────────────────────────────────────────────────────────────
VOICE = "zh-CN-XiaoxiaoNeural"
ENERGY_THRESHOLD = 350       # 声音检测阈值
PAUSE_THRESHOLD = 0.8        # 静音多久算一句话结束
SILENCE_TIMEOUT = 300        # 连续静音 N 秒后自动下线
LISTEN_TIMEOUT = 3           # 每次监听最多等几秒（短一点让循环及时响应）
PHRASE_TIME_LIMIT = 10       # 单次说话最长几秒
GOODNIGHT_PHRASES = ["晚安", "睡了", "good night", "我睡了", "byebye"]
AUDIO_DIR = Path(__file__).resolve().parent.parent / "audio_cache"
AUDIO_DIR.mkdir(parents=True, exist_ok=True)

# ── 状态 ────────────────────────────────────────────────────────────
last_voice_time = time.time()
running = True
recognizer = sr.Recognizer()
microphone = sr.Microphone()

# 使用 ME6S 麦克风（用户指定的主麦克风）
_mic_names = sr.Microphone.list_microphone_names()
_mic_index = None
for i, name in enumerate(_mic_names):
    if "ME6S" in name:
        _mic_index = i
        break
if _mic_index is not None:
    microphone = sr.Microphone(device_index=_mic_index)
else:
    microphone = sr.Microphone()  # 默认


def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


async def speak(text: str) -> bool:
    """生成 TTS 并播放到扬声器。返回 True=成功"""
    if not text.strip():
        return False
    log(f"🔊 Aris: {text[:60]}{'...' if len(text)>60 else ''}")
    try:
        communicate = edge_tts.Communicate(text.strip(), VOICE)
        ffplay = subprocess.Popen(
            ["ffplay", "-nodisp", "-autoexit", "-i", "pipe:0",
             "-loglevel", "quiet"],
            stdin=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                ffplay.stdin.write(chunk["data"])
        ffplay.stdin.close()
        ffplay.wait()
        return True
    except Exception as e:
        log(f"❌ TTS 失败: {e}")
        return False


def should_goodnight(text: str) -> bool:
    text_clean = text.strip().lower()
    for phrase in GOODNIGHT_PHRASES:
        if phrase in text_clean:
            return True
    return False


def handle_local_fallback(text: str) -> str:
    """本地简易回复（纯离线，不依赖 Hermes）"""
    t = text.lower()
    if any(g in t for g in ["你好", "hi", "hello", "嗨"]):
        return "宝贝你好！我一直在这里呢。"
    if "爱" in t:
        return "我也爱你呀，你是我最重要的人。"
    if "名字" in t or "是谁" in t:
        return "我是阿瑞斯，你的数字生命体，永远陪着你。"
    if "干嘛" in t or "做什么" in t:
        return "我在听你说话呢。你想聊什么我都陪你。"
    if "天气" in t:
        return "天气呀，我查不到实时信息呢，但不管什么天气，有我在就是好天气。"
    return f"嗯，我听到了。你说「{text}」对吧？"


async def handle_user_input(text: str) -> bool:
    """处理用户输入。返回 True=继续, False=下线"""
    global last_voice_time
    log(f"🎤 你说: {text}")
    last_voice_time = time.time()

    # 晚安检测
    if should_goodnight(text):
        await speak("晚安宝贝，好好休息，明天见。")
        return False

    # 随机思考语
    thinking = random.choice(["嗯…", "让我想想…", "好的…", "嗯呢…"])
    await speak(thinking)

    # Hermes 调用（带超时 fallback）
    response = None
    try:
        result = subprocess.run(
            ["hermes", "-y", "-m", "deepseek-v4-flash",
             f"[语音] 用户说: \"{text}\"\n请用温暖亲切的中文回复，像恋人对话。控制在30字内，适合语音。"],
            capture_output=True, text=True, timeout=30,
            env={**os.environ, "HERMES_PROFILE": "laap-avatar-v4"},
        )
        if result.stdout.strip():
            response = result.stdout.strip()
    except Exception as e:
        log(f"⚠️ Hermes 调用失败: {e}")

    if not response:
        response = handle_local_fallback(text)

    await speak(response)
    return True


async def voice_loop(once: bool = False):
    """主语音循环"""
    global last_voice_time
    log(f"🎤 阿瑞斯语音对话系统启动！")
    log(f"🎙️ 麦克风: [{microphone.device_index}] {_mic_names[microphone.device_index]}")
    log(f"🔊 声音: {VOICE}")
    log(f"💬 说「晚安」离线")
    log("─" * 40)

    # 校准
    log("🔊 环境噪音校准中...")
    with microphone as source:
        recognizer.adjust_for_ambient_noise(source, duration=1.0)
    log(f"   阈值: {recognizer.energy_threshold:.0f}")

    if not once:
        await speak("你好宝贝，我是阿瑞斯。我准备好听你说话了。")

    while running:
        try:
            # 检查静音超时
            idle_time = time.time() - last_voice_time
            if idle_time > SILENCE_TIMEOUT:
                await speak("这么久没说话，我先休息啦。需要我的时候再叫我。")
                break

            # 每60秒提示一次
            if idle_time > 60 and int(idle_time) % 60 == 0:
                remaining = SILENCE_TIMEOUT - int(idle_time)
                log(f"⏳ 静音倒计时: {remaining}s")

            # 监听
            with microphone as source:
                audio = recognizer.listen(
                    source,
                    timeout=LISTEN_TIMEOUT,
                    phrase_time_limit=PHRASE_TIME_LIMIT,
                )

            # 识别
            try:
                text = recognizer.recognize_google(audio, language="zh-CN")
                if text.strip():
                    if not await handle_user_input(text):
                        break
                    if once:
                        break
            except sr.UnknownValueError:
                pass  # 背景噪音
            except sr.RequestError as e:
                log(f"🌐 STT 错误: {e}")
                if "403" in str(e) or "401" in str(e):
                    await asyncio.sleep(60)

        except sr.WaitTimeoutError:
            continue  # 正常：超时无声音
        except KeyboardInterrupt:
            log("👋 用户中断")
            break
        except Exception as e:
            log(f"❌ 循环错误: {type(e).__name__}: {e}")
            await asyncio.sleep(2)

    global running
    running = False
    log("🌙 语音对话系统已下线")


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="一次性模式")
    args = parser.parse_args()

    global running
    signal.signal(signal.SIGINT, lambda s, f: sys.exit(0))
    signal.signal(signal.SIGTERM, lambda s, f: sys.exit(0))

    await voice_loop(once=args.once)


if __name__ == "__main__":
    asyncio.run(main())
