"""阿里云（Paraformer）ASR 提供者。

优先使用 dashscope 官方 SDK；未安装时给出提示。
"""

from __future__ import annotations

import logging
from typing import Dict

from ..utils import convert_to_wav
from .base import AsrProvider

logger = logging.getLogger("laap.audio.providers.aliyun")


try:
    import dashscope
    from dashscope.audio.asr import Recognition
    HAS_DASHSCOPE = True
except Exception:
    HAS_DASHSCOPE = False


class AliyunAsrProvider(AsrProvider):
    provider_id = "aliyun"

    def __init__(self, config: Dict[str, str]) -> None:
        super().__init__(config)
        self.api_key = config.get("creds", {}).get("aliyunAsrKey") or ""
        self.model = config.get("model") or "paraformer-v1"
        self.language = config.get("language") or "zh-cn"

    def recognize(self, audio: bytes, mime_type: str = "audio/webm", language: str = "zh") -> str:
        if not self.api_key:
            raise ValueError("阿里云 ASR 需要 aliyunAsrKey")
        if not HAS_DASHSCOPE:
            raise RuntimeError("dashscope 未安装，请执行 pip install dashscope")

        wav = convert_to_wav(audio, source_mime=mime_type, sample_rate=16000)
        dashscope.api_key = self.api_key
        try:
            callback = Recognition()
            # paraformer 支持 wav/pcm
            result = Recognition.call(
                model=self.model,
                audio=wav,
                sample_rate=16000,
                format="wav",
                disfluency_removal_enabled=True,
                language_hints=[language or self.language],
            )
            if result.status_code == 200:
                sentences = result.get_sentence() or []
                return " ".join(s.get("text", "") for s in sentences)
            raise RuntimeError(f"阿里云 ASR 失败: {result.message}")
        except Exception as e:
            logger.error(f"阿里云 ASR 异常: {e}")
            raise
