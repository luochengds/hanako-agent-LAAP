"""Triphase Bridge 与 LAAP 前端通信的 CognitiveBus topic 常量。"""

from __future__ import annotations

from enum import Enum


class TriphaseTopic(str, Enum):
    """命名空间统一为 triphase.{domain}.{action}。"""

    # ------------------------------------------------------------------ 记忆
    MEMORY_STORE = "triphase.memory.store"
    MEMORY_RETRIEVE = "triphase.memory.retrieve"
    MEMORY_RETRIEVED = "triphase.memory.retrieved"
    MEMORY_CONSOLIDATED = "triphase.memory.consolidated"

    # ------------------------------------------------------------------ 接地
    GROUNDING_VERIFY = "triphase.grounding.verify"
    GROUNDING_REPORT = "triphase.grounding.report"
    GROUNDING_ANTIBODY_HIT = "triphase.grounding.antibody_hit"

    # ------------------------------------------------------------------ 管线
    PIPELINE_ROUTE = "triphase.pipeline.route"
    PIPELINE_STATS = "triphase.pipeline.stats"

    # ------------------------------------------------------------------ 元认知
    METACOG_TELEMETRY = "triphase.metacog.telemetry"
    METACOG_VERDICT = "triphase.metacog.verdict"

    # ------------------------------------------------------------------ 自愈 / RSI
    SELFHEAL_ANOMALY = "triphase.selfheal.anomaly"
    SELFHEAL_RESOLVED = "triphase.selfheal.resolved"
    RSI_PROPOSAL = "triphase.rsi.proposal"
    RSI_FROZEN = "triphase.rsi.frozen"

    # ------------------------------------------------------------------ 服务状态
    BRIDGE_STATUS = "triphase.bridge.status"
