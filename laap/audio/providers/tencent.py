"""腾讯云 ASR 提供者（占位实现）。

完整实现需要调用腾讯云 API 并处理签名，详见：
https://cloud.tencent.com/document/product/1093/37823
"""

from __future__ import annotations

import logging
from typing import Dict

from .base import AsrProvider

logger = logging.getLogger("laap.audio.providers.tencent")


class TencentAsrProvider(AsrProvider):
    provider_id = "tencent"

    def __init__(self, config: Dict[str, str]) -> None:
        super().__init__(config)
        self.secret_id = config.get("creds", {}).get("tencentSecretId") or ""
        self.secret_key = config.get("creds", {}).get("tencentSecretKey") or ""
        self.app_id = config.get("creds", {}).get("tencentAppId") or ""

    def recognize(self, audio: bytes, mime_type: str = "audio/webm", language: str = "zh") -> str:
        logger.warning("腾讯云 ASR 尚未实现完整 API 调用")
        return ""
