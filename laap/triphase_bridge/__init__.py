"""LAAP Triphase Bridge — 将三值/复相位认知算法接入 LAAP 事件总线。

该包作为 LAAP 与 triphase_engine 之间的适配层，提供：
- 统一的 topic 常量
- PhaseState / Trit / MemoryItem / GroundingReport 的 JSON 编解码
- 文本 → 复相位向量的编码器
- Memory Bridge：CRM 复谐振记忆的封装
- Grounding Bridge：PCG 反幻觉接地的封装
- TriphaseBridgeService：生命周期管理与事件总线集成
"""

from __future__ import annotations

from .service import TriphaseBridgeService
from .memory_service import TriphaseMemoryService
from .grounding_service import TriphaseGroundingService
from .codec import (
    TritJSONCodec,
    PhaseStateJSONCodec,
    triphase_to_dict,
    dict_to_triphase,
)
from .encoder import TextEncoder
from .topics import TriphaseTopic
from .websocket_forwarder import EventBusToWebSocketForwarder

__all__ = [
    "TriphaseBridgeService",
    "TriphaseMemoryService",
    "TriphaseGroundingService",
    "TritJSONCodec",
    "PhaseStateJSONCodec",
    "triphase_to_dict",
    "dict_to_triphase",
    "TextEncoder",
    "TriphaseTopic",
    "EventBusToWebSocketForwarder",
]

__version__ = "0.1.0"
