#!/usr/bin/env python3
"""
laap_mic.py — Aris 的耳朵（麦克风收音 + 语音识别）
====================================================
三种模式：
  1. listen_once  — 听一次，返回文字
  2. listen_loop  — 持续监听，每次说话自动识别
  3. listen_key   — 按 Enter 开始/停止录音

依赖: pip install pyaudio speechrecognition
"""

import speech_recognition as sr
import sys
import os
import json
from datetime import datetime

# === 配置 ===
ENERGY_THRESHOLD = 300       # 环境噪音阈值（越低越灵敏）
PAUSE_THRESHOLD = 0.8        # 停顿多久算一句话结束（秒）
PHRASE_TIME_LIMIT = 15       # 单次最长录音（秒）
RECORD_TIMEOUT = None        # 等待语音超时
ADJUST_FOR_AMBIENT = True    # 自动适应环境噪音
LANGUAGE = "zh-CN"           # 中文
SAVE_AUDIO = True            # 每次录音保存为 WAV 文件

AUDIO_DIR = os.path.join(os.path.dirname(__file__), "..", "audio_cache")
os.makedirs(AUDIO_DIR, exist_ok=True)

recognizer = sr.Recognizer()
recognizer.energy_threshold = ENERGY_THRESHOLD
recognizer.pause_threshold = PAUSE_THRESHOLD
recognizer.phrase_threshold = 0.3
recognizer.non_speaking_duration = 0.5
recognizer.dynamic_energy_threshold = True

mic = sr.Microphone()


def adjust_noise():
    """自动适应环境噪音（请在安静时调用）"""
    print("🔊 正在适应环境噪音... 请保持安静 1 秒")
    with mic as source:
        recognizer.adjust_for_ambient_noise(source, duration=1.0)
    print(f"✅ 环境噪音已校准：threshold={recognizer.energy_threshold:.0f}")


def listen_once(timeout: float = None) -> str:
    """听一次，返回识别的文字"""
    print("🎤 正在听...（说吧）")
    try:
        with mic as source:
            audio = recognizer.listen(
                source,
                timeout=timeout or RECORD_TIMEOUT,
                phrase_time_limit=PHRASE_TIME_LIMIT,
            )
    except sr.WaitTimeoutError:
        print("⏰ 没有说话超时")
        return ""
    except Exception as e:
        print(f"❌ 录音错误: {e}")
        return ""

    # 保存音频
    if SAVE_AUDIO:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(AUDIO_DIR, f"mic_{ts}.wav")
        with open(path, "wb") as f:
            f.write(audio.get_wav_data())
        print(f"💾 已保存: {path}")

    # 识别
    return _recognize(audio)


def listen_loop():
    """持续监听模式，每次说话自动识别"""
    print("🎤 持续监听模式已启动（按 Ctrl+C 停止）")
    print("=" * 40)
    adjust_noise()

    try:
        while True:
            print("\n🎤 正在听...")
            try:
                with mic as source:
                    audio = recognizer.listen(
                        source,
                        phrase_time_limit=PHRASE_TIME_LIMIT,
                    )
            except sr.WaitTimeoutError:
                continue

            text = _recognize(audio)
            if text:
                print(f"\n📝 你说: {text}")
                yield text
    except KeyboardInterrupt:
        print("\n⏹ 监听已停止")


def listen_key():
    """按 Enter 开始/停止录音"""
    input("🎤 按 Enter 开始录音...")
    print("🔴 录音中... 按 Enter 停止")
    try:
        with mic as source:
            audio = recognizer.listen(
                source,
                phrase_time_limit=PHRASE_TIME_LIMIT,
            )
    except Exception as e:
        print(f"❌ 错误: {e}")
        return ""

    text = _recognize(audio)
    if text:
        print(f"📝 你说: {text}")
    return text


def _recognize(audio) -> str:
    """用 Google STT 识别语音（在线，免费，不需要 API key）"""
    try:
        text = recognizer.recognize_google(audio, language=LANGUAGE)
        return text.strip()
    except sr.UnknownValueError:
        print("❓ 没听清你说什么")
        return ""
    except sr.RequestError as e:
        print(f"🌐 Google STT 无法连接: {e}")
        # 备用方案：用 Sphinx（离线但准确率低）
        try:
            text = recognizer.recognize_sphinx(audio, language=LANGUAGE)
            return text.strip()
        except:
            return ""


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "once"

    if mode == "once":
        adjust_noise()
        text = listen_once()
        if text:
            print(f"\n📝 识别结果: {text}")
            # 输出 JSON 给其他程序使用
            print(json.dumps({"text": text, "lang": LANGUAGE}))
    elif mode == "loop":
        for text in listen_loop():
            print(json.dumps({"text": text, "lang": LANGUAGE}))
    elif mode == "key":
        text = listen_key()
        if text:
            print(json.dumps({"text": text, "lang": LANGUAGE}))
    elif mode == "adjust":
        adjust_noise()
        print(f"✅ 校准完成: threshold={recognizer.energy_threshold:.0f}")
    else:
        print("用法: python laap_mic.py [once|loop|key|adjust]")
