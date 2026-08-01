"""测试 — 因果引擎 MCP 工具 (P1-causal-engine)

覆盖：
- CausalDiscovery.fit / QuantumCausalStore.infer / do_calculus facade 行为
- causal_learn 写入 {agent}_vault.db 的 causal_graph 表，可被 causal_query 读回
- agent 隔离：aris 与 butter 两个 vault 的图互不可见
- detect_causal_clues 检测含 cause/effect 元数据 / 箭头 / 中文模式的 content
- register_causal_tools 在 FakeMCP 上注册 3 个工具

运行方式：
    python -m pytest laap/agi/test_causal_mcp.py -v -p no:quadrants
"""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

# 把 laap 包根加入 sys.path（兼容仓库根直接运行）
_THIS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _THIS_DIR.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


# ─── 公共 fixture：把 vault 目录指向 tmp_path ─────────────────


@pytest.fixture
def isolated_vault(tmp_path, monkeypatch):
    """把 vault_manager 单例的 vault_dir 指向临时目录，避免污染真实 vault。

    每个测试函数获得独立的 tmp_path，确保 aris / butter 等测试 agent
    的 vault 文件互不干扰。
    """
    from laap.memory_vault.vault_manager import vault_manager

    # 替换单例对象的 vault_dir 与缓存，使后续 _get_vault / init_for_agent
    # 都在 tmp_path 下创建 vault 文件
    monkeypatch.setattr(vault_manager, "vault_dir", str(tmp_path))
    monkeypatch.setattr(vault_manager, "_vault_cache", {})
    return vault_manager


# ─── 1. CausalDiscovery.fit / do_calculus / infer facade 行为 ────


def test_causal_discovery_fit_basic():
    """CausalDiscovery.fit 接受 dict 列表并返回 edges_added / graph_version。"""
    from laap.agi.causal import CausalDiscovery
    cd = CausalDiscovery()
    obs = [
        {"cause": "熬夜", "effect": "bug", "confidence": 0.8},
        {"cause": "睡眠充足", "effect": "精力充沛", "confidence": 0.9},
    ]
    result = cd.fit(obs)
    assert result["edges_added"] == 2
    assert result["graph_version"].startswith("v")
    assert len(result["edges"]) == 2
    causes = {e["cause"] for e in result["edges"]}
    assert "熬夜" in causes and "睡眠充足" in causes


def test_causal_discovery_fit_idempotent():
    """重复 fit 同一 (cause, effect) 不重复计数，仅更新 confidence。"""
    from laap.agi.causal import CausalDiscovery
    cd = CausalDiscovery()
    obs = [{"cause": "X", "effect": "Y", "confidence": 0.6}]
    r1 = cd.fit(obs)
    assert r1["edges_added"] == 1
    r2 = cd.fit(obs)
    assert r2["edges_added"] == 0  # 已存在，不算新增
    assert len(r2["edges"]) == 1
    # 滚动平均： (0.6 + 0.6) / 2 = 0.6
    assert r2["edges"][0]["confidence"] == pytest.approx(0.6, abs=0.01)


def test_causal_discovery_fit_accepts_mixed_formats():
    """fit 接受 dict / tuple / 'cause->effect' 字符串三种格式。"""
    from laap.agi.causal import CausalDiscovery
    cd = CausalDiscovery()
    obs = [
        {"cause": "A", "effect": "B"},
        ("C", "D", 0.7),
        "E->F",
    ]
    r = cd.fit(obs)
    assert r["edges_added"] == 3
    pairs = {(e["cause"], e["effect"]) for e in r["edges"]}
    assert {("A", "B"), ("C", "D"), ("E", "F")} <= pairs


def test_quantum_causal_store_infer_with_string():
    """QuantumCausalStore.infer 接受字符串并返回结构化 dict。"""
    try:
        import numpy as np  # noqa: F401
    except ImportError:
        pytest.skip("numpy not available")
    from laap.agi.causal import QuantumCausalStore
    store = QuantumCausalStore(dim=32)
    # 没有学习过任何因果链，infer 应返回空 results
    result = store.infer("熬夜")
    assert result["mode"] == "quantum_infer"
    assert result["total_found"] == 0
    assert isinstance(result["results"], list)


def test_quantum_causal_store_infer_with_vector():
    """QuantumCausalStore.infer 接受 np.ndarray，先 learn 再 infer 应有结果。"""
    try:
        import numpy as np
    except ImportError:
        pytest.skip("numpy not available")
    from laap.agi.causal import QuantumCausalStore
    store = QuantumCausalStore(dim=32)
    cause = np.random.randn(32)
    effect = np.random.randn(32)
    store.learn(cause, effect, confidence=0.8, domain="test")
    result = store.infer(cause, top_k=3)
    assert result["total_found"] >= 1
    assert result["results"][0]["domain"] == "test"


def test_do_calculus_observe_mode():
    """do_calculus 在 do=False 时返回 observe 模式结果。"""
    try:
        import numpy as np  # noqa: F401
    except ImportError:
        pytest.skip("numpy not available")
    from laap.agi.causal import UnifiedCausalEngine, do_calculus
    engine = UnifiedCausalEngine()
    # 预先注入一些 bond
    engine.learn_bond("熬夜", "agent", "bug", matched=True, domain="test")
    result = do_calculus(engine, "熬夜", "bug", do=False)
    assert result["intervention"] == "observe(熬夜)"
    assert "reasoning_path" in result
    assert isinstance(result["reasoning_path"], list)
    assert "p_effect_given_do" in result


def test_do_calculus_do_mode_returns_structured():
    """do_calculus 在 do=True 时返回 do-演算结构。"""
    try:
        import numpy as np  # noqa: F401
    except ImportError:
        pytest.skip("numpy not available")
    from laap.agi.causal import UnifiedCausalEngine, do_calculus
    engine = UnifiedCausalEngine()
    engine.learn_bond("study", "exam", "pass", matched=True, domain="edu")
    engine.learn_entity_state("student", {"studied": False, "is_tired": False})
    result = do_calculus(engine, "studied", "exam", do=True)
    assert result["intervention"] == "do(studied=True)"
    assert "p_effect_given_do" in result
    assert "confidence" in result
    assert isinstance(result["reasoning_path"], list)
    assert len(result["reasoning_path"]) >= 1


# ─── 2. causal_graph 表写入与读回 ─────────────────────────────


def test_causal_graph_upsert_and_query(isolated_vault):
    """causal_graph_upsert_edge 写入后可被 causal_graph_query 读回。"""
    from laap.agi import causal_mcp_tools as tools
    tools._ENGINE_CACHE.pop("aris", None)
    tools._ENGINE_CACHE_TS.pop("aris", None)
    r = tools.causal_graph_upsert_edge(
        agent_name="aris",
        cause="熬夜",
        effect="bug",
        confidence=0.8,
        source="learn",
    )
    assert r["upserted"] is True
    assert r["cause"] == "熬夜"
    assert r["effect"] == "bug"
    edges = tools.causal_graph_query("aris")
    assert len(edges) == 1
    assert edges[0]["cause"] == "熬夜"
    assert edges[0]["effect"] == "bug"
    assert edges[0]["confidence"] == pytest.approx(0.8, abs=0.01)


def test_causal_graph_upsert_idempotent_increments_observations(isolated_vault):
    """同一 (cause, effect) 多次 upsert 只增加 observations 计数。"""
    from laap.agi import causal_mcp_tools as tools
    tools._ENGINE_CACHE.pop("aris", None)
    tools.causal_graph_upsert_edge("aris", "X", "Y", confidence=0.6)
    r2 = tools.causal_graph_upsert_edge("aris", "X", "Y", confidence=0.8)
    assert r2["observations"] == 2
    # 滚动平均: (0.6 + 0.8) / 2 = 0.7
    assert r2["confidence"] == pytest.approx(0.7, abs=0.01)
    edges = tools.causal_graph_query("aris")
    assert len(edges) == 1  # 仍然只有一条行


# ─── 3. agent 隔离 ────────────────────────────────────────────


def test_agent_isolation_aris_butter(isolated_vault):
    """aris vault 中的因果图不被 butter 查询到，反之亦然。"""
    from laap.agi import causal_mcp_tools as tools
    tools._ENGINE_CACHE.clear()
    tools._ENGINE_CACHE_TS.clear()
    tools.causal_graph_upsert_edge("aris", "熬夜", "bug", confidence=0.8)
    tools.causal_graph_upsert_edge("butter", "晴天", "好心情", confidence=0.9)

    aris_edges = tools.causal_graph_query("aris")
    butter_edges = tools.causal_graph_query("butter")

    aris_pairs = {(e["cause"], e["effect"]) for e in aris_edges}
    butter_pairs = {(e["cause"], e["effect"]) for e in butter_edges}
    assert ("熬夜", "bug") in aris_pairs
    assert ("熬夜", "bug") not in butter_pairs
    assert ("晴天", "好心情") in butter_pairs
    assert ("晴天", "好心情") not in aris_pairs


def test_agent_isolation_separate_db_files(isolated_vault, tmp_path):
    """aris 与 butter 各自拥有独立的 vault.db 文件。"""
    from laap.agi import causal_mcp_tools as tools
    tools._ENGINE_CACHE.clear()
    tools._ENGINE_CACHE_TS.clear()
    tools.causal_graph_upsert_edge("aris", "A", "B")
    tools.causal_graph_upsert_edge("butter", "C", "D")
    aris_db = tmp_path / "aris_vault.db"
    butter_db = tmp_path / "butter_vault.db"
    assert aris_db.exists()
    assert butter_db.exists()


# ─── 4. detect_causal_clues 检测 ──────────────────────────────


def test_detect_causal_clues_metadata():
    """metadata 显式声明 cause/effect 时被检测。"""
    from laap.agi.causal_mcp_tools import detect_causal_clues
    clues = detect_causal_clues(
        content="任意内容",
        metadata={"cause": "熬夜", "effect": "bug"},
    )
    assert len(clues) == 1
    assert clues[0]["cause"] == "熬夜"
    assert clues[0]["effect"] == "bug"
    assert clues[0]["source"] == "metadata"


def test_detect_causal_clues_arrow_pattern():
    """content 含 cause->effect 箭头被检测。"""
    from laap.agi.causal_mcp_tools import detect_causal_clues
    clues = detect_causal_clues(content="熬夜->bug 是常见现象")
    assert any(c["cause"] == "熬夜" and c["effect"] == "bug" for c in clues)


def test_detect_causal_clues_chinese_pattern():
    """content 含 '因为X所以Y' / 'X导致Y' 中文模式被检测。"""
    from laap.agi.causal_mcp_tools import detect_causal_clues
    clues1 = detect_causal_clues(content="因为熬夜所以出bug")
    assert any(c["cause"] == "熬夜" and c["effect"] == "出bug" for c in clues1)
    clues2 = detect_causal_clues(content="缺睡眠导致精力下降")
    assert any("睡眠" in c["cause"] and "精力" in c["effect"] for c in clues2)


def test_detect_causal_clues_no_clues():
    """无因果线索的 content 返回空列表。"""
    from laap.agi.causal_mcp_tools import detect_causal_clues
    clues = detect_causal_clues(content="今天天气不错，去散步了。")
    assert clues == []


def test_causal_learn_from_clues_writes_to_vault(isolated_vault):
    """causal_learn_from_clues 把检测到的线索写入 causal_graph 表。"""
    from laap.agi import causal_mcp_tools as tools
    tools._ENGINE_CACHE.pop("aris", None)
    tools._ENGINE_CACHE_TS.pop("aris", None)
    result = tools.causal_learn_from_clues(
        agent_name="aris",
        content="熬夜->bug",
        metadata={"cause": "缺睡眠", "effect": "效率低"},
    )
    assert result["clues_detected"] >= 2
    assert result["edges_upserted"] >= 2
    edges = tools.causal_graph_query("aris")
    pairs = {(e["cause"], e["effect"]) for e in edges}
    assert ("熬夜", "bug") in pairs
    assert ("缺睡眠", "效率低") in pairs


# ─── 5. register_causal_tools 注册 3 个工具 ────────────────────


class FakeMCP:
    """最小 FastMCP 替身：记录被 @tool() 装饰的函数名。"""

    def __init__(self):
        self.registered_tools: Dict[str, Any] = {}

    def tool(self):
        def decorator(fn):
            self.registered_tools[fn.__name__] = fn
            return fn
        return decorator


def test_register_causal_tools_registers_three():
    """register_causal_tools 在 FakeMCP 上注册 3 个工具函数。"""
    from laap.agi.causal_mcp_tools import register_causal_tools
    fake = FakeMCP()
    register_causal_tools(fake)
    assert set(fake.registered_tools.keys()) == {
        "causal_infer", "causal_query", "causal_learn",
    }


def test_causal_learn_tool_writes_to_vault(isolated_vault):
    """causal_learn MCP 工具接受 JSON 字符串并写入 causal_graph 表。"""
    from laap.agi.causal_mcp_tools import register_causal_tools
    fake = FakeMCP()
    register_causal_tools(fake)
    observations = json.dumps([
        {"cause": "熬夜", "effect": "bug", "confidence": 0.8},
        {"cause": "运动", "effect": "健康", "confidence": 0.9},
    ])
    result_str = asyncio.run(
        fake.registered_tools["causal_learn"](observations, agent_name="aris")
    )
    result = json.loads(result_str)
    assert result["edges_added"] == 2
    # 验证写入 vault
    from laap.agi import causal_mcp_tools as tools
    edges = tools.causal_graph_query("aris")
    pairs = {(e["cause"], e["effect"]) for e in edges}
    assert ("熬夜", "bug") in pairs
    assert ("运动", "健康") in pairs


def test_causal_query_tool_returns_edges(isolated_vault):
    """causal_query MCP 工具返回 agent 因果图的边。"""
    from laap.agi.causal_mcp_tools import register_causal_tools
    from laap.agi import causal_mcp_tools as tools
    tools._ENGINE_CACHE.clear()
    tools._ENGINE_CACHE_TS.clear()
    tools.causal_graph_upsert_edge("aris", "X", "Y", confidence=0.7)
    fake = FakeMCP()
    register_causal_tools(fake)
    result_str = asyncio.run(
        fake.registered_tools["causal_query"](agent_name="aris")
    )
    result = json.loads(result_str)
    assert result["agent_name"] == "aris"
    assert len(result["edges"]) == 1
    assert result["edges"][0]["cause"] == "X"
    assert result["stats"]["total_edges"] == 1


def test_causal_infer_tool_returns_structured(isolated_vault):
    """causal_infer MCP 工具返回结构化推理结果。"""
    from laap.agi.causal_mcp_tools import register_causal_tools
    fake = FakeMCP()
    register_causal_tools(fake)
    # observe 模式
    result_str = asyncio.run(
        fake.registered_tools["causal_infer"]("熬夜", "bug", do=False)
    )
    result = json.loads(result_str)
    assert result["cause"] == "熬夜"
    assert result["effect"] == "bug"
    assert result["do"] is False
    assert "p_effect_given_do" in result
    assert "reasoning_path" in result
    # do 模式
    result_str2 = asyncio.run(
        fake.registered_tools["causal_infer"]("study", "exam", do=True)
    )
    result2 = json.loads(result_str2)
    assert result2["intervention"] == "do(study=True)"


# ─── 6. MCP 工具与 memory_store 联动（线索检测） ──────────────


def test_memory_store_integration_via_clue_detection(isolated_vault):
    """模拟 memory_store 写入后调用 causal_learn_from_clues 的完整链路。"""
    from laap.agi import causal_mcp_tools as tools
    tools._ENGINE_CACHE.clear()
    tools._ENGINE_CACHE_TS.clear()
    # 模拟 memory_store 写入一条含因果线索的记忆
    content = "用户提到：熬夜->bug 是常见现象"
    metadata = {"scope": "episodic"}
    # 1) 检测线索
    clues = tools.detect_causal_clues(content, metadata)
    assert len(clues) >= 1
    # 2) 写入因果图
    learn_result = tools.causal_learn_from_clues("aris", content, metadata)
    assert learn_result["edges_upserted"] >= 1
    # 3) 因果图可被 query 读回
    edges = tools.causal_graph_query("aris")
    assert any(e["cause"] == "熬夜" and e["effect"] == "bug" for e in edges)


def test_memory_store_integration_no_clues_no_writes(isolated_vault):
    """memory_store 写入无线索内容时，不向因果图写入任何边。"""
    from laap.agi import causal_mcp_tools as tools
    tools._ENGINE_CACHE.clear()
    tools._ENGINE_CACHE_TS.clear()
    content = "今天天气真好，去散步了"
    result = tools.causal_learn_from_clues("aris", content, None)
    assert result["clues_detected"] == 0
    assert result["edges_upserted"] == 0
    edges = tools.causal_graph_query("aris")
    assert len(edges) == 0


# ─── 7. 因果图与 vault_manager 协同 ────────────────────────────


def test_causal_graph_table_in_agent_vault(isolated_vault, tmp_path):
    """causal_graph 表创建在 {agent}_vault.db 中。"""
    from laap.agi import causal_mcp_tools as tools
    from laap.memory_vault.vault_manager import _open_vault_connection, vault_manager
    tools._ENGINE_CACHE.clear()
    tools._ENGINE_CACHE_TS.clear()
    tools.causal_graph_upsert_edge("aris", "X", "Y")
    db_path, key_hex = vault_manager._get_vault("aris")
    # db_path 应在 tmp_path 下
    assert tmp_path in Path(db_path).parents or Path(db_path).parent == tmp_path
    conn = _open_vault_connection(db_path, key_hex)
    try:
        # 表存在
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='causal_graph'"
        ).fetchone()
        assert row is not None
        assert row["name"] == "causal_graph"
        # 行存在
        cnt = conn.execute("SELECT COUNT(*) as c FROM causal_graph").fetchone()["c"]
        assert cnt == 1
    finally:
        conn.close()


def test_causal_graph_stats(isolated_vault):
    """causal_graph_stats 返回正确的统计。"""
    from laap.agi import causal_mcp_tools as tools
    tools._ENGINE_CACHE.clear()
    tools._ENGINE_CACHE_TS.clear()
    tools.causal_graph_upsert_edge("aris", "A", "B", source="learn")
    tools.causal_graph_upsert_edge("aris", "C", "D", source="clue")
    stats = tools.causal_graph_stats("aris")
    assert stats["total_edges"] == 2
    assert stats["by_source"].get("learn") == 1
    assert stats["by_source"].get("clue") == 1


# ─── 8. causal.py 不可用时的优雅降级 ──────────────────────────


def test_causal_mcp_tools_import_safe():
    """causal_mcp_tools 模块自身可在不依赖 causal.py 的情况下 import。"""
    # 这个测试本身能跑通就说明 import 链没问题
    from laap.agi import causal_mcp_tools as tools
    assert hasattr(tools, "register_causal_tools")
    assert hasattr(tools, "detect_causal_clues")
    assert hasattr(tools, "causal_learn_from_clues")
    assert hasattr(tools, "causal_graph_upsert_edge")
    assert hasattr(tools, "causal_graph_query")


def test_causal_infer_handles_engine_unavailable(isolated_vault, monkeypatch):
    """当 UnifiedCausalEngine 不可用时 causal_infer 工具优雅返回错误。"""
    from laap.agi.causal_mcp_tools import register_causal_tools
    from laap.agi import causal_mcp_tools as tools

    # 强制 _get_engine_for_agent 返回 None
    def fake_get_engine(agent_name):
        return None
    monkeypatch.setattr(tools, "_get_engine_for_agent", fake_get_engine)

    fake = FakeMCP()
    register_causal_tools(fake)
    result_str = asyncio.run(
        fake.registered_tools["causal_infer"]("X", "Y", do=False)
    )
    result = json.loads(result_str)
    assert result["confidence"] == 0.0
    assert "engine unavailable" in result.get("reasoning_path", [""])[-1]


if __name__ == "__main__":
    # 直接运行：python -m laap.agi.test_causal_mcp
    sys.exit(pytest.main([__file__, "-v", "-p", "no:quadrants"]))
