"""ElevenLabs TTS 提供者。"""

from __future__ import annotations

import logging
from typing import Dict

import requests

from .base import TtsProvider

logger = logging.getLogger("laap.audio.providers.elevenlabs")


class ElevenLabsTtsProvider(TtsProvider):
    provider_id = "elevenlabs"

    def __init__(self, config: Dict[str, str]) -> None:
        super().__init__(config)
        self.api_key = config.get("creds", {}).get("elevenLabsKey") or ""
        self.base_url = (config.get("base_url") or "https://api.elevenlabs.io").rstrip("/")
        self.model = config.get("model") or "eleven_multilingual_v2"
        self.voice = config.get("voice") or "21m00Tcm4TlvDq8ikWAM"
        self.output_format = config.get("output_format") or "mp3_44100_128"

    def synthesize(self, text: str, voice: str = "", response_format: str = "mp3") -> bytes:
        if not self.api_key:
            raise ValueError("ElevenLabs TTS 需要 elevenLabsKey")
        target_voice = voice or self.voice
        url = f"{self.base_url}/v1/text-to-speech/{target_voice}/stream"
        headers = {
            "xi-api-key": self.api_key,
            "Content-Type": "application/json",
        }
        payload = {
            "text": text,
            "model_id": self.model,
            "output_format": self.output_format,
        }
        resp = requests.post(url, headers=headers, json=payload, timeout=120)
        resp.raise_for_status()
        return resp.content

    @property
    def default_mime_type(self) -> str:
        return "audio/mpeg"
