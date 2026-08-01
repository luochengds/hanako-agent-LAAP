"""Triphase 核心类型与 JSON 之间的编解码。

目标：让 numpy 复向量、Trit 三值、PhaseState 等可跨 CognitiveBus 序列化。
"""

from __future__ import annotations

import base64
from typing import Any

import numpy as np

from triphase.core import Trit, PhaseState
from triphase.memory import MemoryItem, RetrievalResult
from triphase.grounding import Claim, ClaimVerdict, GroundingReport, GroundingAction


class TritJSONCodec:
    """Trit ↔ 字符串/整数。"""

    @staticmethod
    def encode(trit: Trit) -> str:
        return trit.name  # "POS" / "NEUTRAL" / "NEG"

    @staticmethod
    def decode(value: str) -> Trit:
        return Trit[value.upper()]


class PhaseStateJSONCodec:
    """PhaseState ↔ dict。"""

    @staticmethod
    def encode(state: PhaseState) -> dict[str, float]:
        return {
            "magnitude": float(state.magnitude),
            "phase": float(state.phase),
            "trit": TritJSONCodec.encode(state.trit),
        }

    @staticmethod
    def decode(data: dict[str, Any]) -> PhaseState:
        return PhaseState(
            magnitude=float(data["magnitude"]),
            phase=float(data["phase"]),
        )


def _encode_complex_vector(vec: np.ndarray) -> str:
    """将复向量压缩为 base64 pickle。"""
    vec = np.asarray(vec, dtype=np.complex64)
    raw = vec.tobytes()
    return base64.b64encode(raw).decode("ascii")


def _decode_complex_vector(b64: str, dim: int) -> np.ndarray:
    """从 base64 还原复向量；若维度不符会抛出 ValueError。"""
    raw = base64.b64decode(b64.encode("ascii"))
    vec = np.frombuffer(raw, dtype=np.complex64)
    if vec.size != dim:
        raise ValueError(f"向量维度 {vec.size} 与期望 {dim} 不符")
    return vec


def triphase_to_dict(obj: Any) -> Any:
    """将 triphase 对象递归转为 JSON-safe dict/list。"""
    if isinstance(obj, Trit):
        return TritJSONCodec.encode(obj)
    if isinstance(obj, PhaseState):
        return PhaseStateJSONCodec.encode(obj)
    if isinstance(obj, MemoryItem):
        return {
            "key": obj.key,
            "payload": obj.payload,
            "state": triphase_to_dict(obj.state),
            "strength": float(obj.strength),
            "access_count": obj.access_count,
            "created_at": obj.created_at,
            "updated_at": obj.updated_at,
            "rebuilds": obj.rebuilds,
            "vector": _encode_complex_vector(obj.vector),
        }
    if isinstance(obj, RetrievalResult):
        return {
            "item": triphase_to_dict(obj.item),
            "score": float(obj.score),
        }
    if isinstance(obj, Claim):
        return {
            "text": obj.text,
            "kind": obj.kind.value,
            "slots": obj.slots,
        }
    if isinstance(obj, ClaimVerdict):
        return {
            "claim": triphase_to_dict(obj.claim),
            "trit": triphase_to_dict(obj.trit),
            "reason": obj.reason,
            "evidence": obj.evidence,
            "hard": obj.hard,
        }
    if isinstance(obj, GroundingReport):
        return {
            "action": obj.action.value,
            "verdicts": [triphase_to_dict(v) for v in obj.verdicts],
            "unverified_ratio": float(obj.unverified_ratio),
            "refuted": [triphase_to_dict(v) for v in obj.refuted],
            "antibody_hits": obj.antibody_hits,
            "telemetry": {
                "retrieval_hit_rate": float(obj.telemetry.retrieval_hit_rate),
                "hypothesis_dispersion": float(obj.telemetry.hypothesis_dispersion),
                "unverified_dependency_ratio": float(obj.telemetry.unverified_dependency_ratio),
                "negative_conflicts": int(obj.telemetry.negative_conflicts),
            },
        }
    if isinstance(obj, GroundingAction):
        return obj.value
    if isinstance(obj, np.ndarray):
        return _encode_complex_vector(obj)
    if isinstance(obj, (np.floating, np.integer)):
        return float(obj) if isinstance(obj, np.floating) else int(obj)
    if isinstance(obj, (list, tuple)):
        return [triphase_to_dict(v) for v in obj]
    if isinstance(obj, dict):
        return {k: triphase_to_dict(v) for k, v in obj.items()}
    return obj


def dict_to_triphase(data: Any, cls: type | None = None) -> Any:
    """将 JSON dict 还原为 triphase 对象（目前仅支持 Trit / PhaseState 显式还原）。"""
    if cls is Trit and isinstance(data, str):
        return TritJSONCodec.decode(data)
    if cls is PhaseState and isinstance(data, dict):
        return PhaseStateJSONCodec.decode(data)
    return data
