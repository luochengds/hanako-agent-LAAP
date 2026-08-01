# -*- coding: utf-8 -*-
"""LAAP × SimWorld 集成模块的 smoke 测试.

Run:
    python -m laap.integrations.simworld.verify

10 项检查全部在 headless 模式下运行（使用 MockCommunicator，
不需要 UnrealCV / UE / SimWorld 完整环境）。Exit code 0 = 全部通过,
1 = 至少一项失败。每项检查打印 [PASS]/[FAIL] 与简短详情。

Check list:
    1.  laap.integrations.simworld 可导入（SimWorld 可选）
    2.  LAAPBrain 可实例化（用 MockCommunicator 上下文）
    3.  EventedCommunicator 可实例化（用 mock CognitiveBus）
    4.  MockCommunicator spawn / step_forward / rotate / get_position 流程
    5.  SimWorldBridge 双向同步（spawn_humanoid_in_laap + sync_world_to_laap
        + sync_laap_to_world）
    6.  LAAPBrain.generate_instructions 返回有效 JSON
    7.  actions.parse_simworld_state 解析正确
    8.  actions.candidate_actions 返回非空候选列表
    9.  actions.laap_decision_to_simworld_action 转换正确
    10. CognitiveBus 在 LAAPBrain 决策时被触发（PERCEPTION_INCOMING /
        ACTION_TAKEN 事件）
"""

from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

# 把 d:\LAAP 加入 sys.path，保证直接从仓库根运行时 `laap` 可导入
_LAAP_ROOT = Path(__file__).resolve().parents[3]
if str(_LAAP_ROOT) not in sys.path:
    sys.path.insert(0, str(_LAAP_ROOT))


def _ok(label: str, detail: str = "") -> bool:
    print(f"[PASS] {label}" + (f" — {detail}" if detail else ""))
    return True


def _fail(label: str, detail: str = "") -> bool:
    print(f"[FAIL] {label}" + (f" — {detail}" if detail else ""))
    return False


# ═══════════════════════════════════════════════════════════════
# 共享 fixture — 在多个检查之间复用
# ═══════════════════════════════════════════════════════════════

def _make_laap_stack():
    """构造 LAAP UnifiedCausalEngine + UnifiedWorldModel + CognitiveBus.

    任意一项不可用时返回 None，调用方需容错。
    """
    causal = None
    wm = None
    bus = None
    try:
        from laap.agi.causal import UnifiedCausalEngine
        causal = UnifiedCausalEngine()
    except Exception as e:
        print(f"  [note] UnifiedCausalEngine unavailable: {e}")
    try:
        from laap.agi.world_model import UnifiedWorldModel
        wm = UnifiedWorldModel()
    except Exception as e:
        print(f"  [note] UnifiedWorldModel unavailable: {e}")
    try:
        from laap.agi.cognitive_bus import CognitiveBus
        bus = CognitiveBus(agent_name="simworld_verify")
    except Exception as e:
        print(f"  [note] CognitiveBus unavailable: {e}")
    return causal, wm, bus


def _make_mock_communicator(cognitive_bus=None):
    """构造一个 MockCommunicator（仅依赖 numpy）."""
    from laap.integrations.simworld.communicator import MockCommunicator
    return MockCommunicator(cognitive_bus=cognitive_bus)


# ═══════════════════════════════════════════════════════════════
# 10 项检查
# ═══════════════════════════════════════════════════════════════

def check_simworld_integration_import() -> bool:
    """1. import simworld 集成模块可用（SimWorld 本身可选）."""
    try:
        from laap.integrations.simworld import (
            LAAPBrain, EventedCommunicator, MockCommunicator,
            SimWorldBridge, SimWorldConfig,
        )
        from laap.integrations.simworld import __version__
    except Exception as e:
        return _fail("Integration import", str(e))

    # SimWorld 本身是否可用（仅信息性，不影响通过）
    sw_available = False
    try:
        import simworld  # noqa: F401
        sw_available = True
    except Exception:
        sw_available = False

    detail = "exports LAAPBrain/EventedCommunicator/MockCommunicator/SimWorldBridge/SimWorldConfig v{0}; simworld={1}".format(
        __version__, "available" if sw_available else "fallback (mock-only)"
    )
    return _ok("Integration import", detail)


def check_laap_brain_init() -> bool:
    """2. LAAPBrain 可实例化（用 MockCommunicator 上下文）."""
    try:
        from laap.integrations.simworld import LAAPBrain
        causal, wm, bus = _make_laap_stack()
        brain = LAAPBrain(
            causal_engine=causal,
            world_model=wm,
            cognitive_bus=bus,
            llm_model_name="gpt-4o-mini",
            fallback_to_llm=True,
        )
    except Exception as e:
        return _fail("LAAPBrain init", str(e))

    stats = brain.stats()
    detail = "has_parent_llm={0}, has_causal={1}, has_wm={2}, has_bus={3}".format(
        stats["has_parent_llm"],
        stats["has_causal_engine"],
        stats["has_world_model"],
        stats["has_cognitive_bus"],
    )
    if not stats["has_parent_llm"]:
        # 预期情况：SimWorld A2ALLM 缺 openai 依赖时降级为 LAAP-only 模式
        detail += "; LAAP-only mode (parent LLM unavailable)"
    return _ok("LAAPBrain init", detail)


def check_evented_communicator_init() -> bool:
    """3. EventedCommunicator 可实例化（用 mock CognitiveBus）."""
    try:
        from laap.integrations.simworld import EventedCommunicator
        from laap.agi.cognitive_bus import CognitiveBus
        bus = CognitiveBus(agent_name="ec_verify")
        comm = EventedCommunicator(unrealcv=None, cognitive_bus=bus)
    except Exception as e:
        return _fail("EventedCommunicator init", str(e))

    # 验证关键属性存在
    has_bus = getattr(comm, "cognitive_bus", None) is bus
    has_lock = hasattr(comm, "_event_lock")
    has_prefix = getattr(comm, "event_prefix", "") == "simworld"
    detail = "cognitive_bus={0}, _event_lock={1}, event_prefix={2}".format(
        has_bus, has_lock, has_prefix
    )
    if not (has_bus and has_lock and has_prefix):
        return _fail("EventedCommunicator init", "attribute mismatch: " + detail)
    return _ok("EventedCommunicator init", detail)


def check_mock_communicator_spawn_move() -> bool:
    """4. MockCommunicator spawn / step_forward / rotate / get_position 流程."""
    try:
        from laap.integrations.simworld import MockCommunicator
        comm = MockCommunicator()
    except Exception as e:
        return _fail("MockCommunicator spawn/move", str(e))

    try:
        # 构造一个 fake agent 对象（鸭子类型）
        # 注意：MockCommunicator.spawn_agent 用 `agent.id or name` 作为 entity_id,
        # 因此 id 必须是非零 truthy 值（SimWorld 实际 ID 也都 > 0）。
        class _FakeAgent:
            id = 1
            class _Pos:
                x, y = 0.0, 0.0
            pos = _Pos()
            class _Dir:
                x, y = 1.0, 0.0
            direction = _Dir()
        agent_id = 1
        comm.spawn_agent(_FakeAgent(), name="Alice", position=(100.0, 200.0))
        comm.humanoid_step_forward(agent_id, duration=1.0, direction=0)
        comm.humanoid_rotate(agent_id, angle=90.0, direction="left")
        result = comm.get_position_and_direction(humanoid_ids=[agent_id])
    except Exception as e:
        return _fail("MockCommunicator spawn/move", f"flow error: {e}")

    if not isinstance(result, dict) or not result:
        return _fail("MockCommunicator spawn/move",
                     f"empty result: {result!r}")
    key = ("humanoid", agent_id)
    if key not in result:
        return _fail("MockCommunicator spawn/move",
                     f"key {key} not in {list(result.keys())}")
    pos_vec, yaw = result[key]
    # step_forward 1s @ 200cm/s 应该让 x 增加 ~200（初始 yaw=0）
    # spawn 时 position=(100, 200), yaw 由 direction=(1,0) 推出 = 0°
    x = float(getattr(pos_vec, "x", 0.0))
    if abs(x - 300.0) > 1.0:  # 100 + 200 = 300
        return _fail("MockCommunicator spawn/move",
                     f"unexpected x={x} (expected ~300)")
    # rotate 90° left 后 yaw 应该变成 -90 (mod 360 = 270)
    yaw_val = float(yaw)
    if abs(yaw_val - 270.0) > 1.0 and abs(yaw_val - (-90.0)) > 1.0:
        return _fail("MockCommunicator spawn/move",
                     f"unexpected yaw={yaw_val} (expected 270 or -90)")

    # 相机观测返回 numpy 数组
    try:
        import numpy as np
        img = comm.get_camera_observation(agent_id, "lit")
        if not isinstance(img, np.ndarray) or img.shape != (720, 1280, 3):
            return _fail("MockCommunicator spawn/move",
                         f"bad image shape: {getattr(img, 'shape', None)}")
    except Exception as e:
        return _fail("MockCommunicator spawn/move", f"camera obs: {e}")

    return _ok("MockCommunicator spawn/move",
               f"spawn+step+rotate OK; pos=({x:.1f}, y), yaw={yaw_val:.1f}")


def check_bridge_sync() -> bool:
    """5. SimWorldBridge 双向同步（spawn_humanoid_in_laap + sync_world_to_laap
       + sync_laap_to_world）."""
    try:
        from laap.integrations.simworld import SimWorldBridge, MockCommunicator
        causal, wm, bus = _make_laap_stack()
        if wm is None:
            return _fail("Bridge sync", "UnifiedWorldModel unavailable")
        comm = MockCommunicator()
        bridge = SimWorldBridge(comm, wm, cognitive_bus=bus, sync_interval=0.05)
    except Exception as e:
        return _fail("Bridge sync", str(e))

    try:
        # spawn humanoid 在 LAAP 与 Mock 中
        eid = bridge.spawn_humanoid_in_laap(humanoid_id=0, name="Alice")
        if eid is None:
            return _fail("Bridge sync", "spawn_humanoid_in_laap returned None")
        # 在 MockCommunicator 中实际创建实体
        comm.humanoid_step_forward(0, duration=0.5, direction=0)
        # 同步 SimWorld → LAAP
        synced = bridge.sync_world_to_laap(humanoid_ids=[0])
        if synced < 1:
            return _fail("Bridge sync",
                         f"sync_world_to_laap synced={synced}")
        # 验证 LAAP 实体被更新
        entity = wm.get_entity(eid)
        if entity is None:
            return _fail("Bridge sync", f"entity {eid} missing in world_model")
        if entity.pos is None or abs(entity.pos.x - 100.0) > 1.0:
            # 0.5s @ 200cm/s = 100cm
            pos_x = float(getattr(entity.pos, "x", 0.0)) if entity.pos else None
            return _fail("Bridge sync",
                         f"entity.pos.x={pos_x} (expected ~100)")
        # 同步 LAAP → SimWorld (下发 forward 动作)
        ok = bridge.sync_laap_to_world({
            "humanoid_id": 0,
            "action": "forward",
            "params": {"duration": 0.5, "direction": 0},
        })
        if not ok:
            return _fail("Bridge sync", "sync_laap_to_world returned False")
    except Exception as e:
        return _fail("Bridge sync", f"flow error: {e}")

    stats = bridge.stats()
    detail = "sync_count={0}, entity_map={1}, last_error={2}".format(
        stats["sync_count"], stats["entity_map_size"], stats["last_error"]
    )
    return _ok("Bridge sync", detail)


def check_brain_generate_instructions() -> bool:
    """6. LAAPBrain.generate_instructions 返回有效 JSON."""
    try:
        from laap.integrations.simworld import LAAPBrain
        causal, wm, bus = _make_laap_stack()
        brain = LAAPBrain(
            causal_engine=causal,
            world_model=wm,
            cognitive_bus=bus,
            fallback_to_llm=True,
        )
    except Exception as e:
        return _fail("Brain generate", str(e))

    # 模拟 SimWorld 的 user_prompt（与 simworld.local_planner.prompt 对齐）
    user_prompt = (
        "You are currently at Vector(x=100, y=200) and your direction is "
        "Vector(x=1, y=0). Your final destination is Vector(x=500, y=200). "
        "The destination is approximately 400.00 cm away, and the relative "
        "angle to it is 0.00 degrees (negative = to your left, positive = "
        "to your right). Your walking speed is 200 cm/s."
    )

    try:
        action_json, elapsed = brain.generate_instructions(
            system_prompt="You are a navigation agent.",
            user_prompt=user_prompt,
            images=[],
            response_format=None,
        )
    except Exception as e:
        return _fail("Brain generate", f"call error: {e}")

    if not isinstance(action_json, str):
        return _fail("Brain generate",
                     f"action_json type={type(action_json).__name__}")
    try:
        parsed = json.loads(action_json)
    except json.JSONDecodeError as e:
        return _fail("Brain generate",
                     f"invalid JSON: {e}; raw={action_json[:120]!r}")

    if "choice" not in parsed:
        return _fail("Brain generate",
                     f"no 'choice' key in {list(parsed.keys())}")
    if parsed["choice"] not in (0, 1, 2):
        return _fail("Brain generate",
                     f"invalid choice={parsed['choice']}")

    stats = brain.stats()
    detail = "choice={0}, elapsed={1:.3f}s, decisions={2}, laap_ok={3}".format(
        parsed["choice"], float(elapsed) if elapsed is not None else 0.0,
        stats["decision_count"], stats["laap_success_count"],
    )
    return _ok("Brain generate", detail)


def check_parse_simworld_state() -> bool:
    """7. actions.parse_simworld_state 解析正确."""
    try:
        from laap.integrations.simworld.actions import parse_simworld_state
    except Exception as e:
        return _fail("parse_simworld_state", str(e))

    user_prompt = (
        "You are currently at Vector(x=100, y=200) and your direction is "
        "Vector(x=1, y=0). Your final destination is Vector(x=500, y=200). "
        "The destination is approximately 412.56 cm away, and the relative "
        "angle to it is 25.30 degrees."
    )
    try:
        state = parse_simworld_state(user_prompt)
    except Exception as e:
        return _fail("parse_simworld_state", f"error: {e}")

    if not isinstance(state, dict):
        return _fail("parse_simworld_state", f"got {type(state).__name__}")

    # 检查关键字段
    pos = state.get("position")
    if not (isinstance(pos, dict) and pos.get("x") == 100.0 and pos.get("y") == 200.0):
        return _fail("parse_simworld_state",
                     f"position={pos} (expected x=100, y=200)")
    direction = state.get("direction")
    if not (isinstance(direction, dict) and direction.get("x") == 1.0):
        return _fail("parse_simworld_state",
                     f"direction={direction} (expected x=1)")
    target = state.get("target")
    if not (isinstance(target, dict) and target.get("x") == 500.0):
        return _fail("parse_simworld_state",
                     f"target={target} (expected x=500)")
    if state.get("relative_distance") != 412.56:
        return _fail("parse_simworld_state",
                     f"distance={state.get('relative_distance')} (expected 412.56)")
    if state.get("relative_angle") != 25.30:
        return _fail("parse_simworld_state",
                     f"angle={state.get('relative_angle')} (expected 25.30)")

    return _ok("parse_simworld_state",
               "pos/direction/target/distance/angle all parsed")


def check_candidate_actions() -> bool:
    """8. actions.candidate_actions 返回非空候选列表."""
    try:
        from laap.integrations.simworld.actions import (
            candidate_actions, ACTION_FORWARD, ACTION_ROTATE_LEFT,
            ACTION_ROTATE_RIGHT, ACTION_STOP,
        )
    except Exception as e:
        return _fail("candidate_actions", str(e))

    state = {
        "position": {"x": 100.0, "y": 200.0},
        "direction": {"x": 1.0, "y": 0.0},
        "target": {"x": 500.0, "y": 200.0},
        "relative_distance": 400.0,
        "relative_angle": 25.30,
    }
    try:
        candidates = candidate_actions(state)
    except Exception as e:
        return _fail("candidate_actions", f"error: {e}")

    if not isinstance(candidates, list) or len(candidates) < 4:
        return _fail("candidate_actions",
                     f"got {len(candidates) if isinstance(candidates, list) else 'non-list'} candidates")
    names = {c.get("name") for c in candidates}
    required = {ACTION_FORWARD, ACTION_ROTATE_LEFT, ACTION_ROTATE_RIGHT, ACTION_STOP}
    if not required.issubset(names):
        return _fail("candidate_actions",
                     f"missing: {sorted(required - names)}")
    # 验证 low_level 字段
    for c in candidates:
        if "low_level" not in c or "params" not in c:
            return _fail("candidate_actions",
                         f"bad candidate: {c}")
    detail = "{0} candidates: {1}".format(len(candidates), sorted(names))
    return _ok("candidate_actions", detail)


def check_laap_decision_to_simworld_action() -> bool:
    """9. actions.laap_decision_to_simworld_action 转换正确."""
    try:
        from laap.integrations.simworld.actions import (
            laap_decision_to_simworld_action,
            to_high_level_action_json,
            LOW_LEVEL_STEP_FORWARD, LOW_LEVEL_TURN_AROUND, LOW_LEVEL_DO_NOTHING,
            ACTION_FORWARD, ACTION_ROTATE_LEFT, ACTION_ROTATE_RIGHT, ACTION_STOP,
        )
    except Exception as e:
        return _fail("decision conversion", str(e))

    cases = [
        (
            {"action": ACTION_FORWARD, "params": {"duration": 2.0, "direction": 0},
             "regret": 0.1, "relief": 0.8, "reasoning": "aligned"},
            LOW_LEVEL_STEP_FORWARD,
            {"duration": 2.0, "direction": 0},
        ),
        (
            {"action": ACTION_ROTATE_LEFT, "params": {"angle": 45.0},
             "regret": 0.3, "relief": 0.6, "reasoning": "align left"},
            LOW_LEVEL_TURN_AROUND,
            {"clockwise": False, "angle": 45.0},
        ),
        (
            {"action": ACTION_ROTATE_RIGHT, "params": {"angle": 30.0},
             "regret": 0.4, "relief": 0.5, "reasoning": "align right"},
            LOW_LEVEL_TURN_AROUND,
            {"clockwise": True, "angle": 30.0},
        ),
        (
            {"action": ACTION_STOP, "params": {},
             "regret": 0.9, "relief": 0.1, "reasoning": "stop"},
            LOW_LEVEL_DO_NOTHING,
            {},
        ),
    ]

    for decision, expected_choice, expected_fields in cases:
        try:
            converted = laap_decision_to_simworld_action(decision)
        except Exception as e:
            return _fail("decision conversion",
                         f"convert {decision['action']} error: {e}")
        if converted.get("choice") != expected_choice:
            return _fail("decision conversion",
                         f"{decision['action']}: choice={converted.get('choice')} expected {expected_choice}")
        for k, v in expected_fields.items():
            if converted.get(k) != v:
                return _fail("decision conversion",
                             f"{decision['action']}: {k}={converted.get(k)} expected {v}")
        if "reasoning" not in converted:
            return _fail("decision conversion",
                         f"{decision['action']}: missing reasoning")

    # 测试 HighLevelActionSpace 包装
    try:
        high_json = to_high_level_action_json(
            {"choice": 1, "reasoning": "test"}, destination=[500.0, 200.0]
        )
        high = json.loads(high_json)
        if "action_queue" not in high or "destination" not in high:
            return _fail("decision conversion",
                         f"bad high-level: {high}")
        if high["destination"] != [500.0, 200.0]:
            return _fail("decision conversion",
                         f"bad destination: {high['destination']}")
    except Exception as e:
        return _fail("decision conversion", f"to_high_level_action_json: {e}")

    return _ok("decision conversion",
               "4 actions + high-level wrap OK")


def check_cognitive_bus_events() -> bool:
    """10. CognitiveBus 在 LAAPBrain 决策时被触发.

    订阅 PERCEPTION_INCOMING / ACTION_TAKEN，调用 generate_instructions，
    验证至少各触发了一次。
    """
    try:
        from laap.agi.cognitive_bus import (
            CognitiveBus, CognitiveEventType,
        )
        from laap.integrations.simworld import LAAPBrain
    except Exception as e:
        return _fail("CognitiveBus events", f"import error: {e}")

    bus = CognitiveBus(agent_name="events_verify")
    received = {"perception": 0, "action": 0, "raw": []}

    def _on_perception(event):
        received["perception"] += 1
        received["raw"].append(("perception", getattr(event, "type", None)))

    def _on_action(event):
        received["action"] += 1
        received["raw"].append(("action", getattr(event, "type", None)))

    try:
        bus.subscribe("verify", CognitiveEventType.PERCEPTION_INCOMING, _on_perception)
        bus.subscribe("verify", CognitiveEventType.ACTION_TAKEN, _on_action)
    except Exception as e:
        return _fail("CognitiveBus events", f"subscribe error: {e}")

    # 用一个简单的 MockCommunicator 让 LAAPBrain 拿到状态
    try:
        comm = _make_mock_communicator(cognitive_bus=bus)
        # 在 mock 中 spawn 一个 humanoid 让 get_position 有数据
        comm.humanoid_step_forward(0, duration=0.0, direction=0)  # 仅触发事件
    except Exception as e:
        return _fail("CognitiveBus events", f"mock comm setup: {e}")

    # 构造 LAAPBrain，注入同一个 bus
    try:
        causal, wm, _ = _make_laap_stack()
        brain = LAAPBrain(
            causal_engine=causal,
            world_model=wm,
            cognitive_bus=bus,
            fallback_to_llm=False,  # 关闭 fallback 避免 LLM 调用引入额外事件
        )
    except Exception as e:
        return _fail("CognitiveBus events", f"brain init: {e}")

    # 触发一次决策（应该产生 PERCEPTION_INCOMING pre + ACTION_TAKEN laap_decision）
    user_prompt = (
        "You are currently at Vector(x=0, y=0) and your direction is "
        "Vector(x=1, y=0). Your final destination is Vector(x=300, y=0). "
        "The destination is approximately 300.00 cm away, and the relative "
        "angle to it is 0.00 degrees."
    )
    try:
        action_json, elapsed = brain.generate_instructions(
            system_prompt="navigate",
            user_prompt=user_prompt,
            images=[],
        )
    except Exception as e:
        return _fail("CognitiveBus events", f"generate_instructions: {e}")

    # MockCommunicator 自身也会发事件，所以 received 至少有 brain 的事件
    if received["perception"] < 1:
        return _fail("CognitiveBus events",
                     f"no PERCEPTION_INCOMING events (raw={received['raw'][:5]})")
    if received["action"] < 1:
        return _fail("CognitiveBus events",
                     f"no ACTION_TAKEN events (raw={received['raw'][:5]})")

    detail = "perception={0}, action={1} (total events captured)".format(
        received["perception"], received["action"]
    )
    return _ok("CognitiveBus events", detail)


# ═══════════════════════════════════════════════════════════════
# Runner
# ═══════════════════════════════════════════════════════════════

CHECKS = [
    check_simworld_integration_import,
    check_laap_brain_init,
    check_evented_communicator_init,
    check_mock_communicator_spawn_move,
    check_bridge_sync,
    check_brain_generate_instructions,
    check_parse_simworld_state,
    check_candidate_actions,
    check_laap_decision_to_simworld_action,
    check_cognitive_bus_events,
]


def verify() -> bool:
    """运行全部检查，返回 True 表示全部通过."""
    results = [fn() for fn in CHECKS]
    return all(results)


def main() -> int:
    print()
    print("  LAAP × SimWorld integration — verification (headless)")
    print("  " + "=" * 56)
    print()
    results = [fn() for fn in CHECKS]
    passed = sum(1 for r in results if r)
    total = len(results)
    print()
    print(f"  Result: {passed}/{total} checks passed")
    print()
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
