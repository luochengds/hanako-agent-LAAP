# -*- coding: utf-8 -*-
"""SimWorld 集成配置.

定义 LAAP × SimWorld 集成所需的运行时参数，包括 UE 连接信息、
同步间隔、是否启用 mock 模式等。所有字段均可通过环境变量覆盖。

Usage:
    cfg = SimWorldConfig()                  # 默认 headless mock 模式
    cfg = SimWorldConfig.from_env()         # 从环境变量读取
    cfg = SimWorldConfig(use_mock=False)    # 真实 UE 模式
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class SimWorldConfig:
    """SimWorld 集成运行时配置.

    Attributes:
        ue_ip: Unreal Engine 服务端 IP.
        ue_port: Unreal Engine 服务端端口.
        connect_timeout: 连接超时（秒）.
        sync_interval: SimWorldBridge 后台同步间隔（秒）.
        use_mock: 是否使用 MockCommunicator（headless 模式）.
        fallback_to_llm: LAAP 因果推演失败时是否回退到纯 LLM 模式.
        llm_model_name: LLM 模型名（用于 A2ALLM 父类初始化）.
        event_prefix: CognitiveBus 事件源前缀.
    """

    ue_ip: str = "127.0.0.1"
    ue_port: int = 9000
    connect_timeout: float = 5.0
    sync_interval: float = 0.1
    use_mock: bool = True  # 默认 headless，便于 CI
    fallback_to_llm: bool = True
    llm_model_name: str = "gpt-4o-mini"
    event_prefix: str = "simworld"

    @classmethod
    def from_env(cls) -> "SimWorldConfig":
        """从环境变量读取配置.

        支持的环境变量:
            SIMWORLD_UE_IP, SIMWORLD_UE_PORT,
            SIMWORLD_CONNECT_TIMEOUT, SIMWORLD_SYNC_INTERVAL,
            SIMWORLD_USE_MOCK, SIMWORLD_FALLBACK_TO_LLM,
            SIMWORLD_LLM_MODEL_NAME, SIMWORLD_EVENT_PREFIX
        """
        def _get_str(key: str, default: str) -> str:
            return os.getenv(key, default)

        def _get_int(key: str, default: int) -> int:
            try:
                return int(os.getenv(key, default))
            except (TypeError, ValueError):
                return default

        def _get_float(key: str, default: float) -> float:
            try:
                return float(os.getenv(key, default))
            except (TypeError, ValueError):
                return default

        def _get_bool(key: str, default: bool) -> bool:
            raw = os.getenv(key)
            if raw is None:
                return default
            return raw.strip().lower() in ("1", "true", "yes", "on")

        return cls(
            ue_ip=_get_str("SIMWORLD_UE_IP", "127.0.0.1"),
            ue_port=_get_int("SIMWORLD_UE_PORT", 9000),
            connect_timeout=_get_float("SIMWORLD_CONNECT_TIMEOUT", 5.0),
            sync_interval=_get_float("SIMWORLD_SYNC_INTERVAL", 0.1),
            use_mock=_get_bool("SIMWORLD_USE_MOCK", True),
            fallback_to_llm=_get_bool("SIMWORLD_FALLBACK_TO_LLM", True),
            llm_model_name=_get_str("SIMWORLD_LLM_MODEL_NAME", "gpt-4o-mini"),
            event_prefix=_get_str("SIMWORLD_EVENT_PREFIX", "simworld"),
        )

    def to_dict(self) -> dict:
        return {
            "ue_ip": self.ue_ip,
            "ue_port": self.ue_port,
            "connect_timeout": self.connect_timeout,
            "sync_interval": self.sync_interval,
            "use_mock": self.use_mock,
            "fallback_to_llm": self.fallback_to_llm,
            "llm_model_name": self.llm_model_name,
            "event_prefix": self.event_prefix,
        }
