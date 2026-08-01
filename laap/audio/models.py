"""LAAP 音频服务数据模型。"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass
class AsrConfig:
    provider: str = "aliyun"
    model: str = ""
    base_url: str = ""
    creds: Dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: Dict[str, Any]) -> "AsrConfig":
        cfg = payload.get("asr") or {}
        return cls(
            provider=cfg.get("provider", "aliyun"),
            model=cfg.get("model", ""),
            base_url=cfg.get("baseUrl", ""),
            creds=cfg.get("creds") or cfg.get("credentials") or {},
        )


@dataclass
class TtsConfig:
    provider: str = "microsoft"
    model: str = "zh-CN-XiaoxiaoNeural"
    base_url: str = ""
    streaming: bool = False
    creds: Dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: Dict[str, Any]) -> "TtsConfig":
        cfg = payload.get("tts") or {}
        return cls(
            provider=cfg.get("provider", "microsoft"),
            model=cfg.get("model", "zh-CN-XiaoxiaoNeural"),
            base_url=cfg.get("baseUrl", ""),
            streaming=cfg.get("streaming", False),
            creds=cfg.get("creds") or cfg.get("credentials") or {},
        )


@dataclass
class VoiceInputPayload:
    audio: bytes
    mime_type: str
    asr: AsrConfig
    tts: TtsConfig
    llm: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: Dict[str, Any]) -> "VoiceInputPayload":
        audio_b64 = payload.get("audio", "")
        if isinstance(audio_b64, bytes):
            audio = audio_b64
        else:
            audio = base64.b64decode(audio_b64.encode("ascii")) if audio_b64 else b""

        return cls(
            audio=audio,
            mime_type=payload.get("mimeType") or payload.get("mime_type") or "audio/webm",
            asr=AsrConfig.from_payload(payload),
            tts=TtsConfig.from_payload(payload),
            llm=payload.get("llm") or {},
        )
