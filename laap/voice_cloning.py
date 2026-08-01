"""
LAAP Voice Cloning Bridge — GPT-SoVITS Integration
Connects to GPT-SoVITS API for voice cloning and streaming TTS
"""

import logging
logger = logging.getLogger(__name__)

import os, json, base64, time, threading, requests
from pathlib import Path

ENGINE_DIR = Path(__file__).parent.parent / "character_engine"
VOICES_DIR = ENGINE_DIR / "voices"

# GPT-SoVITS default endpoint
SOVITS_URL = "http://127.0.0.1:9880"

def check_engine() -> dict:
    """Check if GPT-SoVITS engine is running"""
    try:
        r = requests.get(f"{SOVITS_URL}/status", timeout=3)
        return {"online": True, "info": r.json()}
    except:
        return {"online": False, "info": "Engine not running"}

def clone_voice(character_name: str, audio_dir: str = None) -> dict:
    """
    Clone a voice from audio samples using GPT-SoVITS
    - audio_dir: directory containing WAV samples + a transcript file
    """
    voice_dir = VOICES_DIR / character_name
    voice_dir.mkdir(parents=True, exist_ok=True)
    
    if audio_dir:
        # Copy samples to voice dir
        import shutil
        audio_path = Path(audio_dir)
        if audio_path.exists():
            for f in audio_path.glob("*"):
                if f.suffix.lower() in ('.wav','.mp3','.m4a','.ogg'):
                    shutil.copy2(f, voice_dir / f.name)
    
    # Find the best sample (first .wav or longest audio)
    samples = list(voice_dir.glob("*.wav")) + list(voice_dir.glob("*.mp3"))
    if not samples:
        return {"status": "error", "message": "No audio samples found"}
    
    ref_audio = str(samples[0])
    ref_text = ""
    
    # Check for transcript
    transcript = voice_dir / "transcript.txt"
    if transcript.exists():
        with open(transcript, 'r', encoding='utf-8') as f:
            ref_text = f.read().strip()
    
    # Save config for later use
    config = {
        "character": character_name,
        "ref_audio": ref_audio,
        "ref_text": ref_text,
        "models": [],
        "status": "ready_for_cloning"
    }
    
    # Try to call GPT-SoVITS API
    try:
        # Step 1: Set reference voice
        r = requests.post(f"{SOVITS_URL}/change_voice", json={
            "ref_audio_path": ref_audio,
            "prompt_text": ref_text or "default",
            "prompt_language": "zh"
        }, timeout=10)
        
        if r.status_code == 200:
            config["status"] = "voice_set"
            config["response"] = r.json()
        else:
            config["status"] = f"api_error: {r.text[:100]}"
    except Exception as e:
        config["status"] = f"connection_error: {e}"
    
    with open(voice_dir / "voice_config.json", 'w', encoding='utf-8') as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
    
    return config

def tts_with_cloned_voice(text: str, character_name: str = None) -> bytes:
    """
    Generate TTS audio using cloned voice
    Falls back to EdgeTTS if GPT-SoVITS unavailable
    """
    if character_name:
        config_path = VOICES_DIR / character_name / "voice_config.json"
        if config_path.exists():
            with open(config_path, 'r') as f:
                config = json.load(f)
            if config.get("status") in ("voice_set", "ready"):
                try:
                    r = requests.post(f"{SOVITS_URL}/tts", json={
                        "text": text,
                        "text_language": "zh",
                        "stream_chunk": False
                    }, timeout=30)
                    if r.status_code == 200:
                        return r.content
                except Exception as e:
                    logger.debug(f"操作失败: {e}")
    from laap_web import tts_sync
    return tts_sync(text)

def tts_stream(text: str, on_chunk, character_name: str = None):
    """Streaming TTS via WebSocket"""
    import websockets.sync.client as ws_client
    
    engine_online = check_engine()["online"]
    
    if engine_online and character_name:
        try:
            with ws_client.connect(f"ws://127.0.0.1:9880/tts") as ws:
                ws.send(json.dumps({
                    "text": text,
                    "text_language": "zh",
                    "stream_chunk": True
                }))
                for msg in ws:
                    data = json.loads(msg)
                    if data["type"] == "audio":
                        on_chunk(base64.b64decode(data["data"]))
                    elif data["type"] == "stop":
                        break
            return
        except Exception as e:
            logger.debug(f"操作失败: {e}")
    audio = tts_sync(text)
    if audio:
        on_chunk(audio)

if __name__ == "__main__":
    status = check_engine()
    logger.info(f"GPT-SoVITS: {'ONLINE' if status['online'] else 'OFFLINE'}")