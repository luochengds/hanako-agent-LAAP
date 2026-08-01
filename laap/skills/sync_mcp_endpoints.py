"""LAAP Skills — Skill Sync MCP 工具与 sidecar 端点桥接 (P3-skill-sync)

================================================================
  把 SkillSyncManager (sync_skill / advance / get_job / list_jobs)
  接入 MCP server 与 sidecar HTTP 端点 ``/skills/sync*``
================================================================

本模块是 P3 任务 ``p3-skill-sync`` 的 MCP 工具注册交付物，为
``laap/mcp/server.py`` 与 sidecar HTTP 端点 ``/skills/sync*`` 提供
统一入口。

对外导出的桥接函数（供 sidecar ``_post_handler`` 调用）：

1. ``handle_skill_sync_start(peer_public_key, skill_id, target_agent,
   personality_override?, auto_advance?)`` —
   ``POST /skills/sync`` 端点桥接（启动同步任务）；
2. ``handle_skill_sync_status(sync_job_id)`` —
   ``POST /skills/sync/status`` 端点桥接（查询任务状态）；
3. ``handle_skill_sync_list(state_filter?)`` —
   ``POST /skills/sync/list`` 端点桥接（列出全部任务）；
4. ``handle_skill_sync_advance(sync_job_id)`` —
   ``POST /skills/sync/advance`` 端点桥接（手动推进下一步，
   auto_advance=False 时使用）。

另导出 ``register_skill_sync_tools(mcp_server)``，供
``laap/mcp/server.py`` 的 ``build_server()`` 末尾调用注册 MCP 工具。

设计约束（与 spec L304-313 / L427-435 对齐）：

* 不修改共享文件：本模块导出注册函数，由 ``laap/mcp/server.py`` 调用；
* lazy import：``SkillSyncManager`` 等仅在首次调用时导入；
* 私钥永不离开 sidecar：本模块不涉及私钥参数；
* 复用 P3 p2p-relay：``peer_public_key`` 由调用方传入，本模块仅
  记录用于 audit，签名验证由上层完成（spec 硬约束：
  p3-skill-sync 依赖 p3-p2p-relay）；
* LLM 调用必经 truth-grounding 管线（在 ``SkillSyncManager`` 内部
  ``_step_understanding`` 中完成，本模块不重复实现）；
* 幂等：所有端点可重复调用；
* 所有 MCP 工具入口返回 JSON 字符串；
* vault 永不直接共享：同步过程只写入目标 agent 自己的 vault。

印记: Aris 永远记得 Lorry — 技能在传递中保持本心，性格在适配中
各自绽放。
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("laap.skills.sync_mcp_endpoints")


# ──────────────────────────────────────────────────────────────────────
# 对外公开桥接函数（供 sidecar HTTP 端点直接调用）
# ──────────────────────────────────────────────────────────────────────


def handle_skill_sync_start(
    peer_public_key: str,
    skill_id: str,
    target_agent: str = "aris",
    personality_override: Optional[str] = None,
    auto_advance: Optional[bool] = None,
) -> str:
    """桥接函数：启动一次技能同步任务.

    spec SubTask 3.1: ``sync_skill(peer_public_key, skill_id) ->
    sync_job_id``.

    Args:
        peer_public_key: 源 peer 的 base64 Ed25519 公钥（audit;
            真实签名验证由上层 p2p-relay 完成）.
        skill_id: 要同步的技能 ID（laap/skills/{skill_id}/ 必须存在）.
        target_agent: 目标 agent 名称（默认 "aris"）.
        personality_override: 性格文本覆盖（可选；测试或显式指定时使用，
            None 时由 SkillSyncManager 内部 loader 加载 ishiki.md）.
        auto_advance: 是否自动跑完四步（None 用默认 True）.

    Returns:
        JSON 字符串，结构为::

            {
              "sync_job_id": "sync_xxxx",
              "state": "adopted" | "rolled_back" | "understanding" | ...,
              "skill_id": "...",
              "target_agent": "...",
              "peer_public_key": "...",
              "current_step": 1-4,
              "error": ""              # 仅 rolled_back 时非空
            }

        失败时::

            {"synced": False, "error": "..."}
    """
    if not isinstance(peer_public_key, str) or not peer_public_key.strip():
        return json.dumps(
            {"synced": False, "error": "peer_public_key must be non-empty str"},
            ensure_ascii=False,
        )
    if not isinstance(skill_id, str) or not skill_id.strip():
        return json.dumps(
            {"synced": False, "error": "skill_id must be non-empty str"},
            ensure_ascii=False,
        )
    if not isinstance(target_agent, str) or not target_agent.strip():
        return json.dumps(
            {"synced": False, "error": "target_agent must be non-empty str"},
            ensure_ascii=False,
        )
    try:
        from laap.skills.sync import get_skill_sync_manager
        mgr = get_skill_sync_manager()
        sync_job_id = mgr.sync_skill(
            peer_public_key=peer_public_key.strip(),
            skill_id=skill_id.strip(),
            target_agent=target_agent.strip(),
            personality_override=personality_override,
            auto_advance=auto_advance,
        )
        job = mgr.get_job(sync_job_id)
        if job is None:  # pragma: no cover - 不应发生
            return json.dumps(
                {"synced": False, "error": "job disappeared after creation"},
                ensure_ascii=False,
            )
        out: Dict[str, Any] = {
            "synced": True,
            "sync_job_id": sync_job_id,
            "state": job.get("state", ""),
            "skill_id": job.get("skill_id", ""),
            "target_agent": job.get("target_agent", ""),
            "peer_public_key": job.get("peer_public_key", ""),
            "current_step": job.get("current_step", 1),
            "error": job.get("error", ""),
        }
        logger.info(
            f"skill_sync_start: job={sync_job_id} skill={skill_id} "
            f"agent={target_agent} state={out['state']}"
        )
        return json.dumps(out, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        logger.warning(f"skill_sync_start: value error {exc}")
        return json.dumps(
            {"synced": False, "error": str(exc)},
            ensure_ascii=False,
        )
    except FileNotFoundError as exc:
        logger.warning(f"skill_sync_start: skill not found {exc}")
        return json.dumps(
            {"synced": False, "error": f"skill not found: {exc}"},
            ensure_ascii=False,
        )
    except Exception as exc:
        logger.error(f"skill_sync_start: unexpected {exc}", exc_info=True)
        return json.dumps(
            {"synced": False,
             "error": f"{type(exc).__name__}: {exc}"},
            ensure_ascii=False,
        )


def handle_skill_sync_status(sync_job_id: str) -> str:
    """桥接函数：查询同步任务状态.

    Args:
        sync_job_id: 任务 ID（sync_skill 返回的 ``sync_xxxx``）.

    Returns:
        JSON 字符串，含完整任务 dict（state / current_step /
        understanding_artifact / adapting_artifact /
        testing_artifact / adopting_artifact / error 等）.

        不存在时::

            {"error": "sync_job not found: ..."}
    """
    if not isinstance(sync_job_id, str) or not sync_job_id.strip():
        return json.dumps(
            {"error": "sync_job_id must be non-empty str"},
            ensure_ascii=False,
        )
    try:
        from laap.skills.sync import get_skill_sync_manager
        mgr = get_skill_sync_manager()
        job = mgr.get_job(sync_job_id.strip())
        if job is None:
            return json.dumps(
                {"error": f"sync_job not found: {sync_job_id}"},
                ensure_ascii=False,
            )
        return json.dumps(job, ensure_ascii=False)
    except Exception as exc:
        logger.error(f"skill_sync_status: unexpected {exc}", exc_info=True)
        return json.dumps(
            {"error": f"{type(exc).__name__}: {exc}"},
            ensure_ascii=False,
        )


def handle_skill_sync_list(state_filter: Optional[str] = None) -> str:
    """桥接函数：列出全部同步任务.

    Args:
        state_filter: 可选状态过滤（"adopted" / "rolled_back" /
            "understanding" / "adapting" / "testing" / "adopting"）.

    Returns:
        JSON 字符串，结构为 ``{"jobs": [...], "count": N}``.
    """
    try:
        from laap.skills.sync import get_skill_sync_manager
        mgr = get_skill_sync_manager()
        jobs = mgr.list_jobs(state_filter=state_filter)
        return json.dumps(
            {"jobs": jobs, "count": len(jobs)},
            ensure_ascii=False,
        )
    except Exception as exc:
        logger.error(f"skill_sync_list: unexpected {exc}", exc_info=True)
        return json.dumps(
            {"jobs": [], "count": 0,
             "error": f"{type(exc).__name__}: {exc}"},
            ensure_ascii=False,
        )


def handle_skill_sync_advance(sync_job_id: str) -> str:
    """桥接函数：手动推进任务到下一步.

    auto_advance=False 创建的任务需要外部逐步推进. 终态任务 advance
    返回当前状态，不抛异常.

    Args:
        sync_job_id: 任务 ID.

    Returns:
        JSON 字符串，任务当前状态 dict（与 ``handle_skill_sync_status``
        一致，但 ``advanced=True`` 标记本次实际推进了一步）.
    """
    if not isinstance(sync_job_id, str) or not sync_job_id.strip():
        return json.dumps(
            {"advanced": False, "error": "sync_job_id must be non-empty str"},
            ensure_ascii=False,
        )
    try:
        from laap.skills.sync import get_skill_sync_manager
        mgr = get_skill_sync_manager()
        result = mgr.advance(sync_job_id.strip())
        if "error" in result and "sync_job not found" in result.get("error", ""):
            return json.dumps(result, ensure_ascii=False)
        out = dict(result)
        out["advanced"] = True
        return json.dumps(out, ensure_ascii=False)
    except Exception as exc:
        logger.error(f"skill_sync_advance: unexpected {exc}", exc_info=True)
        return json.dumps(
            {"advanced": False,
             "error": f"{type(exc).__name__}: {exc}"},
            ensure_ascii=False,
        )


# ──────────────────────────────────────────────────────────────────────
# MCP 工具注册
# ──────────────────────────────────────────────────────────────────────


def register_skill_sync_tools(mcp_server: Any) -> None:
    """向 FastMCP 实例注册 skill-sync MCP 工具.

    在 ``laap/mcp/server.py`` 的 ``build_server()`` 末尾调用::

        from laap.skills.sync_mcp_endpoints import (
            register_skill_sync_tools,
        )
        register_skill_sync_tools(mcp)

    注册的工具：

    - ``skill_sync_start(peer_public_key, skill_id, target_agent?)``
      启动一次技能同步（自动跑完四步，到终态 adopted/rolled_back）
    - ``skill_sync_status(sync_job_id)`` 查询任务状态
    - ``skill_sync_list(state_filter?)`` 列出全部任务

    ``skill_sync_advance`` 不作为 MCP 工具暴露（手动逐步推进是
    sidecar 端点专用，默认走 auto_advance=True 路径）.

    幂等：本函数可被重复调用，FastMCP 内部去重.

    Args:
        mcp_server: FastMCP 实例（必须提供 ``tool()`` 装饰器）.
    """
    if mcp_server is None:
        logger.warning("register_skill_sync_tools: mcp_server is None")
        return

    @mcp_server.tool()
    async def skill_sync_start(
        peer_public_key: str,
        skill_id: str,
        target_agent: str = "aris",
    ) -> str:
        """启动一次跨 LAAPer 技能同步（P3-skill-sync SubTask 3.1）.

        自动跑完四步状态机：understanding -> adapting ->
        testing -> adopting -> adopted. 任一步骤失败转
        rolled_back 并通过事件总线通知.

        Args:
            peer_public_key: 源 peer base64 公钥（audit）.
            skill_id: 要同步的技能 ID.
            target_agent: 目标 agent 名称（默认 "aris"）.

        Returns:
            JSON 字符串，结构::

                {
                  "synced": true,
                  "sync_job_id": "sync_xxxx",
                  "state": "adopted" | "rolled_back" | ...,
                  "skill_id": "...",
                  "target_agent": "...",
                  "current_step": 1-4,
                  "error": ""
                }
        """
        return handle_skill_sync_start(
            peer_public_key=peer_public_key,
            skill_id=skill_id,
            target_agent=target_agent,
        )

    @mcp_server.tool()
    async def skill_sync_status(sync_job_id: str) -> str:
        """查询技能同步任务状态（P3-skill-sync）.

        Args:
            sync_job_id: 任务 ID（``sync_xxxx``）.

        Returns:
            JSON 字符串，含完整任务 dict（含各步骤产物
            understanding_artifact / adapting_artifact /
            testing_artifact / adopting_artifact）.
        """
        return handle_skill_sync_status(sync_job_id)

    @mcp_server.tool()
    async def skill_sync_list(state_filter: str = "") -> str:
        """列出全部技能同步任务（P3-skill-sync）.

        Args:
            state_filter: 可选状态过滤（"adopted" / "rolled_back"
                / "understanding" / "adapting" / "testing" /
                "adopting"）；空字符串返回全部.

        Returns:
            JSON 字符串，结构 ``{"jobs": [...], "count": N}``.
        """
        return handle_skill_sync_list(
            state_filter=state_filter if state_filter else None,
        )

    logger.info(
        "register_skill_sync_tools: registered skill_sync_start / "
        "skill_sync_status / skill_sync_list "
        "(skill_sync_advance 仅 sidecar 端点，供 auto_advance=False 场景)"
    )
    return None
