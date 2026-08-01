"""火山引擎 ASR 提供者（占位实现）。

完整实现可调用火山引擎语音识别 OpenAPI：
https://www.volcengine.com/docs/6561/80818
"""

from __future__ import annotations

import logging
from typing import Dict

from .base import AsrProvider

logger = logging.getLogger("laap.audio.providers.volcengine")


class VolcengineAsrProvider(AsrProvider):
    provider_id = "volcengine"

    def __init__(self, config: Dict[str, str]) -> None:
        super().__init__(config)
        self.api_key = config.get("creds", {}).get("volcAsrApiKey") or ""
        self.app_key = config.get("creds", {}).get("volcAsrAppKey") or ""
        self.access_key = config.get("creds", {}).get("volcAsrAccessKey") or ""
        self.resource_id = config.get("creds", {}).get("volcAsrResourceId") or ""

    def recognize(self, audio: bytes, mime_type: str = "audio/webm", language: str = "zh") -> str:
        logger.warning("火山引擎 ASR 尚未实现完整 API 调用")
        return ""
