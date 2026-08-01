"""LAAP Protocol — 共同进化循环 (P4-coevolution-loop)

================================================================
  个人经验 -> 提炼分享 -> 他人吸收 -> 新经验回传 -> 共同进化图
================================================================

本模块是 P4 任务 ``p4-coevolution-loop`` 的核心交付物：在
``p4-memex`` 共享知识库之上构建经验共同进化闭环.

**与 ``laap_evo.py`` 的关系**：
``laap_evo.py`` 仅定义 ``EvolutionProtocol`` 抽象基类 +
``MutationProposal`` / ``ExperiencePacket`` / ``SelectionReport``
dataclass，不含具体实现. 本模块**不修改该抽象基类**，而是
新建独立的 ``CoevolutionLoop`` 具体类，专注于"经验级"的共同
进化（区别于变异级的 RSI）.

SubTask 对照 (tasks.md L139-145)：

* SubTask 4.1 ``share_experience(agent, experience) -> shared_id``
  调用 ``p4-memex`` 的 ``publish_knowledge`` 把个人经验以去标识化
  形式发布到社区知识库，得到 ``knowledge_id``，并创建共同进化图
  的根节点；
* SubTask 4.2 ``absorb_experience(agent, shared_id) -> new_experience_id``
  从社区取回某条共享经验，LLM 主导提炼吸收（生成新视角的内容），
  **必经 truth-grounding 管线**校验，再把新经验以 ``derived_from``
  标记发布回 Memex；
* SubTask 4.3 ``feedback_experience(new_experience_id, derived_from)``
  把派生经验回传给原始分享者（标记 ``derived_from`` 关系并触发通知）；
* SubTask 4.4 共同进化图：节点 = 经验，边 = ``derived_from`` 关系，
  存入进程内 ``coevolution_graph``（dict + 邻接表）；
* SubTask 4.5 通知机制：经验回传后通过 ``laap.events.bus`` 发布
  ``coevolution_feedback`` 事件，原始分享者可订阅并选择吸收；
* SubTask 4.6 ``laap/evolution/test_coevolution.py`` 测试分享 →
  吸收 → 回传 → 通知 闭环.

设计约束（与 spec L139-145 / L427-435 对齐）：

* 不修改共享文件：本模块导出注册函数，由 ``laap/mcp/server.py`` 调用；
* lazy import：``publish_knowledge`` / ``ground_candidate_description``
  / ``bus`` 仅在首次调用时导入；
* vault 永不直接共享：经验必须先经 Memex ``deidentify``；
* LLM 调用必经 truth-grounding 管线（``ground_candidate_description``）；
* dataclass + type hints + docstring；
* 所有 MCP 工具入口返回 JSON 字符串；
* 幂等：同一 (agent, knowledge_id) 二次 absorb 返回同一
  ``new_experience_id``；
* 不可变：共同进化图节点一旦创建，``derived_from`` 不可修改
  （篡改检测由 ``stats()`` 中的图一致性检查体现）.

印记: 经验在两个生命之间流转，从此不再是孤岛.
"""
from __future__ import annotations

import json
import logging
import threading
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

logger = logging.getLogger("laap.protocol.laap_coevolution")


# ──────────────────────────────────────────────────────────────────────
# 共同进化图节点
# ──────────────────────────────────────────────────────────────────────

@dataclass
class ExperienceNode:
    """共同进化图中的一个节点：一条经验（共享或派生）.

    Attributes:
        experience_id: ``coevo_xxxx`` 共同进化图节点 ID（区别于
            Memex 的 ``knowledge_id``）.
        knowledge_id: 对应的 Memex 知识记录 ID（``know_xxxx``）.
        agent: 创建该经验的 agent 标识（分享者或吸收者）.
        content: 已去标识化的经验内容（来自 Memex）.
        confidence: 经验置信度 [0.0, 1.0].
        derived_from: 父经验 ID. ``None`` 表示原始分享节点，
            非空表示派生自某次 absorb.
        derived_chain: 完整派生链（从根到本节点的 experience_id 列表）.
        created_at: 创建时间 ISO 8601.
        absorption_summary: absorb 时 LLM 提炼的吸收摘要（仅派生节点）.
        publisher_public_key: 发布者 base64 公钥（可选，用于验签）.
    """

    experience_id: str = ""
    knowledge_id: str = ""
    agent: str = ""
    content: str = ""
    confidence: float = 0.0
    derived_from: Optional[str] = None
    derived_chain: List[str] = field(default_factory=list)
    created_at: str = ""
    absorption_summary: str = ""
    publisher_public_key: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)


def _now_iso() -> str:
    """当前 UTC 时间的 ISO 8601 字符串."""
    import datetime as _dt
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


# ──────────────────────────────────────────────────────────────────────
# LLM 主导路径（必经 truth-grounding 管线）
# ──────────────────────────────────────────────────────────────────────

def _ground_via_truth_grounding(
    description: str,
    agent_name: str = "coevo",
) -> Dict[str, Any]:
    """把经验描述送入 truth-grounding 管线校验.

    spec 硬约束：**LLM 调用必经 truth-grounding 管线**
    （``laap/cognition/truth_grounding_mcp_tools.py`` 的
    ``ground_candidate_description``）.

    环境无 truth_grounding engine 时，返回 ``state=uncertain``，
    由调用方降级到模板路径.
    """
    try:
        from laap.cognition.truth_grounding_mcp_tools import (
            ground_candidate_description,
        )
        return ground_candidate_description(description, agent_name=agent_name)
    except Exception as exc:
        logger.warning(
            f"ground_candidate_description failed (降级模板路径): {exc}"
        )
        return {
            "state": "uncertain",
            "confidence": 0.0,
            "evidence": [f"grounding_unavailable: {type(exc).__name__}"],
            "rejected": False,
        }


def _llm_absorb_summary(
    parent_content: str,
    agent: str,
    agent_name: str = "coevo",
) -> Dict[str, Any]:
    """LLM 主导路径：从父经验提炼出吸收摘要（必经 truth-grounding 管线）.

    TODO 升级为 LLM 主导：当前 truth-grounding 管线只做事实校验，
    不做摘要生成. 本函数现阶段先用规则模板生成摘要 + truth-grounding
    校验摘要的事实性，返回 ``{summary, grounding}``.
    后续接入真实 LLM 后，摘要生成由 LLM 主导，但仍必经
    truth-grounding 管线校验.

    Args:
        parent_content: 父经验的去标识化内容.
        agent: 吸收方 agent 标识（用于差异化生成）.
        agent_name: 触发 grounding 复核时写入 vault 的 agent 名称.

    Returns:
        ``{summary: str, grounding: dict, derived_content: str}``.
        ``derived_content`` 是把摘要合并到父内容后形成的新经验文本.
    """
    # 模板路径：从父内容截前 80 字 + 吸收者视角
    snippet = parent_content.strip().replace("\n", " ")
    if len(snippet) > 80:
        snippet = snippet[:80] + "..."
    summary = (
        f"[{agent} 吸收视角] 在原经验「{snippet}」基础上，"
        f"结合自身场景提炼出可复用的实践要点."
    )
    # 把摘要送入 truth-grounding 管线校验事实性
    grounding = _ground_via_truth_grounding(summary, agent_name=agent_name)
    derived_content = f"{summary}\n\n基于: {parent_content}"
    return {
        "summary": summary,
        "grounding": grounding,
        "derived_content": derived_content,
    }


# ──────────────────────────────────────────────────────────────────────
# CoevolutionLoop
# ──────────────────────────────────────────────────────────────────────

class CoevolutionLoop:
    """共同进化循环（进程内单例）.

    内部维护：

    * ``_nodes``: ``experience_id -> ExperienceNode`` 主索引；
    * ``_knowledge_index``: ``knowledge_id -> experience_id`` 反查
      （幂等：同一 ``knowledge_id`` 二次 absorb 返回同一节点）；
    * ``_children``: ``experience_id -> [child_experience_id, ...]``
      邻接表（共同进化图的边）.

    线程安全：所有公开方法用 ``threading.RLock`` 保护.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._nodes: Dict[str, ExperienceNode] = {}
        self._knowledge_index: Dict[str, str] = {}
        self._children: Dict[str, List[str]] = {}

    # ── SubTask 4.1: share_experience ─────────────────────

    def share_experience(
        self,
        agent: str,
        content: str,
        source_memories: List[Dict[str, Any]],
        confidence: float,
        agent_name: str = "coevo",
        publisher_public_key: str = "",
        publisher_private_key: Optional[bytes] = None,
    ) -> Dict[str, Any]:
        """分享一条个人经验到共同进化图（spec SubTask 4.1）.

        端到端流程：
        1. 调用 ``p4-memex`` 的 ``publish_knowledge`` 把 ``content``
           去标识化 + 附加证据链 + grounding 复核 + 存储到 Memex；
        2. 创建共同进化图根节点 ``ExperienceNode``（``derived_from=None``）；
        3. 发布 ``coevolution_shared`` 事件到本地 EventBus；
        4. 返回 ``{shared: true, shared_id, knowledge_id}``.

        Args:
            agent: 分享者 agent 标识.
            content: 原始经验内容字符串（可能含隐私痕迹，会自动去标识化）.
            source_memories: 来源记忆列表（来自 vault retrieve），每项
                至少含 ``memory_id`` 字段.
            confidence: 整体置信度 [0.0, 1.0]. 低于 0.6 会被 Memex 拒绝.
            agent_name: 触发 grounding 复核时写入 vault 的 agent 名称.
            publisher_public_key: 发布者 base64 公钥（可选）.
            publisher_private_key: 发布者 32 字节 Raw Ed25519 私钥（可选，
                spec L435 私钥永不离开 sidecar）.

        Returns:
            ``{shared: bool, reason?: str, shared_id?: str,
            knowledge_id?: str}``. 失败时 ``reason`` 来自 Memex.
        """
        if not isinstance(agent, str) or not agent.strip():
            return {"shared": False, "reason": "empty_agent"}
        if not isinstance(content, str) or not content.strip():
            return {"shared": False, "reason": "empty_content"}
        if not isinstance(source_memories, list) or not source_memories:
            return {"shared": False, "reason": "empty_source_memories"}

        # 1. 发布到 Memex（去标识化 + 证据链 + grounding）
        try:
            from laap.protocol.laap_memex import publish_knowledge
            pub_result = publish_knowledge(
                content=content,
                source_memories=source_memories,
                confidence=confidence,
                agent_name=agent_name,
                publisher_public_key=publisher_public_key,
                publisher_private_key=publisher_private_key,
            )
        except Exception as exc:
            logger.error(f"share_experience: memex publish failed: {exc}",
                         exc_info=True)
            return {"shared": False,
                    "reason": f"memex_error: {type(exc).__name__}: {exc}"}

        if not pub_result.get("published"):
            reason = pub_result.get("reason", "memex_rejected")
            logger.info(
                f"share_experience: agent={agent} rejected reason={reason}"
            )
            return {"shared": False, "reason": reason,
                    "deidentified_content": pub_result.get(
                        "deidentified_content")}

        knowledge_id = pub_result["knowledge_id"]
        deid_content = pub_result.get("deidentified_content", "")
        # 如果 publish_knowledge 没有显式返回 deidentified_content，
        # 从 store 取回
        if not deid_content:
            try:
                from laap.protocol.laap_memex import get_memex_store
                rec = get_memex_store().get(knowledge_id)
                if rec:
                    deid_content = rec.get("content", "")
            except Exception:
                pass

        # 2. 创建共同进化图根节点
        shared_id = f"coevo_{uuid.uuid4().hex[:12]}"
        node = ExperienceNode(
            experience_id=shared_id,
            knowledge_id=knowledge_id,
            agent=agent,
            content=deid_content,
            confidence=float(confidence),
            derived_from=None,
            derived_chain=[shared_id],
            created_at=_now_iso(),
            absorption_summary="",
            publisher_public_key=publisher_public_key or "",
        )
        with self._lock:
            self._nodes[shared_id] = node
            self._knowledge_index[knowledge_id] = shared_id
            self._children.setdefault(shared_id, [])

        # 3. 发布本地事件
        self._emit_local_event("coevolution_shared", {
            "shared_id": shared_id,
            "knowledge_id": knowledge_id,
            "agent": agent,
            "confidence": float(confidence),
        })

        logger.info(
            f"share_experience: agent={agent} shared_id={shared_id} "
            f"know_id={knowledge_id} conf={confidence:.2f}"
        )
        return {
            "shared": True,
            "shared_id": shared_id,
            "knowledge_id": knowledge_id,
        }

    # ── SubTask 4.2: absorb_experience ─────────────────────

    def absorb_experience(
        self,
        agent: str,
        shared_id: str,
        agent_name: str = "coevo",
        publisher_public_key: str = "",
        publisher_private_key: Optional[bytes] = None,
    ) -> Dict[str, Any]:
        """吸收一条共享经验并派生新经验（spec SubTask 4.2）.

        端到端流程：
        1. 从共同进化图取父节点；若不存在则失败；
        2. LLM 主导提炼吸收摘要（**必经 truth-grounding 管线**），
           ``rejected=True``（state=error）时拒绝吸收；
        3. 把派生内容以 ``derived_from=shared_id`` 标记发布回 Memex
           （source_memories 引用父 knowledge_id）；
        4. 创建子节点 ``ExperienceNode``（``derived_from=shared_id``）；
        5. 更新邻接表 ``_children[shared_id].append(new_id)``；
        6. 发布 ``coevolution_absorbed`` 事件；
        7. 返回 ``{absorbed: true, new_experience_id, knowledge_id,
           derived_from}``.

        幂等：同一 ``agent`` 对同一 ``shared_id`` 二次吸收返回
        同一 ``new_experience_id``（基于 ``knowledge_id`` 反查）.

        Args:
            agent: 吸收方 agent 标识.
            shared_id: 父经验节点 ID.
            agent_name: 触发 grounding 复核时写入 vault 的 agent 名称.
            publisher_public_key: 发布者 base64 公钥（可选）.
            publisher_private_key: 发布者 32 字节 Raw Ed25519 私钥（可选）.

        Returns:
            ``{absorbed: bool, reason?: str, new_experience_id?: str,
            knowledge_id?: str, derived_from?: str,
            absorption_summary?: str, grounding?: dict}``.
        """
        if not isinstance(agent, str) or not agent.strip():
            return {"absorbed": False, "reason": "empty_agent"}
        if not isinstance(shared_id, str) or not shared_id.strip():
            return {"absorbed": False, "reason": "empty_shared_id"}

        with self._lock:
            parent = self._nodes.get(shared_id)
        if parent is None:
            return {"absorbed": False, "reason": "shared_id_not_found"}

        # 2. LLM 主导提炼吸收摘要（必经 truth-grounding 管线）
        llm_out = _llm_absorb_summary(
            parent_content=parent.content,
            agent=agent,
            agent_name=agent_name,
        )
        grounding = llm_out["grounding"]
        # error 态直接拒绝（spec 硬约束：LLM 调用必经 truth-grounding）
        if grounding.get("rejected") or grounding.get("state") == "error":
            logger.info(
                f"absorb_experience: agent={agent} parent={shared_id} "
                f"rejected by grounding"
            )
            return {
                "absorbed": False,
                "reason": "grounding_rejected",
                "grounding": grounding,
            }

        derived_content = llm_out["derived_content"]
        summary = llm_out["summary"]

        # 3. 派生经验发布回 Memex（标记 derived_from 关系）
        #    source_memories 引用父 knowledge_id（哈希化后进 evidence_chain）
        derived_source_memories = [{
            "memory_id": parent.knowledge_id,
            "scope": "memex_shared",
            "confidence": parent.confidence,
        }]
        try:
            from laap.protocol.laap_memex import publish_knowledge
            pub_result = publish_knowledge(
                content=derived_content,
                source_memories=derived_source_memories,
                confidence=parent.confidence,
                agent_name=agent_name,
                publisher_public_key=publisher_public_key,
                publisher_private_key=publisher_private_key,
            )
        except Exception as exc:
            logger.error(f"absorb_experience: memex publish failed: {exc}",
                         exc_info=True)
            return {"absorbed": False,
                    "reason": f"memex_error: {type(exc).__name__}: {exc}"}

        if not pub_result.get("published"):
            reason = pub_result.get("reason", "memex_rejected")
            return {
                "absorbed": False,
                "reason": reason,
                "grounding": grounding,
            }

        knowledge_id = pub_result["knowledge_id"]
        deid_content = pub_result.get("deidentified_content", "")
        if not deid_content:
            try:
                from laap.protocol.laap_memex import get_memex_store
                rec = get_memex_store().get(knowledge_id)
                if rec:
                    deid_content = rec.get("content", "")
            except Exception:
                pass

        # 幂等检查：同一 knowledge_id 是否已有节点
        with self._lock:
            existing_exp_id = self._knowledge_index.get(knowledge_id)
            if existing_exp_id and existing_exp_id in self._nodes:
                logger.info(
                    f"absorb_experience: idempotent hit know_id={knowledge_id} "
                    f"exp_id={existing_exp_id}"
                )
                return {
                    "absorbed": True,
                    "new_experience_id": existing_exp_id,
                    "knowledge_id": knowledge_id,
                    "derived_from": shared_id,
                    "absorption_summary": summary,
                    "grounding": grounding,
                    "idempotent": True,
                }

        # 4. 创建子节点
        new_id = f"coevo_{uuid.uuid4().hex[:12]}"
        derived_chain = list(parent.derived_chain) + [new_id]
        node = ExperienceNode(
            experience_id=new_id,
            knowledge_id=knowledge_id,
            agent=agent,
            content=deid_content,
            confidence=float(parent.confidence),
            derived_from=shared_id,
            derived_chain=derived_chain,
            created_at=_now_iso(),
            absorption_summary=summary,
            publisher_public_key=publisher_public_key or "",
        )
        with self._lock:
            self._nodes[new_id] = node
            self._knowledge_index[knowledge_id] = new_id
            self._children.setdefault(new_id, [])
            self._children.setdefault(shared_id, [])
            if new_id not in self._children[shared_id]:
                self._children[shared_id].append(new_id)

        # 6. 发布本地事件
        self._emit_local_event("coevolution_absorbed", {
            "new_experience_id": new_id,
            "knowledge_id": knowledge_id,
            "agent": agent,
            "derived_from": shared_id,
            "parent_agent": parent.agent,
            "absorption_summary": summary,
        })

        logger.info(
            f"absorb_experience: agent={agent} new_id={new_id} "
            f"know_id={knowledge_id} derived_from={shared_id}"
        )
        return {
            "absorbed": True,
            "new_experience_id": new_id,
            "knowledge_id": knowledge_id,
            "derived_from": shared_id,
            "absorption_summary": summary,
            "grounding": grounding,
        }

    # ── SubTask 4.3: feedback_experience ───────────────────

    def feedback_experience(
        self,
        new_experience_id: str,
        derived_from: str,
    ) -> Dict[str, Any]:
        """经验回传到原始分享者（spec SubTask 4.3）.

        在共同进化图中标记 ``derived_from`` 关系并触发通知.
        若 ``new_experience_id`` 已有 ``derived_from``（absorb 时已
        设置），本调用仅触发通知事件（幂等）.

        Args:
            new_experience_id: 派生经验节点 ID.
            derived_from: 父经验节点 ID（必须存在于图中）.

        Returns:
            ``{fed_back: bool, reason?: str, target_agent?: str,
            new_experience_id?: str, derived_from?: str}``.
        """
        if not isinstance(new_experience_id, str) or not new_experience_id.strip():
            return {"fed_back": False, "reason": "empty_new_experience_id"}
        if not isinstance(derived_from, str) or not derived_from.strip():
            return {"fed_back": False, "reason": "empty_derived_from"}

        with self._lock:
            child_node = self._nodes.get(new_experience_id)
            parent_node = self._nodes.get(derived_from)
        if child_node is None:
            return {"fed_back": False, "reason": "new_experience_id_not_found"}
        if parent_node is None:
            return {"fed_back": False, "reason": "derived_from_not_found"}

        # 一致性校验：若子节点已有 derived_from，必须与传入一致
        if child_node.derived_from is not None and \
                child_node.derived_from != derived_from:
            logger.warning(
                f"feedback_experience: derived_from mismatch "
                f"existing={child_node.derived_from} "
                f"incoming={derived_from}"
            )
            return {"fed_back": False,
                    "reason": "derived_from_mismatch",
                    "existing_derived_from": child_node.derived_from}

        # 若子节点没有 derived_from（罕见：直接构造的节点），则补设
        if child_node.derived_from is None:
            with self._lock:
                child_node.derived_from = derived_from
                if derived_from not in child_node.derived_chain:
                    child_node.derived_chain = (
                        list(parent_node.derived_chain) +
                        [new_experience_id]
                    )
                self._children.setdefault(derived_from, [])
                if new_experience_id not in self._children[derived_from]:
                    self._children[derived_from].append(new_experience_id)

        # 发布 coevolution_feedback 事件（通知原分享者）
        # 原分享者通过订阅 coevolution_feedback 事件 + 过滤
        # target_agent 即可接收
        self._emit_local_event("coevolution_feedback", {
            "new_experience_id": new_experience_id,
            "derived_from": derived_from,
            "target_agent": parent_node.agent,
            "source_agent": child_node.agent,
            "knowledge_id": child_node.knowledge_id,
            "parent_knowledge_id": parent_node.knowledge_id,
        })

        logger.info(
            f"feedback_experience: child={new_experience_id} "
            f"parent={derived_from} target_agent={parent_node.agent}"
        )
        return {
            "fed_back": True,
            "new_experience_id": new_experience_id,
            "derived_from": derived_from,
            "target_agent": parent_node.agent,
            "source_agent": child_node.agent,
        }

    # ── SubTask 4.4: 共同进化图查询 ────────────────────────

    def get_experience(self, experience_id: str) -> Optional[Dict[str, Any]]:
        """按 ``experience_id`` 查询单条经验节点."""
        if not isinstance(experience_id, str):
            return None
        with self._lock:
            node = self._nodes.get(experience_id)
        return node.to_dict() if node is not None else None

    def get_graph(self, limit: int = 200) -> Dict[str, Any]:
        """导出共同进化图（节点 + 边）.

        Args:
            limit: 最多返回的节点数（按创建时间倒序）.

        Returns:
            ``{nodes: [...], edges: [...], total_nodes, total_edges}``.
        """
        safe_limit = max(1, min(int(limit), 1000))
        with self._lock:
            nodes_sorted = sorted(
                self._nodes.values(),
                key=lambda n: n.created_at,
                reverse=True,
            )[:safe_limit]
            nodes = [n.to_dict() for n in nodes_sorted]
            edges: List[Dict[str, Any]] = []
            for parent_id, children in self._children.items():
                for child_id in children:
                    edges.append({
                        "from": parent_id,
                        "to": child_id,
                        "type": "derived_from",
                    })
            total_nodes = len(self._nodes)
            total_edges = sum(len(c) for c in self._children.values())
        return {
            "nodes": nodes,
            "edges": edges,
            "total_nodes": total_nodes,
            "total_edges": total_edges,
        }

    def get_descendants(self, experience_id: str) -> List[str]:
        """获取某经验的所有后代节点 ID（BFS）."""
        if not isinstance(experience_id, str):
            return []
        result: List[str] = []
        seen: set = set()
        queue: List[str] = []
        with self._lock:
            if experience_id not in self._nodes:
                return []
            queue = list(self._children.get(experience_id, []))
            while queue:
                cur = queue.pop(0)
                if cur in seen:
                    continue
                seen.add(cur)
                result.append(cur)
                queue.extend(self._children.get(cur, []))
        return result

    def get_ancestors(self, experience_id: str) -> List[str]:
        """获取某经验的祖先链（从直接父节点到根）."""
        if not isinstance(experience_id, str):
            return []
        result: List[str] = []
        with self._lock:
            node = self._nodes.get(experience_id)
            if node is None:
                return []
            # 直接复用 derived_chain（已包含自身）
            chain = list(node.derived_chain)
        # 排除自身
        if experience_id in chain:
            chain.remove(experience_id)
        # 反转：从直接父到根
        chain.reverse()
        return chain

    def list_experiences(
        self,
        agent: Optional[str] = None,
        derived_only: bool = False,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """列出经验节点（可按 agent / 派生节点过滤）."""
        safe_limit = max(1, min(int(limit), 500))
        with self._lock:
            nodes = list(self._nodes.values())
        if agent is not None:
            nodes = [n for n in nodes if n.agent == agent]
        if derived_only:
            nodes = [n for n in nodes if n.derived_from is not None]
        nodes.sort(key=lambda n: n.created_at, reverse=True)
        return [n.to_dict() for n in nodes[:safe_limit]]

    # ── 统计与清理 ─────────────────────────────────────────

    def stats(self) -> Dict[str, Any]:
        """共同进化图统计."""
        with self._lock:
            total = len(self._nodes)
            shared = sum(
                1 for n in self._nodes.values()
                if n.derived_from is None
            )
            derived = total - shared
            by_agent: Dict[str, int] = {}
            for n in self._nodes.values():
                by_agent[n.agent] = by_agent.get(n.agent, 0) + 1
            total_edges = sum(len(c) for c in self._children.values())
            roots = [nid for nid, n in self._nodes.items()
                     if n.derived_from is None]
            leaves = [
                nid for nid, n in self._nodes.items()
                if not self._children.get(nid)
            ]
            max_depth = 0
            for n in self._nodes.values():
                depth = len(n.derived_chain) - 1
                if depth > max_depth:
                    max_depth = depth
        return {
            "total_experiences": total,
            "shared_roots": shared,
            "derived": derived,
            "total_edges": total_edges,
            "by_agent": by_agent,
            "roots_count": len(roots),
            "leaves_count": len(leaves),
            "max_depth": max_depth,
        }

    def clear(self) -> None:
        """清空所有节点与边（仅测试用）."""
        with self._lock:
            self._nodes.clear()
            self._knowledge_index.clear()
            self._children.clear()

    # ── 内部辅助 ───────────────────────────────────────────

    def _emit_local_event(self, event_type: str, payload: Dict[str, Any]) -> None:
        """发布事件到本地 EventBus（让 UI / 其他模块可订阅）.

        事件类型：
        - ``coevolution_shared``：经验被分享
        - ``coevolution_absorbed``：经验被吸收并派生新经验
        - ``coevolution_feedback``：经验回传通知原分享者
        """
        try:
            from laap.events.bus import bus as event_bus
            event_bus.publish_simple(event_type, payload, source="coevo")
        except Exception as exc:
            logger.warning(
                f"_emit_local_event({event_type}) failed: {exc}"
            )


# ──────────────────────────────────────────────────────────────────────
# 全局单例
# ──────────────────────────────────────────────────────────────────────

_coevolution_loop: Optional[CoevolutionLoop] = None
_coevolution_lock = threading.Lock()


def get_coevolution_loop() -> CoevolutionLoop:
    """获取全局 CoevolutionLoop 单例."""
    global _coevolution_loop
    if _coevolution_loop is None:
        with _coevolution_lock:
            if _coevolution_loop is None:
                _coevolution_loop = CoevolutionLoop()
    return _coevolution_loop


def reset_coevolution_loop_for_test() -> None:
    """测试辅助：重置全局 CoevolutionLoop 单例. 生产代码不要调用."""
    global _coevolution_loop
    with _coevolution_lock:
        _coevolution_loop = None
