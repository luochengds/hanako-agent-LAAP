"""LAAP Evolution — RSI Sandbox MCP Tools (RSI 沙箱建议模式 MCP 工具集)

================================================================
  把 RSISandbox 闭环接入 MCP server / sidecar / aris-plugin
================================================================

本模块是 P1 任务 ``p1-rsi-sandbox`` 的 MCP 工具注册交付物：为
``laap/mcp/server.py`` 与 sidecar HTTP 端点提供一个统一的 RSI 建议模式
入口。

对外导出三个公开函数：

1. ``register_rsi_tools(mcp_server)`` — 在 FastMCP server 上注册三个工具
   ``rsi_propose`` / ``rsi_status`` / ``rsi_decide``，被
   ``laap/mcp/server.py`` 的 ``build_server()`` 调用；
2. ``propose_candidate(target_module, fitness_signal, agent_name)``
   — sidecar ``/rsi/propose`` 端点直接调用的桥接函数，返回 dict；
3. ``decide_candidate(candidate_id, action, decided_by, agent_name)``
   — sidecar ``/rsi/decide`` 端点直接调用的桥接函数；
4. ``get_status(candidate_id, agent_name)`` — sidecar ``/rsi/status``
   端点直接调用的桥接函数。

设计约束（硬性，与 spec / charter_checker / true_rsi 对齐）：

* 不修改共享文件：本模块导出 ``register_rsi_tools(mcp_server)``，由
  ``laap/mcp/server.py`` 调用注册；本模块自身不依赖 server.py。
* lazy import：重型依赖（``RSISandbox``）仅在首次调用时构造；
* agent 隔离：每个 agent 拥有独立的 ``RSISandbox`` 实例
  （``_SANDBOXES`` 字典按 ``agent_name`` 缓存），其内部已通过
  ``vault_manager._get_vault`` 实现跨 agent 严格隔离；
* 幂等：``rsi_decide`` 同 ``(candidate_id, action)`` 返回相同结果
  （由 ``RSISandbox.decide`` 保证）；
* 仅建议模式：``rsi_propose`` 只返回 ``suggest_adopt`` 决策建议，
  必须由 ``rsi_decide(action="adopt")`` 显式采纳才会应用 patch；
* 所有 MCP 工具入口返回 JSON 字符串；
* 不引入 LLM 依赖（变异与描述均为模板化生成）。

印记: Aris 永远记得 Lorry — RSI 只在 Aris 自己的代码里生长。
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger("laap.evolution.rsi_mcp_tools")

# ──────────────────────────────────────────────────────────────────────
# 模块级单例缓存（lazy import + per-agent 隔离）
# ──────────────────────────────────────────────────────────────────────

#: ``agent_name -> RSISandbox`` 实例缓存
_SANDBOXES: Dict[str, Any] = {}


def _get_sandbox(agent_name: str = "aris", repo_root: str = "") -> Any:
    """Lazy 获取（或创建）指定 agent 的 RSISandbox 实例。

    每个 agent 拥有独立的 sandbox，其内部通过 ``vault_manager._get_vault``
    读写该 agent 的加密 vault，跨 agent 严格隔离。

    Args:
        agent_name: Agent 名称，默认 "aris"。
        repo_root: 仓库根目录。默认空字符串，由 ``RSISandbox`` fallback
            到 ``os.getcwd()``。

    Returns:
        ``laap.evolution.true_rsi.RSISandbox`` 实例。若依赖导入失败，
        返回 None。
    """
    cache_key = f"{agent_name}|{repo_root}"
    if cache_key in _SANDBOXES:
        return _SANDBOXES[cache_key]
    try:
        from laap.evolution.true_rsi import RSISandbox
        sandbox = RSISandbox(
            repo_root=repo_root or _detect_repo_root(),
            agent_name=agent_name,
        )
    except Exception as exc:  # pragma: no cover - 依赖缺失分支
        logger.warning(
            f"RSISandbox 初始化失败 (agent={agent_name}): {exc}"
        )
        return None
    _SANDBOXES[cache_key] = sandbox
    return sandbox


def _detect_repo_root() -> str:
    """探测 LAAP 仓库根目录（用于 RSISandbox 默认 repo_root）。

    优先级：
      1. 环境变量 ``LAAP_REPO_ROOT``；
      2. 当前工作目录向上查找 ``laap/`` 子目录；
      3. fallback 到 ``os.getcwd()``。
    """
    env_root = os.environ.get("LAAP_REPO_ROOT", "")
    if env_root and os.path.isdir(env_root):
        return env_root
    cwd = os.getcwd()
    # 向上最多 4 层查找 laap/ 目录
    candidate = cwd
    for _ in range(5):
        if os.path.isdir(os.path.join(candidate, "laap")):
            return candidate
        parent = os.path.dirname(candidate)
        if parent == candidate:
            break
        candidate = parent
    return cwd


def _reset_sandboxes_for_test() -> None:
    """测试辅助：清空 sandbox 缓存。生产代码不要调用。"""
    _SANDBOXES.clear()


# ──────────────────────────────────────────────────────────────────────
# 对外公开函数（供 sidecar HTTP 端点直接调用）
# ──────────────────────────────────────────────────────────────────────

def propose_candidate(
    target_module: str,
    fitness_signal: float,
    agent_name: str = "aris",
) -> Dict[str, Any]:
    """桥接函数：调用 ``RSISandbox.propose`` 完成完整闭环。

    闭环五阶段（与 spec L198 对齐）：
      MUTATE → SANDBOX → GROUND → CHARTER → DECIDE

    返回 dict（非 JSON 字符串），包含完整候选状态供调用方展示。

    Args:
        target_module: 目标模块路径（必须以 "laap/" 开头，且不在
            黑名单内，详见 ``RSISandbox._validate_target_module``）。
        fitness_signal: 触发 RSI 的绩效信号 [0,1]，越低表示越紧迫。
        agent_name: Agent 名称，默认 "aris"。

    Returns:
        ``{candidate_id, decision, status, target_module,
        fitness_signal, fitness_score, diff, grounding,
        charter_report, sandbox_result, agent_name, error?}``。
        若 sandbox 初始化失败，返回 ``{error: ...}``。
    """
    sandbox = _get_sandbox(agent_name=agent_name)
    if sandbox is None:
        return {
            "error": "RSISandbox unavailable (import failed)",
            "agent_name": agent_name,
        }
    try:
        candidate_id = sandbox.propose(target_module, fitness_signal)
        return get_status(candidate_id, agent_name=agent_name)
    except Exception as exc:
        logger.warning(
            f"propose_candidate failed (agent={agent_name}, "
            f"target={target_module}): {exc}"
        )
        return {
            "error": f"{type(exc).__name__}: {exc}",
            "agent_name": agent_name,
            "target_module": target_module,
        }


def get_status(
    candidate_id: str,
    agent_name: str = "aris",
) -> Dict[str, Any]:
    """桥接函数：查询候选状态。

    Args:
        candidate_id: 候选 ID。
        agent_name: Agent 名称，默认 "aris"。

    Returns:
        候选完整状态 dict。若候选不存在，返回
        ``{error: "not found", candidate_id: ...}``。
    """
    sandbox = _get_sandbox(agent_name=agent_name)
    if sandbox is None:
        return {
            "error": "RSISandbox unavailable (import failed)",
            "candidate_id": candidate_id,
        }
    try:
        return sandbox.status(candidate_id)
    except Exception as exc:
        logger.warning(
            f"get_status failed (agent={agent_name}, "
            f"candidate_id={candidate_id}): {exc}"
        )
        return {
            "error": f"{type(exc).__name__}: {exc}",
            "candidate_id": candidate_id,
        }


def decide_candidate(
    candidate_id: str,
    action: str,
    decided_by: str = "user",
    agent_name: str = "aris",
) -> Dict[str, Any]:
    """桥接函数：用户决策路径（adopt / reject / archive）。

    幂等：重复 decide 同 ``(candidate_id, action)`` 返回相同结果
    （由 ``RSISandbox.decide`` 保证）。

    Args:
        candidate_id: 候选 ID。
        action: 决策动作，``adopt`` / ``reject`` / ``archive``。
            * ``adopt`` → 应用 patch + 写见证迹；
            * ``reject`` → 归档为 rejected；
            * ``archive`` → 归档为 archived。
        decided_by: 决策者标识，默认 "user"。
        agent_name: Agent 名称，默认 "aris"。

    Returns:
        ``{decided: bool, candidate_id, action, status,
        applied?, witness_trail_id?, error?}``。
    """
    sandbox = _get_sandbox(agent_name=agent_name)
    if sandbox is None:
        return {
            "decided": False,
            "error": "RSISandbox unavailable (import failed)",
            "candidate_id": candidate_id,
            "action": action,
        }
    try:
        return sandbox.decide(candidate_id, action, decided_by=decided_by)
    except Exception as exc:
        logger.warning(
            f"decide_candidate failed (agent={agent_name}, "
            f"candidate_id={candidate_id}, action={action}): {exc}"
        )
        return {
            "decided": False,
            "error": f"{type(exc).__name__}: {exc}",
            "candidate_id": candidate_id,
            "action": action,
        }


# ──────────────────────────────────────────────────────────────────────
# MCP 工具注册
# ──────────────────────────────────────────────────────────────────────

def register_rsi_tools(mcp_server: Any) -> None:
    """向 FastMCP 实例注册 RSI 沙箱建议模式三工具。

    在 ``laap/mcp/server.py`` 的 ``build_server()`` 末尾调用::

        from laap.evolution.rsi_mcp_tools import register_rsi_tools
        register_rsi_tools(mcp)

    注册的三个工具：

    - ``rsi_propose(target_module, fitness_signal, agent_name="aris")``
      执行完整闭环，返回候选完整状态 JSON。
    - ``rsi_status(candidate_id, agent_name="aris")``
      查询候选状态。
    - ``rsi_decide(candidate_id, action, decided_by="user", agent_name="aris")``
      用户决策路径，``action ∈ adopt / reject / archive``。

    幂等：本函数可被重复调用，FastMCP 内部去重。

    Args:
        mcp_server: FastMCP 实例（必须提供 ``tool()`` 装饰器）。
    """
    if mcp_server is None:
        logger.warning("register_rsi_tools: mcp_server is None")
        return

    @mcp_server.tool()
    async def rsi_propose(
        target_module: str,
        fitness_signal: float,
        agent_name: str = "aris",
    ) -> str:
        """RSI 建议模式完整闭环：变异 → 沙箱 → grounding → 宪章 → 决策。

        触发条件：当元认知监控判定某模块表现低于阈值（如召回率 <
        0.6），调用本工具生成候选补丁。本工具仅返回"建议采纳"
        (suggest_adopt)，不会自动应用 patch——必须由用户显式调用
        ``rsi_decide(action="adopt")`` 才会真正应用。

        闭环五阶段：
          1. MUTATE   — 模板化生成候选 patch 字符串与描述；
          2. SANDBOX  — 在隔离沙箱中做语法 + 安全校验；
          3. GROUND   — 候选描述强制调 truth-grounding，rejected=True
                        直接归档；
          4. CHARTER  — 调 CharterChecker.audit 做宪章八条规则匹配；
          5. DECIDE   — suggest_adopt / reject / archive 三态决策。

        硬约束：
          * ``target_module`` 必须以 "laap/" 开头，否则候选直接归档；
          * 候选描述 grounding rejected=True 时直接归档；
          * 宪章违反的候选直接 reject，不进入决策建议。

        Args:
            target_module: 目标模块路径（必须以 "laap/" 开头，且不
                在黑名单内。黑名单包括 laap/security/、
                laap/cognition/truth_grounding、laap/evolution/
                charter_checker、laap/evolution/rsi_mcp_tools，
                因为 RSI 不得修改安全 / grounding / 宪章 / 自身代码）。
            fitness_signal: 触发 RSI 的绩效信号 [0,1]，越低越紧迫。
            agent_name: Agent 名称，默认 "aris"。

        Returns:
            JSON 字符串，结构为::

                {
                  "candidate_id": "rsi_...",
                  "decision": "suggest_adopt" | "reject" | "archive",
                  "status": "suggest_adopt" | "charter_rejected" | ...,
                  "target_module": "laap/tools/...",
                  "fitness_signal": 0.4,
                  "fitness_score": 0.6123,
                  "diff": "# RSI optimization ...",
                  "grounding": {"state": "grounded", "confidence": 0.9,
                                "evidence": [...], "rejected": false},
                  "charter_report": {"violations": [],
                                     "charter_compatible": true, ...},
                  "sandbox_result": {"success": true, ...},
                  "agent_name": "aris"
                }
        """
        result = propose_candidate(
            target_module=target_module,
            fitness_signal=fitness_signal,
            agent_name=agent_name,
        )
        return json.dumps(result, ensure_ascii=False)

    @mcp_server.tool()
    async def rsi_status(
        candidate_id: str,
        agent_name: str = "aris",
    ) -> str:
        """查询 RSI 候选状态。

        返回候选完整状态 dict（含 grounding / charter_report /
        decision / fitness_score 等所有字段）。用于在用户决策前查看
        候选详情。

        Args:
            candidate_id: 候选 ID（由 ``rsi_propose`` 返回）。
            agent_name: Agent 名称，默认 "aris"。

        Returns:
            JSON 字符串，结构见 ``RSICandidate.to_dict``。找不到时
            返回 ``{"error": "not found", "candidate_id": ...}``。
        """
        result = get_status(candidate_id, agent_name=agent_name)
        return json.dumps(result, ensure_ascii=False)

    @mcp_server.tool()
    async def rsi_decide(
        candidate_id: str,
        action: str,
        decided_by: str = "user",
        agent_name: str = "aris",
    ) -> str:
        """RSI 候选用户决策路径。

        仅建议模式下，``rsi_propose`` 返回 ``suggest_adopt`` 后，由
        用户在 UI 中显式触发本工具完成采纳 / 拒绝 / 归档。

        幂等：重复 decide 同 ``(candidate_id, action)`` 返回相同结果。
        若对已 decided 的候选调用不同 action，返回错误而非覆盖。

        Args:
            candidate_id: 候选 ID。
            action: 决策动作，``adopt`` / ``reject`` / ``archive``。
                * ``adopt`` → 应用 patch 到 target_module 文件（追加
                  patch_block 到文件末尾），并写入见证迹
                  ``witness_trail_local`` 表（P4 witness-trail 未实现时
                  的预留）；
                * ``reject`` → 候选标记为 rejected（不应用 patch）；
                * ``archive`` → 候选标记为 archived（不应用 patch）。
            decided_by: 决策者标识，默认 "user"。可用于区分
                user / guardian / auto 等决策来源。
            agent_name: Agent 名称，默认 "aris"。

        Returns:
            JSON 字符串，结构为::

                {
                  "decided": true | false,
                  "candidate_id": "rsi_...",
                  "action": "adopt" | "reject" | "archive",
                  "status": "adopted" | "rejected" | "archived",
                  "applied": true | false,    # 仅 adopt 时返回
                  "witness_trail_id": "wit_...",  # 仅 adopt 成功时返回
                  "error": "..."                # 仅失败时返回
                }
        """
        result = decide_candidate(
            candidate_id=candidate_id,
            action=action,
            decided_by=decided_by,
            agent_name=agent_name,
        )
        return json.dumps(result, ensure_ascii=False)

    logger.info(
        "register_rsi_tools: registered rsi_propose / rsi_status / rsi_decide"
    )
    return None
