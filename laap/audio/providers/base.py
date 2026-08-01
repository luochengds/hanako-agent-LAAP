"""ASR/TTS 提供者抽象基类。"""

from __future__ import annotations

import abc
import logging
from typing import Dict

logger = logging.getLogger("laap.audio.providers")


class BaseAudioProvider(abc.ABC):
    """所有音频提供者的公共基类。"""

    provider_id: str = ""

    def __init__(self, config: Dict[str, str]) -> None:
        self.config = config
        self._creds = config.get("creds") or {}


class AsrProvider(BaseAudioProvider, abc.ABC):
    """自动语音识别提供者接口。"""

    @abc.abstractmethod
    def recognize(self, audio: bytes, mime_type: str = "audio/webm", language: str = "zh") -> str:
        """将音频字节流识别为文本。

        Args:
            audio: 原始音频字节。
            mime_type: 客户端上传的 MIME 类型，用于决定是否需要转码。
            language: 目标语言代码。

        Returns:
            识别后的文本；识别失败返回空字符串。
        """
        ...


class TtsProvider(BaseAudioProvider, abc.ABC):
    """文本转语音提供者接口。"""

    @abc.abstractmethod
    def synthesize(self, text: str, voice: str = "", response_format: str = "mp3") -> bytes:
        """将文本合成为音频字节。

        Args:
            text: 待合成文本。
            voice: 音色/发音人 ID。
            response_format: 期望音频格式（mp3/wav/opus/pcm）。

        Returns:
            音频字节流。
        """
        ...

    @property
    def default_mime_type(self) -> str:
        return "audio/mpeg"
