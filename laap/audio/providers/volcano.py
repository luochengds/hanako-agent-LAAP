"""火山引擎 TTS 提供者。"""

from __future__ import annotations

import base64
import logging
from typing import Dict

import requests

from .base import TtsProvider

logger = logging.getLogger("laap.audio.providers.volcano")


class VolcanoTtsProvider(TtsProvider):
    provider_id = "volcano"

    def __init__(self, config: Dict[str, str]) -> None:
        super().__init__(config)
        self.app_id = config.get("creds", {}).get("volcanoAppId") or ""
        self.token = config.get("creds", {}).get("volcanoToken") or ""
        self.base_url = (config.get("base_url") or "https://openspeech.bytedance.com").rstrip("/")
        self.model = config.get("model") or ""
        self.voice = config.get("voice") or "BV001_streaming"
        self.cluster = config.get("cluster") or "volcano_tts"

    def synthesize(self, text: str, voice: str = "", response_format: str = "mp3") -> bytes:
        if not self.app_id or not self.token:
            raise ValueError("火山引擎 TTS 需要 volcanoAppId 与 volcanoToken")
        target_voice = voice or self.voice
        url = f"{self.base_url}/api/v1/tts"
        headers = {
            "Authorization": f"Bearer; {self.token}",
            "Content-Type": "application/json",
        }
        payload = {
            "appid": self.app_id,
            "token": "default",
            "cluster": self.cluster,
            "voice_type": target_voice,
            "encoding": response_format if response_format in ("mp3", "wav", "pcm") else "mp3",
            "text": text,
        }
        resp = requests.post(url, headers=headers, json=payload, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        audio = data.get("data")
        if audio:
            return base64.b64decode(audio)
        raise RuntimeError(f"火山引擎 TTS 返回异常: {data}")

    @property
    def default_mime_type(self) -> str:
        return "audio/mpeg"
