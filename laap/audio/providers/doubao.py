"""豆包（火山方舟）TTS 提供者。

兼容 OpenAI 格式的 /audio/speech 接口。
"""

from __future__ import annotations

import logging
from typing import Dict

import requests

from .base import TtsProvider

logger = logging.getLogger("laap.audio.providers.doubao")


class DoubaoTtsProvider(TtsProvider):
    provider_id = "doubao"

    def __init__(self, config: Dict[str, str]) -> None:
        super().__init__(config)
        self.base_url = (config.get("base_url") or config.get("baseUrl") or "https://ark.cn-beijing.volces.com/api/v3").rstrip("/")
        self.api_key = config.get("creds", {}).get("doubaoKey") or ""
        self.resource_id = config.get("creds", {}).get("doubaoResourceId") or ""
        self.model = config.get("model") or ""
        self.voice = config.get("voice") or ""

    def synthesize(self, text: str, voice: str = "", response_format: str = "mp3") -> bytes:
        if not self.api_key:
            raise ValueError("豆包 TTS 需要 doubaoKey")
        target_voice = voice or self.voice or self.model
        url = f"{self.base_url}/audio/speech"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        payload = {
            "input": text,
            "voice": target_voice,
            "response_format": response_format,
        }
        if self.resource_id:
            payload["model"] = self.resource_id
        resp = requests.post(url, headers=headers, json=payload, timeout=120)
        resp.raise_for_status()
        return resp.content

    @property
    def default_mime_type(self) -> str:
        return "audio/mpeg"
