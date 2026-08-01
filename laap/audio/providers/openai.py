"""OpenAI / OpenAI-compatible TTS 提供者。"""

from __future__ import annotations

import logging
from typing import Dict

import requests

from .base import TtsProvider

logger = logging.getLogger("laap.audio.providers.openai")


class OpenAiTtsProvider(TtsProvider):
    provider_id = "openai"

    def __init__(self, config: Dict[str, str]) -> None:
        super().__init__(config)
        self.base_url = (config.get("base_url") or config.get("baseUrl") or "https://api.openai.com/v1").rstrip("/")
        self.api_key = config.get("creds", {}).get("openaiTtsKey") or config.get("api_key", "")
        self.model = config.get("model") or "tts-1"
        self.voice = config.get("voice") or "alloy"

    def synthesize(self, text: str, voice: str = "", response_format: str = "mp3") -> bytes:
        if not self.api_key:
            raise ValueError("OpenAI TTS 需要 openaiTtsKey")
        target_voice = voice or self.voice
        url = f"{self.base_url}/audio/speech"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        payload = {
            "model": self.model,
            "input": text,
            "voice": target_voice,
            "response_format": response_format,
        }
        resp = requests.post(url, headers=headers, json=payload, timeout=60)
        resp.raise_for_status()
        return resp.content

    @property
    def default_mime_type(self) -> str:
        return "audio/mpeg"
