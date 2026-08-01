"""
LAAP — p1-truth-grounding 防幻觉管线集成测试

覆盖目标（P1 覆盖率 ≥ 70%）：
1. ``extract_claims`` 启发式论断提取；
2. ``ground_text`` 批量三态判定 + 错误回写；
3. ``ground_candidate_description`` 单一候选判定 + rejected 标志；
4. ``register_truth_grounding_tools`` MCP 工具注册与调用；
5. 真实 facade 方法 ``TruthGroundingEngine.ground_three_state`` /
   ``ErrorReflectionPipeline.reflect`` /
   ``MetaCognitiveMonitor.record_bias_correction`` (依赖缺失则 skip)；
6. 模拟四条接入路径：session / 频道 / DM / RSI；
7. 三态判定 (grounded / uncertain / error) 边界；
8. 错误回写幂等性。
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict, List, Optional

import pytest

# 确保项目根在 sys.path 上（部分环境 conftest 未覆盖到 cognition 子包）
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from laap.cognition import truth_grounding_mcp_tools as tg


# ──────────────────────────────────────────────────────────────────────
# 测试替身（Fakes）
# ──────────────────────────────────────────────────────────────────────

class FakeEngine:
    """可控的 TruthGroundingEngine 替身。

    通过 ``claim_map`` 把 claim 文本映射到预置的三态结果，便于测试
    grounded/uncertain/error 三种路径。未命中映射时返回 uncertain。
    """

    def __init__(self, claim_map: Optional[Dict[str, Dict[str, Any]]] = None):
        self.claim_map: Dict[str, Dict[str, Any]] = claim_map or {}
        self.calls: List[tuple] = []

    def ground_three_state(
        self,
        claim: str,
        context: Optional[str] = None,
    ) -> Dict[str, Any]:
        self.calls.append((claim, context))
        # 精确匹配优先，其次按子串匹配
        if claim in self.claim_map:
            result = dict(self.claim_map[claim])
            return result
        for key, val in self.claim_map.items():
            if key in claim or claim in key:
                return dict(val)
        return {
            "state": "uncertain",
            "confidence": 0.2,
            "evidence": ["fake_default"],
        }


class FakeErrorReflection:
    """ErrorReflectionPipeline 替身，记录 reflect 调用。"""

    def __init__(self):
        self.reflect_calls: List[Dict[str, Any]] = []

    def reflect(self, error_record: Dict[str, Any]) -> Dict[str, Any]:
        self.reflect_calls.append(dict(error_record))
        return {
            "frame_id": f"fake_frame_{len(self.reflect_calls)}",
            "memory_id": f"fake_mem_{len(self.reflect_calls)}",
            "root_cause": "factual_error",
            "gap_analysis": "fake gap",
            "fix_strategy": "fake fix",
            "calibration_weight": 0.6,
        }


class FakeMetaCognitive:
    """MetaCognitiveMonitor 替身，记录偏误校正，bias_count 可读。"""

    def __init__(self):
        self.corrections: List[Dict[str, Any]] = []
        self.biases_found = 0.0

    def record_bias_correction(self, record: Dict[str, Any]) -> None:
        # 模拟真实方法的幂等逻辑，便于测试
        cid = record.get("correction_id")
        if cid:
            for existing in self.corrections:
                if existing.get("correction_id") == cid:
                    return
        self.corrections.append(dict(record))
        self.biases_found += 1.0

    @property
    def bias_count(self) -> int:
        return len(self.corrections)


class FakeVaultManager:
    """VaultManager 替身，记录 store 调用。"""

    def __init__(self):
        self.store_calls: List[tuple] = []

    def store(
        self,
        agent_name: str,
        scope: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        self.store_calls.append((agent_name, scope, content, metadata))
        return {
            "stored": True,
            "memory_id": f"fake_vault_{len(self.store_calls)}",
            "scope": scope,
            "id": len(self.store_calls),
        }


class FakeMCP:
    """FastMCP 替身，记录 tool 注册并允许直接调用。"""

    def __init__(self):
        self.registered_tools: Dict[str, Any] = {}

    def tool(self):
        def decorator(func):
            name = func.__name__
            # 幂等：同名工具只注册一次
            if name not in self.registered_tools:
                self.registered_tools[name] = func
            return func
        return decorator


# ──────────────────────────────────────────────────────────────────────
# 公共 fixture
# ──────────────────────────────────────────────────────────────────────

@pytest.fixture
def fakes(monkeypatch):
    """安装一组可控替身到 truth_grounding_mcp_tools 的 lazy 入口。

    返回一个命名元组式 dict，含 engine/pipeline/meta/vault，便于断言。
    """
    engine = FakeEngine()
    pipeline = FakeErrorReflection()
    meta = FakeMetaCognitive()
    vault = FakeVaultManager()

    # 重置模块级单例 + 已回写 id 集合，确保每个测试干净
    tg._reset_singletons_for_test()

    monkeypatch.setattr(tg, "_get_engine", lambda: engine)
    monkeypatch.setattr(tg, "_get_error_pipeline", lambda: pipeline)
    monkeypatch.setattr(tg, "_get_meta_cognitive", lambda: meta)
    monkeypatch.setattr(tg, "_get_vault_manager", lambda: vault)

    return {
        "engine": engine,
        "pipeline": pipeline,
        "meta": meta,
        "vault": vault,
    }


# ──────────────────────────────────────────────────────────────────────
# 1. extract_claims 测试
# ──────────────────────────────────────────────────────────────────────

class TestExtractClaims:
    """启发式事实论断提取。"""

    def test_extracts_sentences_with_digits(self):
        text = "项目共有 3 个模块。你好世界。"
        claims = tg.extract_claims(text)
        assert "项目共有 3 个模块" in claims
        assert "你好世界" not in claims  # 无数字无信号词

    def test_extracts_sentences_with_definition_signals(self):
        text = "量子纠缠是一种物理现象。请问这是什么？"
        claims = tg.extract_claims(text)
        assert "量子纠缠是一种物理现象" in claims
        # 疑问句被过滤
        assert all("请问" not in c for c in claims)

    def test_filters_short_sentences(self):
        text = "是。对的。这条论断包含 5 个数据点。"
        claims = tg.extract_claims(text)
        assert "这条论断包含 5 个数据点" in claims
        assert all(len(c) >= 4 for c in claims)

    def test_dedupes_preserving_order(self):
        text = "结果是 42。结果是 42。另一条是 99。"
        claims = tg.extract_claims(text)
        # 去重保序
        assert claims.count("结果是 42") == 1
        assert "另一条是 99" in claims

    def test_handles_empty_and_non_string(self):
        assert tg.extract_claims("") == []
        assert tg.extract_claims(None) == []  # type: ignore[arg-type]

    def test_handles_english_claims(self):
        text = "The system contains 3 nodes. Hello there."
        claims = tg.extract_claims(text)
        # "The system contains 3 nodes" 含数字 + "contains" 信号词
        assert any("3 nodes" in c for c in claims)
        # "Hello there" 无数字无信号词，被过滤
        assert all("Hello there" not in c for c in claims)


# ──────────────────────────────────────────────────────────────────────
# 2. ground_text 测试
# ──────────────────────────────────────────────────────────────────────

class TestGroundText:
    """批量三态判定 + 错误回写。"""

    def test_returns_list_with_claim_field(self, fakes):
        fakes["engine"].claim_map = {
            "地球是圆的": {
                "state": "grounded",
                "confidence": 0.8,
                "evidence": ["天文观测"],
            }
        }
        results = tg.ground_text("地球是圆的。")
        assert len(results) == 1
        assert results[0]["claim"] == "地球是圆的"
        assert results[0]["state"] == "grounded"
        assert results[0]["confidence"] == 0.8

    def test_error_triggers_write_back(self, fakes):
        fakes["engine"].claim_map = {
            "1+1=3": {
                "state": "error",
                "confidence": 0.05,
                "evidence": [],
                "conflicts": ["known_false_fact: 1+1=3"],
            }
        }
        results = tg.ground_text("1+1=3。", agent_name="aris")
        assert results[0]["state"] == "error"
        # 三路回写均被触发
        assert len(fakes["pipeline"].reflect_calls) == 1
        assert fakes["meta"].bias_count == 1
        assert len(fakes["vault"].store_calls) == 1
        # vault 调用参数检查
        agent, scope, content, metadata = fakes["vault"].store_calls[0]
        assert agent == "aris"
        assert scope == "semantic"
        assert metadata["correction"] is True

    def test_non_error_does_not_trigger_write_back(self, fakes):
        fakes["engine"].claim_map = {
            "地球是圆的": {
                "state": "grounded",
                "confidence": 0.9,
                "evidence": ["天文观测"],
            }
        }
        tg.ground_text("地球是圆的。")
        assert fakes["pipeline"].reflect_calls == []
        assert fakes["meta"].bias_count == 0
        assert fakes["vault"].store_calls == []

    def test_multiple_claims_each_grounded(self, fakes):
        fakes["engine"].claim_map = {
            "地球是圆的": {"state": "grounded", "confidence": 0.8, "evidence": []},
        }
        # 另一条会走默认 uncertain 分支
        results = tg.ground_text("地球是圆的。某未知事物是某东西。")
        assert len(results) == 2
        assert results[0]["state"] == "grounded"
        assert results[1]["state"] == "uncertain"


# ──────────────────────────────────────────────────────────────────────
# 3. ground_candidate_description 测试
# ──────────────────────────────────────────────────────────────────────

class TestGroundCandidateDescription:
    """单一候选描述判定 + rejected 标志（RSI 路径入口）。"""

    def test_error_yields_rejected_true(self, fakes):
        fakes["engine"].claim_map = {
            "1+1=3": {
                "state": "error",
                "confidence": 0.0,
                "evidence": [],
                "conflicts": ["known_false_fact: 1+1=3"],
            }
        }
        result = tg.ground_candidate_description("1+1=3")
        assert result["state"] == "error"
        assert result["rejected"] is True
        assert "conflicts" in result
        # RSI 路径同样触发回写
        assert fakes["meta"].bias_count == 1
        assert len(fakes["vault"].store_calls) == 1

    def test_grounded_yields_rejected_false(self, fakes):
        fakes["engine"].claim_map = {
            "地球是圆的": {
                "state": "grounded",
                "confidence": 0.9,
                "evidence": ["天文观测"],
            }
        }
        result = tg.ground_candidate_description("地球是圆的")
        assert result["state"] == "grounded"
        assert result["rejected"] is False
        assert "conflicts" not in result

    def test_uncertain_yields_rejected_false(self, fakes):
        # 默认 FakeEngine 未命中映射返回 uncertain
        result = tg.ground_candidate_description("某条未知论断")
        assert result["state"] == "uncertain"
        assert result["rejected"] is False

    def test_result_shape(self, fakes):
        result = tg.ground_candidate_description("测试论断")
        assert set(result.keys()) >= {"state", "confidence", "evidence", "rejected"}
        assert isinstance(result["evidence"], list)
        assert isinstance(result["confidence"], float)


# ──────────────────────────────────────────────────────────────────────
# 4. register_truth_grounding_tools 测试
# ──────────────────────────────────────────────────────────────────────

class TestRegisterTruthGroundingTools:
    """MCP 工具注册。"""

    def test_registers_truth_ground_tool(self, fakes):
        mcp = FakeMCP()
        tg.register_truth_grounding_tools(mcp)
        assert "truth_ground" in mcp.registered_tools

    def test_none_mcp_is_safe(self, fakes):
        # 不应抛异常
        tg.register_truth_grounding_tools(None)

    def test_idempotent_registration(self, fakes):
        mcp = FakeMCP()
        tg.register_truth_grounding_tools(mcp)
        tg.register_truth_grounding_tools(mcp)
        assert len(mcp.registered_tools) == 1

    @pytest.mark.asyncio
    async def test_tool_returns_json_string(self, fakes):
        fakes["engine"].claim_map = {
            "地球是圆的": {
                "state": "grounded",
                "confidence": 0.8,
                "evidence": ["天文观测"],
            }
        }
        mcp = FakeMCP()
        tg.register_truth_grounding_tools(mcp)
        tool = mcp.registered_tools["truth_ground"]
        raw = await tool("地球是圆的")
        assert isinstance(raw, str)
        parsed = json.loads(raw)
        assert parsed["state"] == "grounded"
        assert parsed["confidence"] == 0.8

    @pytest.mark.asyncio
    async def test_tool_error_triggers_write_back(self, fakes):
        fakes["engine"].claim_map = {
            "1+1=3": {
                "state": "error",
                "confidence": 0.0,
                "evidence": [],
                "conflicts": ["known_false_fact: 1+1=3"],
            }
        }
        mcp = FakeMCP()
        tg.register_truth_grounding_tools(mcp)
        tool = mcp.registered_tools["truth_ground"]
        raw = await tool("1+1=3", agent_name="lorry")
        parsed = json.loads(raw)
        assert parsed["state"] == "error"
        assert "conflicts" in parsed
        assert fakes["meta"].bias_count == 1
        # agent_name 透传到 vault
        assert fakes["vault"].store_calls[0][0] == "lorry"


# ──────────────────────────────────────────────────────────────────────
# 5. 三态判定边界测试
# ──────────────────────────────────────────────────────────────────────

class TestThreeStateBoundaries:
    """grounded / uncertain / error 边界。"""

    def test_grounded_high_confidence(self, fakes):
        fakes["engine"].claim_map = {
            "x": {"state": "grounded", "confidence": 0.6, "evidence": []}
        }
        r = tg._ground_one("x")
        assert r["state"] == "grounded"

    def test_uncertain_low_confidence(self, fakes):
        fakes["engine"].claim_map = {
            "x": {"state": "uncertain", "confidence": 0.3, "evidence": []}
        }
        r = tg._ground_one("x")
        assert r["state"] == "uncertain"

    def test_error_state(self, fakes):
        fakes["engine"].claim_map = {
            "x": {
                "state": "error",
                "confidence": 0.0,
                "evidence": [],
                "conflicts": ["test"],
            }
        }
        r = tg._ground_one("x")
        assert r["state"] == "error"
        assert r["conflicts"] == ["test"]

    def test_engine_unavailable_returns_uncertain(self, monkeypatch):
        tg._reset_singletons_for_test()
        monkeypatch.setattr(tg, "_get_engine", lambda: None)
        r = tg._ground_one("任意论断")
        assert r["state"] == "uncertain"
        assert "truth_grounding_engine_unavailable" in r["evidence"]


# ──────────────────────────────────────────────────────────────────────
# 6. 幂等性测试
# ──────────────────────────────────────────────────────────────────────

class TestIdempotency:
    """错误回写幂等：同一 error claim 多次调用不重复计数。"""

    def test_duplicate_error_claim_not_double_counted(self, fakes):
        fakes["engine"].claim_map = {
            "1+1=3": {
                "state": "error",
                "confidence": 0.0,
                "evidence": [],
                "conflicts": ["known_false_fact: 1+1=3"],
            }
        }
        # 第一次调用
        tg.ground_text("1+1=3。", agent_name="aris")
        assert fakes["meta"].bias_count == 1
        assert len(fakes["vault"].store_calls) == 1
        # 第二次调用同一 claim
        tg.ground_text("1+1=3。", agent_name="aris")
        # 幂等：不重复计数
        assert fakes["meta"].bias_count == 1
        assert len(fakes["vault"].store_calls) == 1

    def test_different_error_claims_each_counted(self, fakes):
        fakes["engine"].claim_map = {
            "1+1=3": {
                "state": "error",
                "confidence": 0.0,
                "evidence": [],
                "conflicts": ["known_false_fact: 1+1=3"],
            },
            "2+2=5": {
                "state": "error",
                "confidence": 0.0,
                "evidence": [],
                "conflicts": ["known_false_fact: 2+2=5"],
            },
        }
        tg.ground_text("1+1=3。")
        tg.ground_text("2+2=5。")
        assert fakes["meta"].bias_count == 2
        assert len(fakes["vault"].store_calls) == 2


# ──────────────────────────────────────────────────────────────────────
# 7. 四路径集成模拟（session / 频道 / DM / RSI）
# ──────────────────────────────────────────────────────────────────────

class TestFourPathsIntegration:
    """模拟 aris-plugin / channel-router / dm-router / rsi-sandbox 四条
    接入路径。

    实际接入由 Integration Patch 在 sidecar.py / aris-plugin/index.js /
    hanako/hub/*.ts 中完成（本测试不依赖那些补丁，仅通过 Python 入口
    模拟等价调用）。
    """

    def test_session_path_via_ground_text(self, fakes):
        """session 路径：aris-plugin 调 sidecar /truth/ground → ground_text。"""
        fakes["engine"].claim_map = {
            "1+1=3": {
                "state": "error",
                "confidence": 0.0,
                "evidence": [],
                "conflicts": ["known_false_fact: 1+1=3"],
            }
        }
        # 模拟 sidecar 收到 POST /truth/ground {text: "1+1=3。"}
        results = tg.ground_text("1+1=3。", agent_name="aris")
        # sidecar 返回 {annotation: "[grounding: ...]", results: [...]}
        annotation = f"[grounding: {len(results)} claims, " \
                     f"{sum(1 for r in results if r['state']=='error')} error]"
        assert "error" in annotation
        assert results[0]["state"] == "error"
        # 回写发生
        assert fakes["meta"].bias_count == 1

    def test_channel_path_via_ground_text(self, fakes):
        """频道路径：channel-router 对 content 调 grounding → ground_text。"""
        fakes["engine"].claim_map = {
            "地球是圆的": {
                "state": "grounded",
                "confidence": 0.8,
                "evidence": ["天文观测"],
            }
        }
        # 模拟 channel-router 在 appendMessage 前对 content 做 grounding
        content = "地球是圆的。"
        results = tg.ground_text(content, agent_name="aris")
        annotation = f"[grounding: {len(results)} claims]"
        # annotation 会追加到 content 末尾（由 Integration Patch 完成）
        assert annotation
        assert results[0]["state"] == "grounded"
        # grounded 不触发回写
        assert fakes["meta"].bias_count == 0

    def test_dm_path_via_ground_text(self, fakes):
        """DM 路径：dm-router 对 cleanReply 调 grounding → ground_text。"""
        fakes["engine"].claim_map = {
            "1+1=3": {
                "state": "error",
                "confidence": 0.0,
                "evidence": [],
                "conflicts": ["known_false_fact: 1+1=3"],
            }
        }
        clean_reply = "我确认 1+1=3。"
        # 模拟 dm-router 对 cleanReply 做 grounding
        results = tg.ground_text(clean_reply, agent_name="aris")
        assert any(r["state"] == "error" for r in results)
        # annotation 追加到 cleanReply 末尾
        annotation = f"[grounding: {len(results)} claims, " \
                     f"{sum(1 for r in results if r['state']=='error')} error]"
        assert "error" in annotation
        assert fakes["meta"].bias_count == 1

    def test_rsi_path_via_ground_candidate_description(self, fakes):
        """RSI 路径：rsi-sandbox 调 ground_candidate_description 拒绝错误候选。"""
        fakes["engine"].claim_map = {
            "1+1=3": {
                "state": "error",
                "confidence": 0.0,
                "evidence": [],
                "conflicts": ["known_false_fact: 1+1=3"],
            },
            "地球是圆的": {
                "state": "grounded",
                "confidence": 0.8,
                "evidence": ["天文观测"],
            },
        }
        # 错误候选被拒绝
        bad = tg.ground_candidate_description("1+1=3")
        assert bad["rejected"] is True
        # 正确候选通过
        good = tg.ground_candidate_description("地球是圆的")
        assert good["rejected"] is False
        assert good["state"] == "grounded"


# ──────────────────────────────────────────────────────────────────────
# 8. 真实 facade 方法测试（依赖缺失则 skip）
# ──────────────────────────────────────────────────────────────────────

@pytest.fixture
def real_engine():
    """尝试构造真实 TruthGroundingEngine，依赖缺失则 skip。"""
    try:
        from laap.cognition.truth_grounding import TruthGroundingEngine
        return TruthGroundingEngine()
    except Exception as exc:
        pytest.skip(f"TruthGroundingEngine 依赖缺失: {exc}")


@pytest.fixture
def real_error_pipeline():
    try:
        from laap.cognition.error_reflection import ErrorReflectionPipeline
        return ErrorReflectionPipeline(long_term_memory=None)
    except Exception as exc:
        pytest.skip(f"ErrorReflectionPipeline 依赖缺失: {exc}")


@pytest.fixture
def real_meta_cognitive():
    try:
        from laap.agi.meta_cognitive import MetaCognitiveMonitor
        return MetaCognitiveMonitor()
    except Exception as exc:
        pytest.skip(f"MetaCognitiveMonitor 依赖缺失: {exc}")


class TestRealGroundThreeState:
    """真实 TruthGroundingEngine.ground_three_state facade。"""

    def test_returns_dict_with_required_fields(self, real_engine):
        result = real_engine.ground_three_state("什么是量子纠缠")
        assert isinstance(result, dict)
        assert "state" in result
        assert "confidence" in result
        assert "evidence" in result
        assert result["state"] in {"grounded", "uncertain", "error"}

    def test_known_false_fact_triggers_error(self, real_engine):
        result = real_engine.ground_three_state("1+1=3")
        assert result["state"] == "error"
        assert "conflicts" in result
        assert any("1+1=3" in c for c in result["conflicts"])

    def test_flat_earth_triggers_error(self, real_engine):
        result = real_engine.ground_three_state("地球是平的")
        assert result["state"] == "error"
        assert "conflicts" in result

    def test_absolute_claim_without_evidence_triggers_error(self, real_engine):
        # 含绝对化词汇且 ground() 无法给出已知证据
        result = real_engine.ground_three_state("绝对是某个虚构事物的真理")
        assert result["state"] == "error"
        assert any("absolute" in c for c in result["conflicts"])

    def test_normal_query_returns_uncertain_or_grounded(self, real_engine):
        # 未知概念应返回 uncertain（不会是 error，因为没有冲突信号）
        result = real_engine.ground_three_state("什么是量子纠缠")
        assert result["state"] in {"grounded", "uncertain"}

    def test_context_participates_in_heuristic(self, real_engine):
        # context 中包含已知伪事实也应触发 error
        result = real_engine.ground_three_state(
            "某条论断", context="背景：1+1=3"
        )
        assert result["state"] == "error"


class TestRealErrorReflectionReflect:
    """真实 ErrorReflectionPipeline.reflect facade。"""

    def test_reflect_returns_frame_metadata(self, real_error_pipeline):
        result = real_error_pipeline.reflect({
            "query": "1+1=?",
            "wrong_answer": "1+1=3",
            "correct_answer": "1+1=2",
            "confidence": 0.9,
            "source": "test",
        })
        assert "frame_id" in result
        assert "memory_id" in result
        assert "root_cause" in result
        assert "gap_analysis" in result
        assert "fix_strategy" in result

    def test_reflect_missing_fields_returns_error_envelope(self, real_error_pipeline):
        result = real_error_pipeline.reflect({"query": "", "wrong_answer": ""})
        assert "error" in result
        assert result["frame_id"] == ""
        assert result["memory_id"] == ""

    def test_reflect_with_reasoning_trace(self, real_error_pipeline):
        result = real_error_pipeline.reflect({
            "query": "测试查询",
            "wrong_answer": "错误答案",
            "correct_answer": "正确答案",
            "reasoning_trace": [
                {
                    "step": 1,
                    "description": "第一步",
                    "reasoning": "高置信推断",
                    "alternatives": [],
                    "chosen_direction": "方向A",
                    "confidence_at_step": 0.9,
                    "was_correct_branch": False,
                }
            ],
        })
        assert result["frame_id"]
        # 高置信错误分支应被归因为 overconfidence 或类似
        assert result["root_cause"]


class TestRealMetaCognitiveBiasCorrection:
    """真实 MetaCognitiveMonitor.record_bias_correction + bias_count。"""

    def test_record_increments_bias_count(self, real_meta_cognitive):
        initial = real_meta_cognitive.bias_count
        real_meta_cognitive.record_bias_correction({
            "bias_type": "hallucination",
            "claim": "1+1=3",
            "conflicts": ["known_false_fact: 1+1=3"],
        })
        assert real_meta_cognitive.bias_count == initial + 1

    def test_idempotent_with_correction_id(self, real_meta_cognitive):
        initial = real_meta_cognitive.bias_count
        record = {
            "correction_id": "tg_abc123",
            "bias_type": "hallucination",
            "claim": "1+1=3",
        }
        real_meta_cognitive.record_bias_correction(record)
        # 重复传入同 correction_id
        real_meta_cognitive.record_bias_correction(record)
        assert real_meta_cognitive.bias_count == initial + 1

    def test_different_correction_ids_each_counted(self, real_meta_cognitive):
        initial = real_meta_cognitive.bias_count
        real_meta_cognitive.record_bias_correction({
            "correction_id": "tg_a",
            "bias_type": "hallucination",
        })
        real_meta_cognitive.record_bias_correction({
            "correction_id": "tg_b",
            "bias_type": "known_false_fact",
        })
        assert real_meta_cognitive.bias_count == initial + 2

    def test_non_dict_record_is_safe(self, real_meta_cognitive):
        # 不应抛异常
        real_meta_cognitive.record_bias_correction(None)  # type: ignore[arg-type]
        real_meta_cognitive.record_bias_correction("not a dict")  # type: ignore[arg-type]

    def test_bias_count_property_idempotent(self, real_meta_cognitive):
        # 多次读取返回一致值
        v1 = real_meta_cognitive.bias_count
        v2 = real_meta_cognitive.bias_count
        assert v1 == v2

    def test_performance_metrics_biases_found_incremented(self, real_meta_cognitive):
        before = float(real_meta_cognitive.performance_metrics.get("biases_found", 0.0))
        real_meta_cognitive.record_bias_correction({
            "correction_id": "tg_metrics_test",
            "bias_type": "hallucination",
        })
        after = float(real_meta_cognitive.performance_metrics.get("biases_found", 0.0))
        assert after == before + 1.0
