"""
LAAP Voice Bridge - TTS + Audio streaming
Uses edge_tts for speech synthesis, handles WebSocket audio protocol
"""

import logging
logger = logging.getLogger(__name__)

import asyncio, base64, json, os, uuid, io, time, threading
from pathlib import Path

# Try edge_tts
try:
    import edge_tts
    HAS_EDGE_TTS = True
except ImportError:
    HAS_EDGE_TTS = False

TEMP_DIR = Path(__file__).parent.parent / "tmp" / "voice"
TEMP_DIR.mkdir(parents=True, exist_ok=True)

# ── TTS ──
def tts_sync(text: str, voice: str = "zh-CN-XiaoxiaoNeural") -> bytes:
    """Synchronous wrapper for edge_tts. Returns MP3 bytes."""
    if not HAS_EDGE_TTS:
        raise RuntimeError("edge_tts not installed")
    result = []
    error = [None]
    def run():
        async def _inner():
            try:
                communicate = edge_tts.Communicate(text, voice=voice)
                audio = b""
                async for chunk in communicate.stream():
                    if chunk["type"] == "audio":
                        audio += chunk["data"]
                result.append(audio)
            except Exception as e:
                error[0] = e
        asyncio.run(_inner())
    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(timeout=30)
    if error[0]:
        raise error[0]
    return result[0] if result else b""

def tts_to_base64(text: str, voice: str = "zh-CN-XiaoxiaoNeural") -> str:
    """Get TTS audio as base64 string."""
    audio = tts_sync(text, voice)
    return base64.b64encode(audio).decode('ascii')

# ── Audio Processing ──
def pcm_to_wav_bytes(pcm_data: bytes, sample_rate: int = 16000) -> bytes:
    """Convert raw PCM 16-bit to WAV format."""
    import struct
    num_channels = 1
    bits_per_sample = 16
    byte_rate = sample_rate * num_channels * bits_per_sample // 8
    block_align = num_channels * bits_per_sample // 8
    data_size = len(pcm_data)
    header_size = 44
    total_size = header_size + data_size
    
    header = b"RIFF"
    header += struct.pack('<I', total_size - 8)
    header += b"WAVE"
    header += b"fmt "
    header += struct.pack('<IHHIIHH', 16, 1, num_channels, sample_rate, byte_rate, block_align, bits_per_sample)
    header += b"data"
    header += struct.pack('<I', data_size)
    return header + pcm_data

# ── ASR via Web Speech API (handled in browser) ──
# Browser sends text directly, no server-side ASR needed

if __name__ == "__main__":
    import sys
    text = " ".join(sys.argv[1:]) or "你好，我是LAAP数字生命体，很高兴认识你。"
    logger.info(f"TTS: '{text}'...")
    audio = tts_sync(text)
    logger.info(f"  Generated {len(audio)} bytes of audio")
    b64 = base64.b64encode(audio).decode('ascii')
    logger.info(f"  Base64: {len(b64)} chars")