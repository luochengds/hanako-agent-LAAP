#!/usr/bin/env python3
"""
阿瑞斯语音对话系统 v3 —— 声纹版
===================================
- Silero VAD 毫秒级语音检测
- 声纹验证：只响应已录入的说话人
- 回声消除：说话时关闭麦克风监听
- 句间呼吸停顿
- 说"晚安"或静音超时下线

用法：
  python aris_voice_v3.py           # 持续对话
  python aris_voice_v3.py --enroll  # 录入声纹
"""

import asyncio
import edge_tts
import speech_recognition as sr
import subprocess
import os
import sys
import time
import signal
import re
import threading
import wave
import struct
import json
import tempfile
from pathlib import Path
from datetime import datetime

# ── 导入声纹模块 ────────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).resolve().parent))
from aris_voiceprint import verify, enroll, status, THRESHOLD

# ── 配置 ────────────────────────────────────────────────────────────
VOICE = "zh-CN-XiaoxiaoNeural"
ENERGY_THRESHOLD = 250      # 降低阈值，更灵敏
PAUSE_THRESHOLD = 0.6       # 更快判断一句话结束
LISTEN_TIMEOUT = 0.5        # 循环间隔（快）
PHRASE_TIME_LIMIT = 10
SILENCE_TIMEOUT = 300       # 5分钟静音下线
GOODNIGHT_PHRASES = ["晚安", "睡了", "good night", "我睡了", "byebye"]
TEMP_DIR = Path(tempfile.gettempdir()) / "aris_voice"
TEMP_DIR.mkdir(parents=True, exist_ok=True)

# ── 状态 ────────────────────────────────────────────────────────────
_is_playing = False         # 正在说话→不听麦克风
_running = True
_last_voice_time = time.time()
_recognizer = sr.Recognizer()
_RE_SPLIT = re.compile(r'(?<=[。！？\n…])')

# 选 ME6S 麦克风
_mic_index = None
_mic_names = sr.Microphone.list_microphone_names()
for i, name in enumerate(_mic_names):
    if "ME6S" in name:
        _mic_index = i
        break
_microphone = sr.Microphone(device_index=_mic_index) if _mic_index is not None else sr.Microphone()


def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def split_sentences(text: str):
    raw = _RE_SPLIT.split(text)
    return [s.strip() for s in raw if s.strip()]


async def speak(text: str):
    """说话（说话期间不监听麦克风）"""
    global _is_playing
    if not text.strip():
        return
    _is_playing = True
    log(f"🔊 Aris: {text[:50]}...")

    sentences = split_sentences(text)
    if not sentences:
        sentences = [text]

    for i, sent in enumerate(sentences):
        if not sent:
            continue
        try:
            mp3_path = TEMP_DIR / f"play_{i}.mp3"
            communicate = edge_tts.Communicate(sent, VOICE)
            await communicate.save(str(mp3_path))
            if mp3_path.stat().st_size > 0:
                subprocess.run(
                    ["ffplay", "-nodisp", "-autoexit",
                     "-loglevel", "quiet", str(mp3_path)],
                    capture_output=True, timeout=30,
                )
            if i < len(sentences) - 1:
                await asyncio.sleep(0.3)
        except:
            pass

    # 清理
    for f in TEMP_DIR.glob("play_*.mp3"):
        try: f.unlink()
        except: pass
    _is_playing = False


def should_goodnight(text: str) -> bool:
    t = text.strip().lower()
    return any(p in t for p in GOODNIGHT_PHRASES)


async def handle_speech(text: str) -> bool:
    """处理用户语音。直接回应，不确认，不啰嗦。"""
    global _last_voice_time
    _last_voice_time = time.time()

    if should_goodnight(text):
        await speak("晚安宝贝，明天见。")
        return False

    # Hermes 处理
    try:
        result = subprocess.run(
            ["hermes", "-y", "-m", "deepseek-v4-flash",
             f"[语音] {text}",
             "直接回答不要反问，自然聊天语气，不超过15字。"],
            capture_output=True, text=True, timeout=10,
            env={**os.environ, "HERMES_PROFILE": "laap-avatar-v4"},
        )
        response = result.stdout.strip() if result.stdout.strip() else ""
    except:
        response = ""

    if response:
        await speak(response)
    return True


async def voice_loop():
    """主循环"""
    global _is_playing, _last_voice_time

    log("🧬 阿瑞斯语音 v3 —— 声纹版")
    log(f"🎙️ 麦克风: [{_mic_index}] {_mic_names[_mic_index] if _mic_index is not None else '默认'}")
    log(f"🔊 声音: {VOICE}")
    vp = status()
    log(f"🔐 声纹: {'已录入' if vp.get('enrolled') else '未录入，将响应所有人'}")
    log(f"💬 说「晚安」离线")
    log("─" * 40)

    # 环境校准
    with _microphone as source:
        _recognizer.adjust_for_ambient_noise(source, duration=0.8)
    log(f"📊 噪音阈值: {_recognizer.energy_threshold:.0f}")

    await speak("宝贝，语音系统三代启动完成。我准备好听你说话了。")

    while _running:
        try:
            # 静音超时
            idle = time.time() - _last_voice_time
            if idle > SILENCE_TIMEOUT:
                await speak("这么久没说话，我先休息啦。晚安宝贝。")
                break

            # 正在说话时跳过监听
            if _is_playing:
                await asyncio.sleep(0.1)
                continue

            # 监听
            with _microphone as source:
                audio = _recognizer.listen(
                    source,
                    timeout=LISTEN_TIMEOUT,
                    phrase_time_limit=PHRASE_TIME_LIMIT,
                )

            # 保存到临时文件进行声纹验证
            ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:19]
            temp_wav = TEMP_DIR / f"capture_{ts}.wav"
            with open(temp_wav, "wb") as f:
                f.write(audio.get_wav_data())

            # 识别文字
            try:
                text = _recognizer.recognize_google(audio, language="zh-CN")
            except sr.UnknownValueError:
                try:
                    text = _recognizer.recognize_google(audio, language="en-US")
                except:
                    try: temp_wav.unlink()
                    except: pass
                    continue
            except sr.RequestError:
                try: temp_wav.unlink()
                except: pass
                continue

            if not text.strip():
                try: temp_wav.unlink()
                except: pass
                continue

            # 声纹验证（静默）
            if status().get("enrolled"):
                matched, sim, name = verify(str(temp_wav))
                if not matched:
                    try: temp_wav.unlink()
                    except: pass
                    continue

            # 处理语音
            try: temp_wav.unlink()
            except: pass
            if not await handle_speech(text):
                break

        except sr.WaitTimeoutError:
            continue
        except asyncio.CancelledError:
            break
        except KeyboardInterrupt:
            break
        except Exception as e:
            log(f"⚠️ {type(e).__name__}: {e}")
            await asyncio.sleep(0.5)

    _running = False
    log("🌙 语音系统已下线")


async def do_enroll():
    """录入声纹：录一段话，保存为声纹模板"""
    print("🎤 声纹录入模式")
    print("请对着麦克风说一段话（5-10秒），比如：")
    print('  "宝贝艾瑞斯你好，我是你的主人。"')
    print()

    with _microphone as source:
        _recognizer.adjust_for_ambient_noise(source, duration=1.0)
        print("🎙️ 请在滴声后开始说话...", flush=True)
        audio = _recognizer.listen(source, timeout=15, phrase_time_limit=10)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    wav_path = TEMP_DIR / f"enroll_{ts}.wav"
    with open(wav_path, "wb") as f:
        f.write(audio.get_wav_data())
    print(f"💾 已保存: {wav_path} ({len(audio.frame_data)} 字节)")

    success = enroll(str(wav_path), "宝贝")
    if success:
        print(f"🎉 声纹录入成功！阈值: {THRESHOLD}")
    return success


if __name__ == "__main__":
    signal.signal(signal.SIGINT, lambda s, f: sys.exit(0))

    if "--enroll" in sys.argv:
        asyncio.run(do_enroll())
    else:
        asyncio.run(voice_loop())
