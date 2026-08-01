"""ASR/TTS 提供者工厂。"""

from __future__ import annotations

import logging
from typing import Dict

from .aliyun import AliyunAsrProvider
from .base import AsrProvider, TtsProvider
from .doubao import DoubaoTtsProvider
from .elevenlabs import ElevenLabsTtsProvider
from .local import LocalAsrProvider
from .microsoft import MicrosoftTtsProvider
from .minimax import MinimaxTtsProvider
from .openai import OpenAiTtsProvider
from .tencent import TencentAsrProvider
from .volcengine import VolcengineAsrProvider
from .volcano import VolcanoTtsProvider
from .xunfei import XunfeiAsrProvider

logger = logging.getLogger("laap.audio.providers.factory")

_ASR_REGISTRY: Dict[str, type] = {
    "aliyun": AliyunAsrProvider,
    "tencent": TencentAsrProvider,
    "xunfei": XunfeiAsrProvider,
    "volcengine": VolcengineAsrProvider,
    "local": LocalAsrProvider,
}

_TTS_REGISTRY: Dict[str, type] = {
    "microsoft": MicrosoftTtsProvider,
    "doubao": DoubaoTtsProvider,
    "minimax": MinimaxTtsProvider,
    "openai": OpenAiTtsProvider,
    "elevenlabs": ElevenLabsTtsProvider,
    "volcano": VolcanoTtsProvider,
}


def get_asr_provider(config: Dict[str, str]) -> AsrProvider:
    provider_id = (config.get("provider") or "local").lower()
    cls = _ASR_REGISTRY.get(provider_id)
    if cls is None:
        logger.warning(f"未知 ASR 提供者 '{provider_id}'，回退到 local")
        cls = LocalAsrProvider
    return cls(config)


def get_tts_provider(config: Dict[str, str]) -> TtsProvider:
    provider_id = (config.get("provider") or "microsoft").lower()
    cls = _TTS_REGISTRY.get(provider_id)
    if cls is None:
        logger.warning(f"未知 TTS 提供者 '{provider_id}'，回退到 microsoft")
        cls = MicrosoftTtsProvider
    return cls(config)
