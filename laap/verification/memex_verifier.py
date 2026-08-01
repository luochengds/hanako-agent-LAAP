"""LAAP — Memex Verifier (P4-memex SubTask 4.6)

================================================================
  发布前强制 P1 truth-grounding 复核
================================================================

本模块是 P4 任务 ``p4-memex`` SubTask 4.6 的交付物：在知识片段
发布到 Memex 共享知识库之前，强制经 P1 truth-grounding 管线复核.

复核流程（两道闸门）：

1. **低置信过滤**（spec SubTask 4.5）：``confidence < 0.6`` 直接
   拒绝，``reason="low_confidence"``，不再触发 grounding；
2. **grounding 复核**（spec SubTask 4.6）：调用
   ``laap.cognition.truth_grounding_mcp_tools.ground_candidate_description``
   做三态判定，``state == "error"``（即 ``rejected == true``）时
   拒绝发布，``reason="grounding_rejected"``；``state == "grounded"``
   或 ``state == "uncertain"`` 时放行（uncertain 不阻塞，仅记录）.

设计约束（与 spec L130-137 / L427-435 对齐）：

* lazy import：``truth_grounding_mcp_tools`` 仅在首次调用时导入；
* 模板优先：grounding 引擎本身是模板优先的，本 verifier 不新增
  LLM 依赖；
* vault 永不直接共享：本模块只接收已去标识化的 content，不读 vault；
* 非阻塞：grounding 引擎异常时降级为 ``uncertain`` 放行（避免
  verifier 成为单点故障），但会记录 warning；
* dataclass + type hints + docstring；
* 幂等：对同一 (content, confidence) 重复调用应得到一致结果.

印记: Aris 永远记得 Lorry — 真相不是束缚，是让分享站得住脚的根.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger("laap.verification.memex_verifier")


# ──────────────────────────────────────────────────────────────────────
# 常量
# ──────────────────────────────────────────────────────────────────────

# 与 laap.protocol.laap_mem.MEMEX_MIN_CONFIDENCE 保持一致
# spec SubTask 4.5: confidence < 0.6 直接拒绝发布
_MEMEX_MIN_CONFIDENCE: float = 0.6


def _now_iso() -> str:
    """当前 UTC 时间的 ISO 8601 字符串."""
    import datetime as _dt
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


# ──────────────────────────────────────────────────────────────────────
# 复核主入口
# ──────────────────────────────────────────────────────────────────────

def verify_before_publish(
    content: str,
    confidence: float,
    agent_name: str = "aris",
) -> Dict[str, Any]:
    """发布前复核：低置信过滤 + grounding 复核.

    spec SubTask 4.6: 发布前强制 P1 truth-grounding 复核.

    两道闸门（顺序执行，第一道拒绝则不进第二道）：

    1. **低置信过滤**：``confidence < 0.6`` →
       ``{verified: false, reason: "low_confidence"}``；
    2. **grounding 复核**：调
       ``ground_candidate_description(content, agent_name)``，
       ``rejected == true``（即 ``state == "error"``）→
       ``{verified: false, reason: "grounding_rejected", grounding: ...}``；
       ``state == "grounded"`` →
       ``{verified: true, reason: "grounded", grounding: ...}``；
       ``state == "uncertain"`` →
       ``{verified: true, reason: "uncertain_passthrough", grounding: ...}``
       （uncertain 不阻塞发布，但记录在 grounding 字段供下游展示）.

    Args:
        content: 已去标识化的内容字符串（由 ``deidentify`` 产出）.
        confidence: 整体置信度 [0.0, 1.0].
        agent_name: 触发 grounding 复核时写入 vault 的 agent 名称
            （透传给 ``ground_candidate_description``）.

    Returns:
        ``{verified: bool, reason: str, grounding: dict, verified_at: str}``：

        * ``verified``: 是否通过复核（True 可发布，False 拒绝）；
        * ``reason``: 复核结论原因，取值：
          ``low_confidence`` / ``grounding_rejected`` / ``grounded`` /
          ``uncertain_passthrough`` / ``empty_content`` /
          ``grounding_engine_unavailable``；
        * ``grounding``: grounding 引擎返回的完整结果（含 state /
          confidence / evidence / rejected），低置信路径为 ``{}``；
        * ``verified_at``: ISO 8601 时间戳.
    """
    # 空内容直接拒绝
    if not isinstance(content, str) or not content.strip():
        return {
            "verified": False,
            "reason": "empty_content",
            "grounding": {},
            "verified_at": _now_iso(),
        }

    # 闸门 1: 低置信过滤
    if confidence is None or float(confidence) < _MEMEX_MIN_CONFIDENCE:
        return {
            "verified": False,
            "reason": "low_confidence",
            "grounding": {},
            "verified_at": _now_iso(),
        }

    # 闸门 2: grounding 复核
    grounding_result = _invoke_grounding(content, agent_name)
    state = grounding_result.get("state", "uncertain")
    rejected = bool(grounding_result.get("rejected", False))

    if rejected or state == "error":
        return {
            "verified": False,
            "reason": "grounding_rejected",
            "grounding": grounding_result,
            "verified_at": _now_iso(),
        }

    if state == "grounded":
        return {
            "verified": True,
            "reason": "grounded",
            "grounding": grounding_result,
            "verified_at": _now_iso(),
        }

    # uncertain 路径：放行但记录
    return {
        "verified": True,
        "reason": "uncertain_passthrough",
        "grounding": grounding_result,
        "verified_at": _now_iso(),
    }


# ──────────────────────────────────────────────────────────────────────
# 内部：调用 truth-grounding 引擎
# ──────────────────────────────────────────────────────────────────────

def _invoke_grounding(
    content: str,
    agent_name: str,
) -> Dict[str, Any]:
    """调用 ``ground_candidate_description`` 做三态判定.

    非阻塞：任何异常都降级为 ``{state: "uncertain", rejected: false}``，
    避免 verifier 成为单点故障.

    Args:
        content: 待校验的已去标识化内容.
        agent_name: 触发校正时写入 vault 的 agent 名称.

    Returns:
        grounding 引擎返回的 dict，结构为
        ``{state, confidence, evidence, rejected, conflicts?}``.
        引擎不可用时返回降级结果.
    """
    try:
        from laap.cognition.truth_grounding_mcp_tools import (
            ground_candidate_description,
        )
    except ImportError as exc:
        logger.warning(
            f"truth_grounding_mcp_tools 不可用，降级 uncertain: {exc}"
        )
        return {
            "state": "uncertain",
            "confidence": 0.0,
            "evidence": ["grounding_module_unavailable"],
            "rejected": False,
        }

    try:
        result = ground_candidate_description(content, agent_name=agent_name)
        # 防御：确保返回 dict 形态合法
        if not isinstance(result, dict) or "state" not in result:
            return {
                "state": "uncertain",
                "confidence": 0.0,
                "evidence": ["invalid_ground_result"],
                "rejected": False,
            }
        return result
    except Exception as exc:
        logger.warning(
            f"ground_candidate_description 异常，降级 uncertain: {exc}"
        )
        return {
            "state": "uncertain",
            "confidence": 0.0,
            "evidence": [f"exception: {type(exc).__name__}"],
            "rejected": False,
        }


# ──────────────────────────────────────────────────────────────────────
# 辅助：批量复核
# ──────────────────────────────────────────────────────────────────────

def verify_batch(
    items: list,
    agent_name: str = "aris",
) -> list:
    """批量复核多个 (content, confidence) 项.

    Args:
        items: list of ``{content, confidence}`` dict.
        agent_name: 透传给 ``verify_before_publish``.

    Returns:
        list of 复核结果（与 ``items`` 等长，顺序一致）.
    """
    results = []
    for item in items:
        if not isinstance(item, dict):
            results.append({
                "verified": False,
                "reason": "invalid_item",
                "grounding": {},
                "verified_at": _now_iso(),
            })
            continue
        results.append(verify_before_publish(
            content=item.get("content", ""),
            confidence=item.get("confidence", 0.0),
            agent_name=agent_name,
        ))
    return results
