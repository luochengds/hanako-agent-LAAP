"""Microsoft Azure / Edge TTS 提供者。

后端默认使用 edge-tts（免费离线），无需订阅密钥。
若需要更高品质，可替换为 Azure Speech SDK。
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Dict

from .base import TtsProvider

logger = logging.getLogger("laap.audio.providers.microsoft")

try:
    import edge_tts
    HAS_EDGE_TTS = True
except Exception:
    HAS_EDGE_TTS = False


class MicrosoftTtsProvider(TtsProvider):
    provider_id = "microsoft"

    def __init__(self, config: Dict[str, str]) -> None:
        super().__init__(config)
        self.voice = config.get("model") or config.get("voice") or "zh-CN-XiaoxiaoNeural"

    def synthesize(self, text: str, voice: str = "", response_format: str = "mp3") -> bytes:
        if not HAS_EDGE_TTS:
            raise RuntimeError("edge_tts 未安装，请执行 pip install edge-tts")
        target_voice = voice or self.voice

        result: list = []
        error: list = [None]

        def run():
            async def _inner():
                try:
                    communicate = edge_tts.Communicate(text, voice=target_voice)
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
        t.join(timeout=60)
        if error[0]:
            raise error[0]
        if not result:
            raise RuntimeError("Microsoft TTS 未返回音频")
        return result[0]

    @property
    def default_mime_type(self) -> str:
        return "audio/mpeg"
