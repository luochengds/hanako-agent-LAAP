"""
LAAP — Truth Grounding MCP Tools (防幻觉管线 MCP 工具集)

============================================================
  把 TruthGroundingEngine 的三态判定接入所有 LLM 输出路径
============================================================

本模块是 P1 任务 ``p1-truth-grounding`` 的核心交付物：为 MCP server、
sidecar HTTP 端点、aris-plugin、hanako/hub 路由提供一个统一的防幻觉
管线入口。

对外导出四个函数：

1. ``register_truth_grounding_tools(mcp_server)`` — 在 FastMCP server 上
   注册 ``truth_ground`` 工具，被 ``laap/mcp/server.py`` 集成；
2. ``extract_claims(text)`` — 启发式事实论断提取，供批量校验使用；
3. ``ground_text(text, context, agent_name)`` — 对一段文本中的所有论断
   逐条做三态判定，供 sidecar ``/truth/ground`` 端点调用；
4. ``ground_candidate_description(description, agent_name)`` — 对候选描述
   做单一判定，供 P1 rsi-sandbox 复用（本批次不实现 rsi-sandbox 本身）。

设计约束（硬性）：
* 不得 emoji；
* 幂等：重复对同一论断调用应得到一致结果，重复 error 回写不得污染
  元监控计数；
* 模板优先，不新增外部 LLM 依赖；
* lazy import：重型依赖（truth_grounding / error_reflection /
  meta_cognitive / vault_manager）仅在首次调用时导入；
* dataclass + type hints + docstring；
* 所有 MCP 工具入口返回 JSON 字符串。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger("laap.cognition.truth_grounding_mcp_tools")

# ──────────────────────────────────────────────────────────────────────
# 模块级单例缓存（lazy import + 幂等）
# ──────────────────────────────────────────────────────────────────────

_engine: Optional[Any] = None
_error_pipeline: Optional[Any] = None
_meta_cognitive: Optional[Any] = None
_vault_manager: Optional[Any] = None

# 已回写过的 error 事件 id 集合，避免 sidecar/hub 多路径重复触发回写
_corrected_claim_ids: set = set()


def _get_engine() -> Any:
    """Lazy 获取 TruthGroundingEngine 单例。"""
    global _engine
    if _engine is None:
        try:
            from laap.cognition.truth_grounding import TruthGroundingEngine
            _engine = TruthGroundingEngine()
        except Exception as exc:  # pragma: no cover - 依赖缺失分支
            logger.warning(f"TruthGroundingEngine 初始化失败: {exc}")
            _engine = None
    return _engine


def _get_error_pipeline() -> Any:
    """Lazy 获取 ErrorReflectionPipeline 单例（不接 LTM，避免回写副作用）。"""
    global _error_pipeline
    if _error_pipeline is None:
        try:
            from laap.cognition.error_reflection import ErrorReflectionPipeline
            _error_pipeline = ErrorReflectionPipeline(long_term_memory=None)
        except Exception as exc:  # pragma: no cover
            logger.warning(f"ErrorReflectionPipeline 初始化失败: {exc}")
            _error_pipeline = None
    return _error_pipeline


def _get_meta_cognitive() -> Any:
    """Lazy 获取 MetaCognitiveMonitor 单例。"""
    global _meta_cognitive
    if _meta_cognitive is None:
        try:
            from laap.agi.meta_cognitive import MetaCognitiveMonitor
            _meta_cognitive = MetaCognitiveMonitor()
        except Exception as exc:  # pragma: no cover
            logger.warning(f"MetaCognitiveMonitor 初始化失败: {exc}")
            _meta_cognitive = None
    return _meta_cognitive


def _get_vault_manager() -> Any:
    """Lazy 获取全局 vault_manager 单例。"""
    global _vault_manager
    if _vault_manager is None:
        try:
            from laap.memory_vault.vault_manager import vault_manager
            _vault_manager = vault_manager
        except Exception as exc:  # pragma: no cover
            logger.warning(f"vault_manager 导入失败: {exc}")
            _vault_manager = None
    return _vault_manager


def _reset_singletons_for_test() -> None:
    """测试辅助：重置所有模块级单例。生产代码不要调用。"""
    global _engine, _error_pipeline, _meta_cognitive, _vault_manager
    _engine = None
    _error_pipeline = None
    _meta_cognitive = None
    _vault_manager = None
    _corrected_claim_ids.clear()


# ──────────────────────────────────────────────────────────────────────
# 1. 启发式事实论断提取
# ──────────────────────────────────────────────────────────────────────

# 句子边界（中英文标点）
# 注意：英文句点用 ``\.\s+`` 匹配（句点+空白），避免把 "3.14" 这样的
# 小数切散；中文句号 ``。`` 直接作为单字符边界。
_SENTENCE_BOUNDARY = re.compile(r"[。！？!?；;\n]+|\.\s+")

# 事实论断信号词
_CLAIM_SIGNALS = (
    # 定义/等同
    "是", "等于", "定义为", "意味着", "表示", "是指",
    "means", "is", "are", "equals", "defined as", "refers to",
    # 断言/声明
    "声明", "断言", "确认", "认为", "声称", "指出", "说明",
    "stated", "claimed", "asserted", "confirmed", "believes",
    # 数值/量化
    "包含", "共有", "总计", "占比", "达到",
    "contains", "total", "amounts to", "reaches",
)

# 纯疑问/寒暄过滤
_NON_CLAIM_MARKERS = (
    "？", "?", "你好", "谢谢", "请问", "什么是", "如何", "怎么",
)


def extract_claims(text: str) -> List[str]:
    """启发式从文本中提取事实论断句子。

    模板优先：仅做正则分句 + 关键词过滤，不调用任何 LLM。

    提取规则：
    1. 按中英文句末标点（``。！？!?；;\\n`` 以及英文句点+空白
       ``\\.\\s+``，后者避免切散 ``3.14`` 这样的成绩）切句；
    2. 保留长度 ≥ 4 字符的句子；
    3. 过滤纯疑问句/寒暄（含 ``？`` ``?`` ``你好`` ``请问`` 等）；
    4. 保留含数字、或含定义/断言信号词的句子；
    5. 去重保序。

    Args:
        text: 待提取的文本。

    Returns:
        事实论断句子列表（保持原文顺序）。
    """
    if not text or not isinstance(text, str):
        return []

    # 切句
    raw_sentences = _SENTENCE_BOUNDARY.split(text)
    sentences = [s.strip() for s in raw_sentences if s and s.strip()]

    claims: List[str] = []
    seen = set()
    for sent in sentences:
        if len(sent) < 4:
            continue
        # 纯疑问/寒暄过滤
        if any(m in sent for m in _NON_CLAIM_MARKERS):
            continue
        # 信号判定：含数字 或 含定义/断言信号词
        has_digit = bool(re.search(r"\d", sent))
        has_signal = any(sig in sent.lower() for sig in _CLAIM_SIGNALS)
        if not (has_digit or has_signal):
            continue
        # 去重保序
        key = sent.strip()
        if key in seen:
            continue
        seen.add(key)
        claims.append(key)

    return claims


# ──────────────────────────────────────────────────────────────────────
# 2. 三态判定的统一内部入口
# ──────────────────────────────────────────────────────────────────────

def _ground_one(
    claim: str,
    context: Optional[str] = None,
) -> Dict[str, Any]:
    """对单条 claim 调 ground_three_state，失败时降级为 uncertain。

    本函数是所有外部入口（MCP / sidecar / rsi-sandbox）共享的内部入口，
    保证：
    * 任意异常都不向上抛，确保管线非阻塞；
    * 依赖缺失时返回 ``state=uncertain`` 而非报错。
    """
    engine = _get_engine()
    if engine is None:
        return {
            "state": "uncertain",
            "confidence": 0.0,
            "evidence": ["truth_grounding_engine_unavailable"],
        }
    try:
        result = engine.ground_three_state(claim, context=context)
        # 防御：确保返回 dict 形态合法
        if not isinstance(result, dict) or "state" not in result:
            return {
                "state": "uncertain",
                "confidence": 0.0,
                "evidence": ["invalid_ground_result"],
            }
        return result
    except Exception as exc:
        logger.warning(f"ground_three_state 异常: {exc}")
        return {
            "state": "uncertain",
            "confidence": 0.0,
            "evidence": [f"exception: {type(exc).__name__}"],
        }


def _write_back_error(
    claim: str,
    ground_result: Dict[str, Any],
    agent_name: str,
) -> None:
    """当三态判定命中 error 时，触发错误反思 + 元监控 + vault 回写。

    幂等：以 ``claim`` 的稳定哈希作为 ``correction_id``，重复调用同一
    claim 不会重复计数。
    """
    # 幂等键：基于 claim 文本的内容哈希
    correction_id = f"tg_{abs(hash(claim)) & 0xFFFFFFFFFFFFFFFF:x}"

    if correction_id in _corrected_claim_ids:
        return
    _corrected_claim_ids.add(correction_id)

    conflicts = list(ground_result.get("conflicts", []) or [])
    confidence = float(ground_result.get("confidence", 0.0))

    # 1) 错误反思管线
    error_pipeline = _get_error_pipeline()
    if error_pipeline is not None:
        try:
            error_record: Dict[str, Any] = {
                "query": claim,
                "wrong_answer": claim,
                "correct_answer": "",  # 未知正确答案，留空让 pipeline 推断
                "confidence": confidence,
                "source": "truth_grounding",
            }
            error_pipeline.reflect(error_record)
        except Exception as exc:
            logger.warning(f"ErrorReflectionPipeline.reflect 异常: {exc}")

    # 2) 元监控偏误计数
    meta_cognitive = _get_meta_cognitive()
    if meta_cognitive is not None:
        try:
            bias_type = "hallucination"
            if conflicts:
                # 取第一条冲突的前缀作为更细粒度的 bias_type
                first = conflicts[0]
                bias_type = first.split(":", 1)[0].strip() or "hallucination"
            meta_cognitive.record_bias_correction({
                "correction_id": correction_id,
                "bias_type": bias_type,
                "claim": claim,
                "conflicts": conflicts,
            })
        except Exception as exc:
            logger.warning(f"record_bias_correction 异常: {exc}")

    # 3) vault_manager 写入语义记忆
    vault_manager = _get_vault_manager()
    if vault_manager is not None:
        try:
            corrected_content = (
                f"[防幻觉校正] 论断: {claim[:200]}\n"
                f"冲突来源: {'; '.join(conflicts[:3]) or 'unknown'}\n"
                f"原置信度: {confidence:.3f}\n"
                f"校正建议: 该论断被判定为 error 态，需人工复核或重新生成。"
            )
            vault_manager.store(
                agent_name,
                "semantic",
                corrected_content,
                metadata={"correction": True, "source": "truth_grounding"},
            )
        except Exception as exc:
            logger.warning(f"vault_manager.store 异常: {exc}")


# ──────────────────────────────────────────────────────────────────────
# 3. 对外公开函数
# ──────────────────────────────────────────────────────────────────────

def ground_text(
    text: str,
    context: Optional[str] = None,
    agent_name: str = "aris",
) -> List[Dict[str, Any]]:
    """对一段文本中的所有事实论断逐条做三态判定。

    流程：
    1. ``extract_claims(text)`` 提取论断；
    2. 对每条 claim 调 ``_ground_one``，得到 ``{state, confidence,
       evidence, conflicts?}``；
    3. 命中 ``error`` 态的 claim 触发 ``_write_back_error``。

    Args:
        text: 待校验的文本。
        context: 可选上下文，仅参与启发式冲突检测。
        agent_name: 触发校正时写入 vault 的 agent 名称。

    Returns:
        每条 claim 的判定结果列表（顺序与提取顺序一致）。
    """
    claims = extract_claims(text)
    results: List[Dict[str, Any]] = []
    for claim in claims:
        result = _ground_one(claim, context=context)
        # 在结果中附带原 claim 文本，便于上游展示
        result_with_claim: Dict[str, Any] = {"claim": claim}
        result_with_claim.update(result)
        if result.get("state") == "error":
            _write_back_error(claim, result, agent_name=agent_name)
        results.append(result_with_claim)
    return results


def ground_candidate_description(
    description: str,
    agent_name: str = "aris",
) -> Dict[str, Any]:
    """对单一候选描述做三态判定，供 P1 rsi-sandbox 复用。

    与 ``ground_text`` 的区别：
    * 输入是单条描述而非多句文本，不会做 ``extract_claims`` 切句；
    * 返回结果额外带 ``rejected: bool`` 字段——当 ``state == "error"``
      时 ``rejected=True``，rsi-sandbox 可据此直接拒绝该候选。

    本批次仅交付本函数，不实现 rsi-sandbox 本身。

    Args:
        description: 候选描述文本。
        agent_name: 触发校正时写入 vault 的 agent 名称。

    Returns:
        ``{"state": str, "confidence": float, "evidence": List[str],
        "rejected": bool}``，``state == "error"`` 时额外带
        ``{"conflicts": List[str]}``。
    """
    result = _ground_one(description, context=None)
    rejected = result.get("state") == "error"
    out: Dict[str, Any] = {
        "state": result.get("state", "uncertain"),
        "confidence": float(result.get("confidence", 0.0)),
        "evidence": list(result.get("evidence", []) or []),
        "rejected": rejected,
    }
    if rejected:
        out["conflicts"] = list(result.get("conflicts", []) or [])
        _write_back_error(description, result, agent_name=agent_name)
    return out


# ──────────────────────────────────────────────────────────────────────
# 4. MCP 工具注册
# ──────────────────────────────────────────────────────────────────────

def register_truth_grounding_tools(mcp_server: Any) -> None:
    """在 FastMCP server 上注册防幻觉管线工具。

    注册的工具：

    * ``truth_ground(claim, context=None, agent_name="aris") -> str``

      对单条 claim 做三态判定，返回 JSON 字符串
      ``{"state": ..., "confidence": ..., "evidence": [...], "conflicts"?: [...]}``。
      ``state == "error"`` 时自动触发错误反思 + 元监控计数 + vault 语义记忆
      回写。

    幂等：本函数可被重复调用，但同一 ``mcp_server`` 上的同名工具只会注册
    一次（FastMCP 内部去重），不会产生重复 tool 注册错误。

    Args:
        mcp_server: FastMCP 实例（``laap/mcp/server.py`` 的 ``mcp`` 对象）。
    """
    if mcp_server is None:
        logger.warning("register_truth_grounding_tools: mcp_server is None")
        return

    @mcp_server.tool()
    async def truth_ground(
        claim: str,
        context: Optional[str] = None,
        agent_name: str = "aris",
    ) -> str:
        """对一条事实论断做防幻觉三态判定 (grounded/uncertain/error)。

        当判定为 error 时会自动触发错误反思管线、元监控偏误计数和
        vault 语义记忆回写，调用方只需关心返回的 state 字段。

        Args:
            claim: 待校验的事实论断。
            context: 可选上下文，参与启发式冲突检测。
            agent_name: 触发校正时写入 vault 的 agent 名称。

        Returns:
            JSON 字符串，字段：state / confidence / evidence / conflicts?
        """
        result = _ground_one(claim, context=context)
        if result.get("state") == "error":
            _write_back_error(claim, result, agent_name=agent_name)
        return json.dumps(result, ensure_ascii=False)

    logger.debug("truth_ground MCP 工具已注册")
    return None
