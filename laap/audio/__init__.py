"""LAAP 统一音频服务 —— ASR/TTS provider 接口与 CognitiveBus 接线。"""

from .service import AudioService, get_audio_service
from .gateway import AetherGateway, start_gateway

__all__ = [
    "AudioService",
    "get_audio_service",
    "AetherGateway",
    "start_gateway",
]
