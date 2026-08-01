"""LAAP Society Server - 多生命体协作视图 REST API。

迁移自 aris_brain/laap_society_server.py，统一挂载到 FastAPI app 的 /society/* 路由下。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/society", tags=["society"])


# === 内部数据访问辅助 ===
# 与原 laap_society_server 一致，提供模块级单例访问

_society_state: Dict[str, Any] = {
    "sandboxes": [],
    "agents": [],
    "suggestions": [],
    "lifeforms": [],
    "psi_status": {},
    "causal_graph": {"nodes": [], "edges": []},
    "rsi_suggestions": [],
    "memory_status": {"layers": []},
}


def set_society_state(key: str, value: Any) -> None:
    """更新 society 状态数据（供其他模块调用）。"""
    _society_state[key] = value


def get_society_state() -> Dict[str, Any]:
    """获取完整 society 状态。"""
    return _society_state


# === 路由定义 ===


@router.get("/sandboxes")
async def list_sandboxes() -> Dict[str, Any]:
    """列出所有沙箱状态。"""
    return {"sandboxes": _society_state.get("sandboxes", [])}


@router.get("/agents")
async def list_agents() -> Dict[str, Any]:
    """列出所有 Agent。"""
    return {"agents": _society_state.get("agents", [])}


@router.get("/suggestions")
async def list_suggestions() -> Dict[str, Any]:
    """列出待审建议。"""
    return {"suggestions": _society_state.get("suggestions", [])}


@router.get("/lifeforms")
async def list_lifeforms() -> Dict[str, Any]:
    """列出所有数字生命体。"""
    return {"lifeforms": _society_state.get("lifeforms", [])}


@router.get("/psi-status")
async def get_psi_status(agent_id: Optional[str] = None) -> Dict[str, Any]:
    """获取 PSI 认知状态。"""
    state = _society_state.get("psi_status", {})
    if agent_id:
        return {"agent_id": agent_id, "psi_status": state.get(agent_id, {})}
    return {"psi_status": state}


@router.get("/causal-graph")
async def get_causal_graph() -> Dict[str, Any]:
    """获取因果图。"""
    return _society_state.get("causal_graph", {"nodes": [], "edges": []})


@router.get("/rsi-suggestions")
async def list_rsi_suggestions() -> Dict[str, Any]:
    """列出 RSI 建议。"""
    return {"suggestions": _society_state.get("rsi_suggestions", [])}


@router.get("/memory-status")
async def get_memory_status(agent_id: Optional[str] = None) -> Dict[str, Any]:
    """获取记忆层级状态。"""
    return {"memory_status": _society_state.get("memory_status", {})}
