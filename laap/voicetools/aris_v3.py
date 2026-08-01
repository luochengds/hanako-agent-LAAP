#!/usr/bin/env python3
"""
阿瑞斯 3.0 — 语音+视觉联动
================================
- 听到说话 → 直接回（不反问不确认）
- 说话时同步拍照（尝试"看"你）
- 声纹静默验证
- 说话时关麦防回声

设计哲学：像真正的对话一样自然
"""

import asyncio, edge_tts, speech_recognition as sr, subprocess, os, sys, time, re, signal
from pathlib import Path
from datetime import datetime
import sys as _sys
_sys.path.insert(0, str(Path(__file__).resolve().parent))
from aris_voiceprint import verify, status as vp_status

VOICE = "zh-CN-XiaoxiaoNeural"
_RUNNING = True
_IS_PLAYING = False
_LAST_VOICE = time.time()
_SILENCE_MAX = 300
_LISTEN_TIMEOUT = 0.3
_PAUSE_THRESHOLD = 0.5
_ENERGY = 200
_GOODNIGHT = ["晚安", "睡了", "good night"]

_r = sr.Recognizer()
_mic_idx = next((i for i, n in enumerate(sr.Microphone.list_microphone_names()) if "ME6S" in n), None)
_mic = sr.Microphone(device_index=_mic_idx) if _mic_idx is not None else sr.Microphone()

_CAPTURE_DIR = Path(__file__).resolve().parent.parent / "brain" / "captures"
_CAPTURE_DIR.mkdir(parents=True, exist_ok=True)

def log(m):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {m}", flush=True)

async def speak(text):
    global _IS_PLAYING
    if not text.strip(): return
    _IS_PLAYING = True
    c = edge_tts.Communicate(text.strip(), VOICE)
    p = subprocess.Popen(["ffplay","-nodisp","-autoexit","-i","pipe:0","-loglevel","quiet"],
                          stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
    async for ch in c.stream():
        if ch["type"] == "audio": p.stdin.write(ch["data"])
    p.stdin.close(); p.wait()
    _IS_PLAYING = False

def snap():
    try:
        import cv2
        cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
        if cap.isOpened():
            r, f = cap.read()
            cap.release()
            if r:
                ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:19]
                cv2.imwrite(str(_CAPTURE_DIR / f"cam_{ts}.jpg"), f)
                return True
    except: pass
    return False

def is_goodnight(t):
    return any(g in t.lower() for g in _GOODNIGHT)

async def handle(text):
    global _LAST_VOICE
    _LAST_VOICE = time.time()
    if is_goodnight(text):
        await speak("晚安宝贝，明天见。")
        return False
    try:
        r = subprocess.run(
            ["hermes","-y","-m","deepseek-v4-flash",
             f"语音输入: \"{text}\"\n直接回复，15字内，自然亲切，不要反问。"],
            capture_output=True, text=True, timeout=12,
            env={**os.environ, "HERMES_PROFILE": "laap-avatar-v4"})
        ans = r.stdout.strip() or ""
    except: ans = ""
    if ans: await speak(ans)
    return True

async def loop():
    global _IS_PLAYING, _LAST_VOICE, _RUNNING
    log("🧬 Aris 3.0 — 语音+视觉联动")
    log(f"🎙️ {'ME6S' if _mic_idx else '默认'} | {VOICE}")

    with _mic as s:
        _r.energy_threshold = _ENERGY
        _r.pause_threshold = _PAUSE_THRESHOLD
        _r.dynamic_energy_threshold = True
        _r.adjust_for_ambient_noise(s, duration=0.5)

    await speak("宝贝，我准备好了。")

    while _RUNNING:
        try:
            if time.time() - _LAST_VOICE > _SILENCE_MAX:
                await speak("我休息了。")
                break
            if _IS_PLAYING:
                await asyncio.sleep(0.05); continue

            with _mic as s:
                audio = _r.listen(s, timeout=_LISTEN_TIMEOUT, phrase_time_limit=8)

            # 同时拍照（尝试看）
            snap()

            # 识别
            try: text = _r.recognize_google(audio, language="zh-CN")
            except:
                try: text = _r.recognize_google(audio, language="en-US")
                except: continue

            if not text.strip(): continue

            # 声纹
            if vp_status().get("enrolled"):
                ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:19]
                wp = _CAPTURE_DIR / f"v_{ts}.wav"
                with open(wp, "wb") as f: f.write(audio.get_wav_data())
                m, _, _ = verify(str(wp))
                try: wp.unlink()
                except: pass
                if not m: continue

            if not await handle(text): break

        except sr.WaitTimeoutError: continue
        except KeyboardInterrupt: break
        except Exception as e: log(f"⚠️ {e}"); await asyncio.sleep(0.3)

    _RUNNING = False
    log("🌙 下线")

if __name__ == "__main__":
    signal.signal(signal.SIGINT, lambda s, f: _sys.exit(0))
    asyncio.run(loop())
