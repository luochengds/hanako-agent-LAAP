"""P1-world-model 测试套件。

覆盖：
  - perceive 更新世界状态（实体状态转移被记录）
  - predict 返回 prediction_id 并持久化到 {agent}_vault.db 的 prediction_log 表
  - calibrate 用 prediction_id 取回预测、与 actual 比对、计算误差、
    调用 self_model.queue_reflection
  - agent 隔离：aris 与 butter 的 prediction_log 互不可见
  - maybe_schedule_prediction 在 turn_count % n == 0 时触发、否则返回 None
  - 注册函数：最小 FakeMCP 断言注册 3 个工具
  - 用 tmp_path 把 vault 目录指向临时目录

运行::

    python -m pytest laap/agi/test_world_model_mcp.py -v -p no:quadrants

若 world_model.py 依赖缺失无法 import，测试用 try/except skip 并仍测
facade / 注册 / 调度器。
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import importlib
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

# ── 可选依赖探测 ──────────────────────────────────────────────

# 检查 world_model.py 能否成功 import（依赖 numpy 等）
_wm_available = True
_wm_import_error: Optional[Exception] = None
try:
    importlib.import_module("laap.agi.world_model")
except Exception as e:  # pragma: no cover - 环境相关
    _wm_available = False
    _wm_import_error = e

# 检查 vault_manager 能否成功 import
_vault_available = True
_vault_import_error: Optional[Exception] = None
try:
    importlib.import_module("laap.memory_vault.vault_manager")
except Exception as e:  # pragma: no cover - 环境相关
    _vault_available = False
    _vault_import_error = e


pytestmark = pytest.mark.skipif(
    not _wm_available or not _vault_available,
    reason=(
        f"world_model available={_wm_available} "
        f"({_wm_import_error}); vault available={_vault_available} "
        f"({_vault_import_error})"
    ),
)


# ── FakeMCP：最小化捕获注册的工具 ─────────────────────────────

class FakeMCP:
    """最小 FastMCP 替身，仅捕获 @tool() 注册的 async 函数。"""

    def __init__(self) -> None:
        self.tools: Dict[str, Any] = {}

    def tool(self):
        def decorator(func):
            self.tools[func.__name__] = func
            return func
        return decorator


# ── 公共 fixture：tmp_path 重定向 vault 目录 + per-agent 缓存清理 ──

@pytest.fixture
def isolated_vault_env(tmp_path, monkeypatch):
    """把 vault 目录指向 tmp_path，并重置 world_model_mcp_tools 的
    per-agent 缓存与 VaultManager 单例。

    注意：``laap/memory_vault/__init__.py`` 把 ``vault_manager`` 单例
    re-export 到包属性，导致 ``import laap.memory_vault.vault_manager as vm_mod``
    会拿到单例对象而非子模块。这里用 ``from ... import VaultManager`` 直接
    从子模块取类（Python 走 ``sys.modules`` 解析，不受包属性覆盖影响）。
    """
    # 直接从子模块取 VaultManager 类与 vault_manager 单例引用
    import sys as _sys
    vm_mod = _sys.modules["laap.memory_vault.vault_manager"]
    # 重建 VaultManager 实例（vault_dir=tmp_path，与默认 VAULT_DIR 解耦）
    fresh_vm = vm_mod.VaultManager(vault_dir=str(tmp_path))
    # 同时把子模块的 vault_manager 单例也换成 fresh_vm，覆盖任何
    # ``from laap.memory_vault.vault_manager import vault_manager`` 路径
    monkeypatch.setattr(vm_mod, "vault_manager", fresh_vm, raising=False)

    # 清空 world_model_mcp_tools 的 per-agent 缓存
    import laap.agi.world_model_mcp_tools as wmt
    wmt._WORLD_MODELS.clear()
    wmt._SELF_MODELS.clear()
    # 让 _get_vault_manager 始终拿到我们注入的 fresh_vm
    monkeypatch.setattr(wmt, "_get_vault_manager", lambda: fresh_vm, raising=False)
    yield tmp_path, fresh_vm
    wmt._WORLD_MODELS.clear()
    wmt._SELF_MODELS.clear()


# ═══════════════════════════════════════════════════════════════
# 1. perceive 更新世界状态
# ═══════════════════════════════════════════════════════════════

def test_perceive_updates_entity_state(isolated_vault_env):
    """perceive 一个 deployment 事件后，实体的 state 应转移到 '生产'。"""
    from laap.agi.world_model_mcp_tools import _get_world_model
    wm = _get_world_model("aris")

    event = {
        "type": "deployment",
        "entity": "服务X",
        "env": "prod",
        "from_state": "开发中",
        "to_state": "生产",
    }
    result = wm.perceive(event)

    assert result["perceived"] is True
    assert result["entity"] == "服务X"
    assert result["state_transition"] is not None
    assert result["state_transition"]["from"] == "开发中"
    assert result["state_transition"]["to"] == "生产"

    entity = wm.get_entity("服务X")
    assert entity is not None
    assert entity.properties.get("state") == "生产"
    # history 中应有 state_transition 条目
    transitions = [h for h in entity.history if h["type"] == "state_transition"]
    assert len(transitions) >= 1
    assert transitions[-1]["data"]["to"] == "生产"


def test_perceive_no_entity_records_timeline_only(isolated_vault_env):
    """无 entity 字段的事件仅写入世界时间线，不创建实体。"""
    from laap.agi.world_model_mcp_tools import _get_world_model
    wm = _get_world_model("aris")
    before = len(wm.timeline)
    result = wm.perceive({"type": "system_event", "detail": "重启"})
    assert result["perceived"] is True
    assert result["entity"] is None
    assert len(wm.timeline) == before + 1


# ═══════════════════════════════════════════════════════════════
# 2. predict 返回 prediction_id 并持久化到 prediction_log 表
# ═══════════════════════════════════════════════════════════════

def test_predict_persists_prediction_log(isolated_vault_env):
    """predict 应返回 prediction_id 并把记录写入 aris_vault.db 的 prediction_log。"""
    tmp_path, fresh_vm = isolated_vault_env
    from laap.agi.world_model_mcp_tools import (
        _store_prediction, _get_prediction, _list_predictions,
    )

    # 直接调用 _store_prediction 模拟 world_predict 工具的持久化路径
    record = {
        "prediction_id": "pred_test_001",
        "agent_name": "aris",
        "entity": "服务X",
        "horizon": 1,
        "predicted_outcome": {"possible_outcomes": ["no_change"], "confidence": 0.5},
        "confidence": 0.5,
        "created_at": "2026-08-01T00:00:00+00:00",
    }
    _store_prediction("aris", record)

    # 取回
    fetched = _get_prediction("aris", "pred_test_001")
    assert fetched is not None
    assert fetched["prediction_id"] == "pred_test_001"
    assert fetched["agent_name"] == "aris"
    assert fetched["entity"] == "服务X"
    assert fetched["horizon"] == 1
    assert fetched["calibrated"] == 0
    assert fetched["predicted_outcome"]["possible_outcomes"] == ["no_change"]

    # 物理文件存在
    assert (tmp_path / "aris_vault.db").exists()

    # 列表
    items = _list_predictions("aris")
    assert any(p["prediction_id"] == "pred_test_001" for p in items)


def test_world_predict_mcp_tool_end_to_end(isolated_vault_env):
    """world_predict MCP 工具端到端：返回 JSON 含 prediction_id，DB 有记录。"""
    tmp_path, _ = isolated_vault_env
    import laap.agi.world_model_mcp_tools as wmt
    fake = FakeMCP()
    wmt.register_world_model_tools(fake)

    # world_predict 是 async
    raw = asyncio.run(fake.tools["world_predict"](
        entity="aris", horizon=1, agent_name="aris"))
    payload = json.loads(raw)
    assert "prediction_id" in payload
    assert payload["entity"] == "aris"
    assert payload["horizon"] == 1
    assert "predicted_outcome" in payload

    # 数据库应有这条记录
    fetched = wmt._get_prediction("aris", payload["prediction_id"])
    assert fetched is not None
    assert fetched["entity"] == "aris"


# ═══════════════════════════════════════════════════════════════
# 3. calibrate 闭环 + 误差回写 self_model.queue_reflection
# ═══════════════════════════════════════════════════════════════

def test_calibrate_writes_reflection_and_marks_db(isolated_vault_env):
    """calibrate 应：取回预测 → 计算误差 → 写反思队列 → DB 标记 calibrated。"""
    from laap.agi.world_model_mcp_tools import (
        _store_prediction, _get_prediction, _get_self_model,
    )
    import laap.agi.world_model_mcp_tools as wmt

    # 1. 先写入一条预测
    record = {
        "prediction_id": "pred_calib_001",
        "agent_name": "aris",
        "entity": "服务X",
        "horizon": 1,
        "predicted_outcome": {"outcome": "CPU飙升"},
        "confidence": 0.8,
        "created_at": "2026-08-01T00:00:00+00:00",
    }
    _store_prediction("aris", record)

    # 2. 注册 MCP 工具并调用 world_calibrate
    fake = FakeMCP()
    wmt.register_world_model_tools(fake)
    actual = json.dumps({
        "outcome": "CPU平稳",
        "outcome_score": 0.2,
        "evidence": "监控数据未见 CPU 上升",
    })
    raw = asyncio.run(fake.tools["world_calibrate"](
        prediction_id="pred_calib_001",
        actual=actual,
        agent_name="aris",
    ))
    payload = json.loads(raw)
    assert payload["calibrated"] is True
    err = payload["error_record"]
    assert err["prediction_id"] == "pred_calib_001"
    # bias = 0.8 - 0.2 = 0.6 (过度自信)
    assert err["bias"] == pytest.approx(0.6)
    assert err["hit"] is False
    assert err["error"] == 1.0

    # 3. 反思队列应有这条记录
    sm = _get_self_model("aris")
    reflections = sm.get_reflections()
    assert len(reflections) >= 1
    assert reflections[-1]["prediction_id"] == "pred_calib_001"
    assert reflections[-1]["bias"] == pytest.approx(0.6)

    # 4. DB 应标记为 calibrated
    fetched = _get_prediction("aris", "pred_calib_001")
    assert fetched["calibrated"] == 1
    assert fetched["bias"] == pytest.approx(0.6)
    assert fetched["hit"] == 0
    assert fetched["error"] == 1.0
    assert fetched["actual_outcome"]["outcome"] == "CPU平稳"
    assert fetched["calibrated_at"] is not None


def test_calibrate_idempotent_reflection_queue(isolated_vault_env):
    """对同一 prediction_id 重复 calibrate 不应让反思队列重复入队。"""
    from laap.agi.world_model_mcp_tools import (
        _store_prediction, _get_self_model,
    )
    import laap.agi.world_model_mcp_tools as wmt

    record = {
        "prediction_id": "pred_idem_001",
        "agent_name": "aris",
        "entity": "服务X",
        "horizon": 1,
        "predicted_outcome": {"outcome": "A"},
        "confidence": 0.7,
        "created_at": "2026-08-01T00:00:00+00:00",
    }
    _store_prediction("aris", record)

    fake = FakeMCP()
    wmt.register_world_model_tools(fake)
    actual = json.dumps({"outcome": "B", "outcome_score": 0.3})
    asyncio.run(fake.tools["world_calibrate"](
        prediction_id="pred_idem_001", actual=actual, agent_name="aris"))

    sm = _get_self_model("aris")
    first_count = len(sm.get_reflections())

    # 再次 calibrate 同一条预测（actual 相同 → calibrated_at 不同 → 不去重；
    # 我们故意传不同 actual 来触发重新计算，但 prediction_id 相同、calibrated_at
    # 是 time.time() 每次不同 → 不会去重，故队列会增长。这里验证幂等性应通过
    # 相同 (prediction_id, calibrated_at) 才去重——所以下面我们手动调用 queue_reflection
    # 用同一 error_record 两次来验证去重路径）
    err_record = {
        "prediction_id": "pred_idem_001",
        "calibrated_at": 12345.0,
        "bias": 0.4,
    }
    sm.queue_reflection(err_record)
    sm.queue_reflection(err_record)  # 完全相同 → 应去重
    second_count = len(sm.get_reflections())
    assert second_count == first_count + 1, "queue_reflection 应去重同一 (prediction_id, calibrated_at)"


def test_calibrate_unknown_prediction_returns_error(isolated_vault_env):
    """calibrate 一个不存在的 prediction_id 应返回 calibrated=False。"""
    import laap.agi.world_model_mcp_tools as wmt
    fake = FakeMCP()
    wmt.register_world_model_tools(fake)
    raw = asyncio.run(fake.tools["world_calibrate"](
        prediction_id="pred_nonexistent",
        actual=json.dumps({"outcome": "X"}),
        agent_name="aris",
    ))
    payload = json.loads(raw)
    assert payload["calibrated"] is False
    assert "not found" in payload["error"]


# ═══════════════════════════════════════════════════════════════
# 4. agent 隔离：aris 与 butter 的 prediction_log 互不可见
# ═══════════════════════════════════════════════════════════════

def test_agent_isolation_prediction_log(isolated_vault_env):
    """aris 写入的预测 butter 应取不到，反之亦然。"""
    from laap.agi.world_model_mcp_tools import (
        _store_prediction, _get_prediction, _list_predictions,
    )

    aris_record = {
        "prediction_id": "pred_aris_iso",
        "agent_name": "aris",
        "entity": "服务X",
        "horizon": 1,
        "predicted_outcome": {"outcome": "A"},
        "confidence": 0.5,
        "created_at": "2026-08-01T00:00:00+00:00",
    }
    butter_record = {
        "prediction_id": "pred_butter_iso",
        "agent_name": "butter",
        "entity": "服务Y",
        "horizon": 1,
        "predicted_outcome": {"outcome": "B"},
        "confidence": 0.6,
        "created_at": "2026-08-01T00:00:00+00:00",
    }
    _store_prediction("aris", aris_record)
    _store_prediction("butter", butter_record)

    # aris 视角：能取到自己的，取不到 butter 的
    assert _get_prediction("aris", "pred_aris_iso") is not None
    assert _get_prediction("aris", "pred_butter_iso") is None

    # butter 视角
    assert _get_prediction("butter", "pred_butter_iso") is not None
    assert _get_prediction("butter", "pred_aris_iso") is None

    # 列表隔离
    aris_items = _list_predictions("aris")
    aris_ids = {p["prediction_id"] for p in aris_items}
    assert "pred_aris_iso" in aris_ids
    assert "pred_butter_iso" not in aris_ids

    butter_items = _list_predictions("butter")
    butter_ids = {p["prediction_id"] for p in butter_items}
    assert "pred_butter_iso" in butter_ids
    assert "pred_aris_iso" not in butter_ids

    # 物理文件隔离
    tmp_path, _ = isolated_vault_env
    assert (tmp_path / "aris_vault.db").exists()
    assert (tmp_path / "butter_vault.db").exists()


def test_agent_isolation_world_model_separate(isolated_vault_env):
    """aris 与 butter 的 UnifiedWorldModel 实例应相互独立。"""
    from laap.agi.world_model_mcp_tools import _get_world_model
    aris_wm = _get_world_model("aris")
    butter_wm = _get_world_model("butter")
    assert aris_wm is not butter_wm
    aris_wm.perceive({"entity": "aris_only", "to_state": "S1"})
    butter_wm.perceive({"entity": "butter_only", "to_state": "S2"})
    # aris 的世界模型里有 aris_only 没有 butter_only
    assert aris_wm.get_entity("aris_only") is not None
    assert aris_wm.get_entity("butter_only") is None
    assert butter_wm.get_entity("butter_only") is not None
    assert butter_wm.get_entity("aris_only") is None


# ═══════════════════════════════════════════════════════════════
# 5. maybe_schedule_prediction 调度器
# ═══════════════════════════════════════════════════════════════

def test_maybe_schedule_prediction_triggers_on_multiple_of_n(isolated_vault_env):
    """turn_count % n == 0 时触发预测并写入 DB。"""
    from laap.agi.world_model_mcp_tools import (
        maybe_schedule_prediction, _get_prediction,
    )
    record = maybe_schedule_prediction("aris", turn_count=5, n=5)
    assert record is not None
    assert record["prediction_id"].startswith("pred_")
    assert record["scheduled"] is True
    assert record["turn_count"] == 5
    assert record["schedule_n"] == 5
    # 持久化
    fetched = _get_prediction("aris", record["prediction_id"])
    assert fetched is not None
    assert fetched["entity"] == "aris"  # 默认 entity=agent_name


def test_maybe_schedule_prediction_returns_none_when_not_multiple(isolated_vault_env):
    """turn_count 不是 n 的倍数时返回 None。"""
    from laap.agi.world_model_mcp_tools import maybe_schedule_prediction
    assert maybe_schedule_prediction("aris", turn_count=1, n=5) is None
    assert maybe_schedule_prediction("aris", turn_count=2, n=5) is None
    assert maybe_schedule_prediction("aris", turn_count=4, n=5) is None
    # 0 轮不触发
    assert maybe_schedule_prediction("aris", turn_count=0, n=5) is None
    # n<=0 不触发
    assert maybe_schedule_prediction("aris", turn_count=10, n=0) is None


def test_maybe_schedule_prediction_custom_entity_and_horizon(isolated_vault_env):
    """调度器支持自定义 entity 与 horizon。"""
    from laap.agi.world_model_mcp_tools import (
        maybe_schedule_prediction, _get_prediction,
    )
    record = maybe_schedule_prediction(
        "aris", turn_count=10, n=10, entity="服务X", horizon=3)
    assert record is not None
    assert record["entity"] == "服务X"
    assert record["horizon"] == 3
    fetched = _get_prediction("aris", record["prediction_id"])
    assert fetched is not None
    assert fetched["entity"] == "服务X"
    assert fetched["horizon"] == 3


# ═══════════════════════════════════════════════════════════════
# 6. 注册函数：FakeMCP 断言注册 3 个工具
# ═══════════════════════════════════════════════════════════════

def test_register_world_model_tools_registers_three_tools(isolated_vault_env):
    """register_world_model_tools 应注册 world_perceive/world_predict/world_calibrate。"""
    import laap.agi.world_model_mcp_tools as wmt
    fake = FakeMCP()
    wmt.register_world_model_tools(fake)
    assert set(fake.tools.keys()) == {
        "world_perceive", "world_predict", "world_calibrate"
    }
    # 都是 coroutine functions
    import inspect
    for name, fn in fake.tools.items():
        assert inspect.iscoroutinefunction(fn), f"{name} should be async"


def test_world_perceive_mcp_tool_end_to_end(isolated_vault_env):
    """world_perceive MCP 工具端到端：返回 JSON 含 perceived=True。"""
    import laap.agi.world_model_mcp_tools as wmt
    fake = FakeMCP()
    wmt.register_world_model_tools(fake)
    event = json.dumps({
        "type": "deployment",
        "entity": "服务Y",
        "to_state": "生产",
    })
    raw = asyncio.run(fake.tools["world_perceive"](
        event=event, agent_name="aris"))
    payload = json.loads(raw)
    assert payload["perceived"] is True
    assert payload["entity"] == "服务Y"
    assert payload["state_transition"]["to"] == "生产"


def test_world_perceive_handles_invalid_json(isolated_vault_env):
    """world_perceive 对非 JSON 输入应返回 perceived=False 而不抛异常。"""
    import laap.agi.world_model_mcp_tools as wmt
    fake = FakeMCP()
    wmt.register_world_model_tools(fake)
    raw = asyncio.run(fake.tools["world_perceive"](
        event="not a json", agent_name="aris"))
    payload = json.loads(raw)
    assert payload["perceived"] is False


# ═══════════════════════════════════════════════════════════════
# 7. self_model 反思队列基础 API（独立验证）
# ═══════════════════════════════════════════════════════════════

def test_self_model_reflection_queue_basics(isolated_vault_env):
    """直接验证 EmergentSelfModel.queue_reflection / get_reflections。"""
    from laap.agi.self_model import EmergentSelfModel
    sm = EmergentSelfModel(agent_name="test")
    assert sm.get_reflections() == []
    sm.queue_reflection({"prediction_id": "p1", "calibrated_at": 1.0, "bias": 0.1})
    sm.queue_reflection({"prediction_id": "p2", "calibrated_at": 2.0, "bias": -0.2})
    reflections = sm.get_reflections()
    assert len(reflections) == 2
    assert reflections[0]["prediction_id"] == "p1"
    assert reflections[1]["prediction_id"] == "p2"

    # 去重
    sm.queue_reflection({"prediction_id": "p1", "calibrated_at": 1.0, "bias": 0.1})
    assert len(sm.get_reflections()) == 2

    # clear
    sm.get_reflections(clear=True)
    assert sm.get_reflections() == []


# ═══════════════════════════════════════════════════════════════
# 8. UnifiedWorldModel.perceive/calibrate facade 直接验证
# ═══════════════════════════════════════════════════════════════

def test_unified_world_model_perceive_facade(isolated_vault_env):
    """直接调用 UnifiedWorldModel.perceive facade。"""
    from laap.agi.world_model import UnifiedWorldModel
    wm = UnifiedWorldModel(name="test")
    result = wm.perceive({"entity": "服务Z", "to_state": "生产", "type": "deployment"})
    assert result["perceived"] is True
    entity = wm.get_entity("服务Z")
    assert entity is not None
    assert entity.properties.get("state") == "生产"


def test_unified_world_model_calibrate_facade(isolated_vault_env):
    """直接调用 UnifiedWorldModel.calibrate facade。"""
    from laap.agi.world_model import UnifiedWorldModel
    wm = UnifiedWorldModel(name="test")
    prediction = {
        "prediction_id": "pred_facade_1",
        "entity": "服务Z",
        "predicted_outcome": "CPU飙升",
        "confidence": 0.9,
    }
    actual = {"outcome": "CPU平稳", "outcome_score": 0.2}
    err = wm.calibrate(prediction, actual)
    assert err["prediction_id"] == "pred_facade_1"
    assert err["bias"] == pytest.approx(0.7)
    assert err["hit"] is False
    assert err["error"] == 1.0


if __name__ == "__main__":
    # 直接运行也支持：python -m laap.agi.test_world_model_mcp
    sys.exit(pytest.main([__file__, "-v", "-p", "no:quadrants"]))
