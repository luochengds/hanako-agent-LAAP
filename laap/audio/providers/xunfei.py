"""科大讯飞 RTASR 提供者（占位实现）。

完整实现需要建立 websocket 连接并处理鉴权，详见：
https://www.xfyun.cn/doc/asr/rtasr/API.html
"""

from __future__ import annotations

import logging
from typing import Dict

from .base import AsrProvider

logger = logging.getLogger("laap.audio.providers.xunfei")


class XunfeiAsrProvider(AsrProvider):
    provider_id = "xunfei"

    def __init__(self, config: Dict[str, str]) -> None:
        super().__init__(config)
        self.app_id = config.get("creds", {}).get("xunfeiAppId") or ""
        self.api_key = config.get("creds", {}).get("xunfeiApiKey") or ""

    def recognize(self, audio: bytes, mime_type: str = "audio/webm", language: str = "zh") -> str:
        logger.warning("科大讯飞 ASR 尚未实现完整 API 调用")
        return ""
