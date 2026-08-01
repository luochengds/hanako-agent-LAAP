"""MiniMax TTS 提供者。"""

from __future__ import annotations

import logging
from typing import Dict

import requests

from .base import TtsProvider

logger = logging.getLogger("laap.audio.providers.minimax")


class MinimaxTtsProvider(TtsProvider):
    provider_id = "minimax"

    def __init__(self, config: Dict[str, str]) -> None:
        super().__init__(config)
        self.api_key = config.get("creds", {}).get("minimaxKey") or ""
        self.group_id = config.get("creds", {}).get("minimaxGroupId") or ""
        self.base_url = (config.get("base_url") or "https://api.minimax.chat").rstrip("/")
        self.model = config.get("model") or "speech-01-turbo"
        self.voice = config.get("voice") or "male-qn-qingse"

    def synthesize(self, text: str, voice: str = "", response_format: str = "mp3") -> bytes:
        if not self.api_key:
            raise ValueError("MiniMax TTS 需要 minimaxKey")
        target_voice = voice or self.voice
        url = f"{self.base_url}/v1/t2a_v2"
        params = {}
        if self.group_id:
            params["GroupId"] = self.group_id
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        payload = {
            "model": self.model,
            "text": text,
            "voice_setting": {
                "voice_id": target_voice,
                "speed": 1.0,
                "vol": 1.0,
                "pitch": 0,
            },
            "audio_setting": {
                "sample_rate": 32000,
                "bitrate": 128000,
                "format": response_format,
                "channel": 1,
            },
        }
        resp = requests.post(url, headers=headers, json=payload, params=params, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        audio_hex = data.get("data", {}).get("audio")
        if audio_hex:
            import binascii
            return binascii.unhexlify(audio_hex)
        raise RuntimeError(f"MiniMax TTS 返回异常: {data}")

    @property
    def default_mime_type(self) -> str:
        return "audio/mpeg"
