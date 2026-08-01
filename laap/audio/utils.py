"""LAAP 音频通用工具。"""

from __future__ import annotations

import io
import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger("laap.audio.utils")


def convert_to_wav(audio: bytes, source_mime: str = "audio/webm", sample_rate: int = 16000) -> bytes:
    """将任意音频容器（webm/mp4/ogg）转换为单声道 16bit WAV。

    优先使用 pydub，未安装时回退到 ffmpeg 命令行。
    """
    if not audio:
        return b""

    ext_map = {
        "audio/webm": ".webm",
        "audio/mp4": ".m4a",
        "audio/mp3": ".mp3",
        "audio/wav": ".wav",
        "audio/ogg": ".ogg",
    }
    ext = ext_map.get(source_mime.lower().split(";")[0].strip(), ".bin")

    # 优先 pydub
    try:
        from pydub import AudioSegment
        seg = AudioSegment.from_file(io.BytesIO(audio), format=ext.lstrip("."))
        seg = seg.set_frame_rate(sample_rate).set_channels(1).set_sample_width(2)
        out = io.BytesIO()
        seg.export(out, format="wav")
        return out.getvalue()
    except Exception:
        pass

    # 回退 ffmpeg
    try:
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as src:
            src.write(audio)
            src_path = Path(src.name)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as dst:
            dst_path = Path(dst.name)
        subprocess.run(
            [
                "ffmpeg", "-y", "-i", str(src_path),
                "-ar", str(sample_rate), "-ac", "1", "-sample_fmt", "s16",
                str(dst_path),
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        wav = dst_path.read_bytes()
        src_path.unlink(missing_ok=True)
        dst_path.unlink(missing_ok=True)
        return wav
    except Exception as e:
        logger.warning(f"音频转码失败 ({source_mime}): {e}")
        return audio


def wav_bytes_to_pcm(wav: bytes) -> bytes:
    """去掉 WAV 头，返回 PCM 16bit 数据。"""
    if wav.startswith(b"RIFF") and b"WAVE" in wav[:12]:
        # 44 字节标准头
        return wav[44:] if len(wav) > 44 else wav
    return wav


def guess_mime_from_audio(audio: bytes) -> Optional[str]:
    """根据文件魔数猜测 MIME 类型。"""
    if audio.startswith(b"RIFF"):
        return "audio/wav"
    if audio[:3] == b"ID3" or audio.startswith(b"\xff\xfb") or audio.startswith(b"\xff\xf3"):
        return "audio/mpeg"
    if audio.startswith(b"OggS"):
        return "audio/ogg"
    if audio.startswith(b"fLaC"):
        return "audio/flac"
    if audio[:4] == b"ftyp":
        return "audio/mp4"
    return None
