"""本地 ASR 提供者。

优先使用 SpeechRecognition + Google Web Speech（在线，无需密钥）做演示。
未安装时回退到简单的能量占位，返回空文本并提示。
"""

from __future__ import annotations

import logging
from typing import Dict

from ..utils import convert_to_wav
from .base import AsrProvider

logger = logging.getLogger("laap.audio.providers.local")


try:
    import speech_recognition as sr
    HAS_SPEECH_RECOGNITION = True
except Exception:
    HAS_SPEECH_RECOGNITION = False


class LocalAsrProvider(AsrProvider):
    provider_id = "local"

    def __init__(self, config: Dict[str, str]) -> None:
        super().__init__(config)
        self.language = config.get("language") or "zh-CN"

    def recognize(self, audio: bytes, mime_type: str = "audio/webm", language: str = "zh") -> str:
        if not HAS_SPEECH_RECOGNITION:
            logger.warning("本地 ASR 需要 pip install SpeechRecognition，当前未安装")
            return ""
        wav = convert_to_wav(audio, source_mime=mime_type, sample_rate=16000)
        recognizer = sr.Recognizer()
        try:
            with sr.AudioFile(__import__("io").BytesIO(wav)) as source:
                sample = recognizer.record(source)
            text = recognizer.recognize_google(sample, language=language or self.language)
            return text
        except sr.UnknownValueError:
            logger.warning("本地 ASR 未能识别音频内容")
            return ""
        except sr.RequestError as e:
            logger.error(f"本地 ASR 请求失败: {e}")
            return ""
