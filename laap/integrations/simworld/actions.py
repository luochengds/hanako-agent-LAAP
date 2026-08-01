# -*- coding: utf-8 -*-
"""动作空间映射 — LAAP 决策 ↔ SimWorld UE 动作.

负责三件事：
  1. ``parse_simworld_state``: 从 SimWorld user_prompt 文本中解析
     position / direction / target 等状态字段。
  2. ``candidate_actions``: 根据当前状态生成候选动作列表
     (forward / rotate_left / rotate_right / stop)。
  3. ``laap_decision_to_simworld_action``: 把 LAAP 因果引擎的决策
     转换成 SimWorld ``HighLevelActionSpace`` 兼容的 JSON。

SimWorld 的 LowLevelAction 枚举：
    0 = DO_NOTHING, 1 = STEP_FORWARD, 2 = TURN_AROUND
"""

from __future__ import annotations

import json
import logging
import math
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger("laap.integrations.simworld.actions")


# SimWorld LowLevelAction 枚举值（与 simworld.local_planner.action_space 对齐）
LOW_LEVEL_DO_NOTHING = 0
LOW_LEVEL_STEP_FORWARD = 1
LOW_LEVEL_TURN_AROUND = 2

# LAAP 内部候选动作名（与 brain.py 反事实推演对齐）
ACTION_FORWARD = "forward"
ACTION_ROTATE_LEFT = "rotate_left"
ACTION_ROTATE_RIGHT = "rotate_right"
ACTION_STOP = "stop"


def parse_simworld_state(user_prompt: str) -> Dict[str, Any]:
    """从 SimWorld user_prompt 文本中解析状态.

    SimWorld 的 user_prompt 通常包含形如：
        "You are currently at Vector(x=100, y=200) and your direction is Vector(x=1, y=0).
         Your final destination is Vector(x=500, y=0). The destination is approximately
         412.56 cm away, and the relative angle to it is 25.30 degrees ..."

    解析输出:
        {
            "position": {"x": 100.0, "y": 200.0},
            "direction": {"x": 1.0, "y": 0.0},
            "target": {"x": 500.0, "y": 0.0},
            "relative_distance": 412.56,
            "relative_angle": 25.3,
            "raw": <原始文本>,
        }

    Args:
        user_prompt: SimWorld 提供的 user_prompt 文本.

    Returns:
        解析后的状态字典。无法解析的字段为 None。
    """
    if not isinstance(user_prompt, str):
        return {
            "position": None, "direction": None, "target": None,
            "relative_distance": None, "relative_angle": None,
            "raw": str(user_prompt),
        }

    state: Dict[str, Any] = {
        "position": None, "direction": None, "target": None,
        "relative_distance": None, "relative_angle": None,
        "raw": user_prompt,
    }

    def _parse_vector(text: str, pattern: str) -> Optional[Dict[str, float]]:
        m = re.search(pattern, text)
        if not m:
            return None
        try:
            return {"x": float(m.group(1)), "y": float(m.group(2))}
        except (ValueError, IndexError):
            return None

    # 兼容 "Vector(x=100, y=200)" / "Vector(100, 200)" / "[100, 200]" 等格式
    vec_re = r"[-\d.]+"
    state["position"] = _parse_vector(
        user_prompt,
        r"currently at[^()]*\(?[^,]*?x\s*=\s*(" + vec_re + r")[^,]*,\s*y\s*=\s*(" + vec_re + r")",
    ) or _parse_vector(
        user_prompt,
        r"currently at[^[]*\[\s*(" + vec_re + r")\s*,\s*(" + vec_re + r")\s*\]",
    )
    state["direction"] = _parse_vector(
        user_prompt,
        r"direction is[^()]*\(?[^,]*?x\s*=\s*(" + vec_re + r")[^,]*,\s*y\s*=\s*(" + vec_re + r")",
    ) or _parse_vector(
        user_prompt,
        r"direction is[^[]*\[\s*(" + vec_re + r")\s*,\s*(" + vec_re + r")\s*\]",
    )
    state["target"] = _parse_vector(
        user_prompt,
        r"(?:final )?destination is[^()]*\(?[^,]*?x\s*=\s*(" + vec_re + r")[^,]*,\s*y\s*=\s*(" + vec_re + r")",
    ) or _parse_vector(
        user_prompt,
        r"(?:final )?destination is[^[]*\[\s*(" + vec_re + r")\s*,\s*(" + vec_re + r")\s*\]",
    )

    # 距离 / 角度
    m_dist = re.search(r"approximately\s+([-\d.]+)\s*cm\s+away", user_prompt)
    if m_dist:
        try:
            state["relative_distance"] = float(m_dist.group(1))
        except ValueError:
            pass

    m_angle = re.search(r"relative angle[^-\d]*(-?[\d.]+)\s*degrees", user_prompt)
    if m_angle:
        try:
            state["relative_angle"] = float(m_angle.group(1))
        except ValueError:
            pass

    return state


def candidate_actions(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    """根据当前状态生成候选动作列表.

    每个候选动作包含：
        - name: 动作名 (forward / rotate_left / rotate_right / stop)
        - low_level: 对应 SimWorld LowLevelAction 值
        - params: 调用 SimWorld communicator 所需的参数
        - description: 人类可读描述

    Args:
        state: ``parse_simworld_state`` 返回的状态字典.

    Returns:
        候选动作列表，至少返回 4 个标准动作。
    """
    angle = state.get("relative_angle")
    distance = state.get("relative_distance")

    # 默认参数
    forward_duration = 1.0
    rotate_angle = 30.0  # 默认旋转角度

    # 根据相对角度调整旋转角度
    if isinstance(angle, (int, float)):
        abs_angle = abs(angle)
        if abs_angle > 90:
            rotate_angle = 90.0
        elif abs_angle > 45:
            rotate_angle = 45.0
        else:
            rotate_angle = 30.0

    # 距离很近时优先 stop
    if isinstance(distance, (int, float)) and distance < 50.0:
        forward_duration = 0.0

    return [
        {
            "name": ACTION_FORWARD,
            "low_level": LOW_LEVEL_STEP_FORWARD,
            "params": {"duration": forward_duration, "direction": 0},
            "description": "向前移动 {0}s".format(forward_duration),
        },
        {
            "name": ACTION_ROTATE_LEFT,
            "low_level": LOW_LEVEL_TURN_AROUND,
            "params": {"angle": rotate_angle, "clockwise": False},
            "description": "向左旋转 {0}°".format(rotate_angle),
        },
        {
            "name": ACTION_ROTATE_RIGHT,
            "low_level": LOW_LEVEL_TURN_AROUND,
            "params": {"angle": rotate_angle, "clockwise": True},
            "description": "向右旋转 {0}°".format(rotate_angle),
        },
        {
            "name": ACTION_STOP,
            "low_level": LOW_LEVEL_DO_NOTHING,
            "params": {},
            "description": "停止/不做任何动作",
        },
    ]


def laap_decision_to_simworld_action(decision: Dict[str, Any]) -> Dict[str, Any]:
    """把 LAAP causal_engine 决策结果转换为 SimWorld HighLevelActionSpace 兼容 JSON.

    LAAP 决策结构（brain.py 输出）:
        {
            "action": "forward" | "rotate_left" | "rotate_right" | "stop",
            "regret": float,
            "relief": float,
            "intensity": float,
            "reasoning": str,
            "params": {...},
        }

    转换为 SimWorld LowLevelActionSpace 兼容 JSON:
        {
            "choice": 0|1|2,
            "duration": Optional[float],
            "direction": Optional[int],
            "angle": Optional[float],
            "clockwise": Optional[bool],
            "reasoning": str,
        }

    也兼容 HighLevelActionSpace 形态（含 action_queue/destination）。

    Args:
        decision: LAAP 决策字典.

    Returns:
        SimWorld 兼容的动作 JSON 字典。
    """
    if not isinstance(decision, dict):
        return {
            "choice": LOW_LEVEL_DO_NOTHING,
            "reasoning": "invalid decision, fallback to do nothing",
        }

    action_name = decision.get("action", ACTION_STOP)
    params = decision.get("params", {}) or {}
    reasoning = decision.get("reasoning", "")
    regret = decision.get("regret", 0.0)
    relief = decision.get("relief", 0.0)

    # 把 regret/relief 拼入 reasoning 便于 LLM 后续读取
    full_reasoning = "{0} | regret={1:.3f} relief={2:.3f}".format(
        reasoning, regret, relief
    ) if reasoning else "regret={0:.3f} relief={1:.3f}".format(regret, relief)

    if action_name == ACTION_FORWARD:
        return {
            "choice": LOW_LEVEL_STEP_FORWARD,
            "duration": params.get("duration", 1.0),
            "direction": params.get("direction", 0),
            "angle": None,
            "clockwise": None,
            "reasoning": full_reasoning,
        }
    elif action_name == ACTION_ROTATE_LEFT:
        return {
            "choice": LOW_LEVEL_TURN_AROUND,
            "duration": None,
            "direction": None,
            "angle": params.get("angle", 30.0),
            "clockwise": False,
            "reasoning": full_reasoning,
        }
    elif action_name == ACTION_ROTATE_RIGHT:
        return {
            "choice": LOW_LEVEL_TURN_AROUND,
            "duration": None,
            "direction": None,
            "angle": params.get("angle", 30.0),
            "clockwise": True,
            "reasoning": full_reasoning,
        }
    elif action_name == ACTION_STOP:
        return {
            "choice": LOW_LEVEL_DO_NOTHING,
            "duration": None,
            "direction": None,
            "angle": None,
            "clockwise": None,
            "reasoning": full_reasoning,
        }
    else:
        # 未知动作 → stop
        return {
            "choice": LOW_LEVEL_DO_NOTHING,
            "duration": None,
            "direction": None,
            "angle": None,
            "clockwise": None,
            "reasoning": "unknown action '{0}', fallback to stop".format(action_name),
        }


def to_high_level_action_json(action_json: Dict[str, Any],
                              destination: Optional[List[float]] = None) -> str:
    """把 low-level 决策 JSON 包装成 HighLevelActionSpace JSON 字符串.

    SimWorld 的 LocalPlanner.parse 期望 response 是 HighLevelActionSpace
    兼容的 JSON 字符串。当 LAAPBrain 直接返回 low-level 动作时，
    可以用这个函数包装一层。

    Args:
        action_json: laap_decision_to_simworld_action 返回的字典.
        destination: 可选目标坐标 [x, y].

    Returns:
        JSON 字符串。
    """
    high_level = {
        "action_queue": [1],  # 默认 NAVIGATE
        "destination": destination or [0, 0],
        "object_name": None,
        "reasoning": action_json.get("reasoning", ""),
    }
    return json.dumps(high_level, ensure_ascii=False)
