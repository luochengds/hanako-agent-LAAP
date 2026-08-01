# -*- coding: utf-8 -*-
"""LAAPBrain — 替换 SimWorld 的 A2ALLM，注入因果/反事实/PSI 能力.

核心创新点：
  - 继承 SimWorld 的 ``A2ALLM``，签名与 ``generate_instructions`` 兼容。
  - 内部调用 LAAP ``UnifiedCausalEngine`` 对每个候选动作做反事实推演，
    评估 regret/relief/intensity，选择 regret 最低的动作分支。
  - 调用 LAAP ``UnifiedWorldModel.predict`` 做短期预测。
  - 通过 LAAP ``CognitiveBus`` 发布 ``ACTION_TAKEN``/``PERCEPTION_INCOMING`` 事件。
  - 所有 LAAP 异常都被捕获，失败时 fallback 到 ``super().generate_instructions``
    （纯 LLM 模式），保证不破坏 SimWorld 主循环。

返回签名与 A2ALLM 一致：``(action_json, elapsed_time)``
其中 action_json 是 str 或 None。

Usage:
    brain = LAAPBrain(
        causal_engine=UnifiedCausalEngine(),
        world_model=UnifiedWorldModel(),
        cognitive_bus=CognitiveBus(),
        llm_model_name="gpt-4o-mini",
        fallback_to_llm=True,
    )
    action_json, elapsed = brain.generate_instructions(
        system_prompt=NAVIGATION_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        images=images,
        response_format=LowLevelActionSpace,
    )
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("laap.integrations.simworld.brain")


# ─── SimWorld A2ALLM 容错导入 ────────────────────────────────

try:
    from simworld.llm.a2a_llm import A2ALLM as _SWA2ALLM
    _HAS_A2ALLM = True
    _A2ALLM_INIT_REQUIRES_OPENAI = True
except Exception:  # pragma: no cover — SimWorld 或 openai 不可用
    _SWA2ALLM = None  # type: ignore
    _HAS_A2ALLM = False
    _A2ALLM_INIT_REQUIRES_OPENAI = False


# ─── LAAP 容错导入 ────────────────────────────────────────────

try:
    from laap.agi.causal import UnifiedCausalEngine, InterventionResult
    _HAS_CAUSAL = True
except Exception:  # pragma: no cover
    UnifiedCausalEngine = None  # type: ignore
    InterventionResult = None  # type: ignore
    _HAS_CAUSAL = False

try:
    from laap.agi.world_model import UnifiedWorldModel, EntityType
    _HAS_WM = True
except Exception:  # pragma: no cover
    UnifiedWorldModel = None  # type: ignore
    EntityType = None  # type: ignore
    _HAS_WM = False

try:
    from laap.agi.cognitive_bus import CognitiveBus, CognitiveEventType
    _HAS_COG_BUS = True
except Exception:  # pragma: no cover
    CognitiveBus = None  # type: ignore
    CognitiveEventType = None  # type: ignore
    _HAS_COG_BUS = False


# ─── 本地 actions 模块 ────────────────────────────────────────

from laap.integrations.simworld.actions import (
    parse_simworld_state,
    candidate_actions,
    laap_decision_to_simworld_action,
    to_high_level_action_json,
    ACTION_FORWARD, ACTION_ROTATE_LEFT, ACTION_ROTATE_RIGHT, ACTION_STOP,
)


# ─── CognitiveEventType 容错辅助 ─────────────────────────────

def _make_event_type(name: str):
    if _HAS_COG_BUS and CognitiveEventType is not None:
        try:
            return CognitiveEventType(name)
        except Exception:
            return name
    return name


EV_PERCEPTION = _make_event_type("perception_incoming")
EV_ACTION = _make_event_type("action_taken")


# ═══════════════════════════════════════════════════════════════
# LAAPBrain
# ═══════════════════════════════════════════════════════════════

class LAAPBrain(_SWA2ALLM if _HAS_A2ALLM else object):  # type: ignore[misc]
    """LAAP 增强版 A2ALLM — 在 SimWorld LLM 决策环节注入 LAAP 因果推演.

    工作流程:
      1. 接收 SimWorld 的 system_prompt + user_prompt + images
      2. 从 user_prompt 解析当前 SimWorld 状态 (position/direction/target)
      3. 对每个候选动作调 ``causal_engine.counterfactual`` 评估
         regret/relief/intensity
      4. 调 ``world_model.predict`` 做短期预测
      5. 通过 ``cognitive_bus`` 发布 PERCEPTION_INCOMING / ACTION_TAKEN 事件
      6. 选择 regret 最低的动作分支，组装为 SimWorld 兼容 JSON 返回

    若 LAAP 推演失败且 ``fallback_to_llm=True``，回退到
    ``super().generate_instructions(...)``（纯 LLM 模式）。

    若 SimWorld A2ALLM 自身不可用（缺 openai/cv2 等），LAAPBrain
    仍可作为独立决策器工作（直接返回 LAAP 决策 JSON）。
    """

    def __init__(self,
                 causal_engine: Optional[Any] = None,
                 world_model: Optional[Any] = None,
                 cognitive_bus: Optional[Any] = None,
                 llm_model_name: str = "gpt-4o-mini",
                 fallback_to_llm: bool = True,
                 **kwargs):
        """初始化 LAAPBrain.

        Args:
            causal_engine: LAAP UnifiedCausalEngine 实例（可选）.
            world_model: LAAP UnifiedWorldModel 实例（可选）.
            cognitive_bus: LAAP CognitiveBus 实例（可选）.
            llm_model_name: 透传给 A2ALLM 的模型名.
            fallback_to_llm: LAAP 推演失败时是否回退到纯 LLM.
            **kwargs: 透传给 A2ALLM 的额外参数（url, provider 等）.
        """
        # 尝试调用父类 A2ALLM.__init__
        self._has_parent_llm = False
        self._parent_init_error: Optional[str] = None
        if _HAS_A2ALLM:
            try:
                # 过滤掉 A2ALLM 不接受的参数
                url = kwargs.get("url", None)
                provider = kwargs.get("provider", "openai")
                super().__init__(model_name=llm_model_name, url=url, provider=provider)
                self._has_parent_llm = True
            except Exception as e:
                # 常见情况：没有 OPENAI_API_KEY、openai 验证失败
                self._parent_init_error = str(e)
                logger.info("A2ALLM parent init failed (%s); "
                            "LAAPBrain will run in LAAP-only mode", e)
                # 退化：把 A2ALLM 必需的属性手动塞进去
                self.model_name = llm_model_name
                self.provider = kwargs.get("provider", "openai")
                self.client = None
                try:
                    from simworld.utils.logger import Logger as _SWLogger
                    self.logger = _SWLogger.get_logger("LAAPBrain")
                except Exception:
                    self.logger = logger
        else:
            # SimWorld A2ALLM 完全不可用 — 纯 LAAP 模式
            self.model_name = llm_model_name
            self.provider = kwargs.get("provider", "openai")
            self.client = None
            self.logger = logger

        # LAAP 组件
        self.causal_engine = causal_engine
        self.world_model = world_model
        self.cognitive_bus = cognitive_bus
        self.fallback_to_llm = bool(fallback_to_llm)

        # 决策统计
        self._decision_count = 0
        self._laap_success_count = 0
        self._fallback_count = 0
        self._last_decision: Optional[Dict[str, Any]] = None

    # ─── CognitiveBus 事件发布 ──────────────────────────────

    def _publish(self, event_type, data: Dict[str, Any]):
        if self.cognitive_bus is None:
            return
        try:
            self.cognitive_bus.publish(event_type, "laap_brain", data)
        except Exception as e:
            logger.debug("brain publish failed: %s", e)

    # ─── 反事实评估 ─────────────────────────────────────────

    def _evaluate_action(self, action: Dict[str, Any],
                         state: Dict[str, Any]) -> Dict[str, Any]:
        """对单个候选动作做反事实评估.

        Returns:
            {
                "action": <action_name>,
                "params": {...},
                "regret": float,    # 0~1, 越低越好
                "relief": float,    # 0~1
                "intensity": float, # 0~1
                "confidence": float,
                "reasoning": str,
                "would_have_happened": str,
            }
        """
        action_name = action.get("name", ACTION_STOP)
        params = action.get("params", {}) or {}

        # 默认评估值
        result = {
            "action": action_name,
            "params": params,
            "regret": 0.5,
            "relief": 0.5,
            "intensity": 0.5,
            "confidence": 0.5,
            "reasoning": "",
            "would_have_happened": "",
        }

        target = state.get("target")
        target_str = ""
        if isinstance(target, dict):
            target_str = "({0},{1})".format(
                target.get("x", 0), target.get("y", 0))

        # 调用 LAAP UnifiedCausalEngine.counterfactual
        if _HAS_CAUSAL and self.causal_engine is not None:
            try:
                cf = self.causal_engine.counterfactual(
                    action=action_name,
                    actor="humanoid",
                    target=target_str or "goal",
                )
                result["would_have_happened"] = cf.get("would_have_happened", "")
                result["confidence"] = float(cf.get("confidence", 0.5))
                triggered = cf.get("triggered_rules", [])
                if triggered:
                    result["reasoning"] = "rules: {0}".format(", ".join(triggered))
                else:
                    result["reasoning"] = "no rules triggered"
                # 简单启发式：触发规则越多 → regret 越低（动作有明确效果）
                if triggered:
                    result["regret"] = 0.2
                    result["relief"] = 0.7
                    result["intensity"] = 0.7
                else:
                    # 没触发规则 → 中等 regret
                    result["regret"] = 0.5
                    result["relief"] = 0.4
                    result["intensity"] = 0.4
            except Exception as e:
                logger.debug("counterfactual failed for %s: %s", action_name, e)
                result["reasoning"] = "cf_error: {0}".format(e)
        else:
            # 没有因果引擎，用启发式评估
            angle = state.get("relative_angle")
            distance = state.get("relative_distance")

            if action_name == ACTION_FORWARD:
                # 朝向目标且距离不太近 → forward 是好选择
                if isinstance(angle, (int, float)) and isinstance(distance, (int, float)):
                    if abs(angle) < 30 and distance > 50:
                        result["regret"] = 0.1
                        result["relief"] = 0.8
                        result["intensity"] = 0.7
                        result["reasoning"] = "aligned with target, distance={0}".format(distance)
                    else:
                        result["regret"] = 0.6
                        result["relief"] = 0.3
                        result["intensity"] = 0.5
                        result["reasoning"] = "misaligned, angle={0}".format(angle)
                else:
                    result["regret"] = 0.4
                    result["reasoning"] = "no angle/distance info"
            elif action_name in (ACTION_ROTATE_LEFT, ACTION_ROTATE_RIGHT):
                # 偏离目标 → 旋转有意义
                if isinstance(angle, (int, float)):
                    if action_name == ACTION_ROTATE_LEFT and angle < 0:
                        result["regret"] = 0.2
                        result["relief"] = 0.7
                        result["reasoning"] = "rotate left to align (angle<0)"
                    elif action_name == ACTION_ROTATE_RIGHT and angle > 0:
                        result["regret"] = 0.2
                        result["relief"] = 0.7
                        result["reasoning"] = "rotate right to align (angle>0)"
                    else:
                        result["regret"] = 0.6
                        result["reasoning"] = "rotate wrong direction"
                else:
                    result["regret"] = 0.5
                    result["reasoning"] = "no angle info"
            elif action_name == ACTION_STOP:
                # 距离很近 → stop 是好选择
                if isinstance(distance, (int, float)) and distance < 50:
                    result["regret"] = 0.1
                    result["relief"] = 0.8
                    result["reasoning"] = "close to target, stop"
                else:
                    result["regret"] = 0.7
                    result["relief"] = 0.2
                    result["reasoning"] = "far from target, stop is suboptimal"

        # 调用 LAAP UnifiedWorldModel.predict 做短期预测（增强 confidence）
        if _HAS_WM and self.world_model is not None:
            try:
                # 找到或创建一个虚拟 humanoid 实体做预测
                # 这里只调用 predict，不要求实体存在
                pred = self.world_model.predict("humanoid", horizon=1.0)
                pred_conf = float(getattr(pred, "confidence", 0.5))
                # 用预测置信度调制 confidence
                result["confidence"] = (result["confidence"] + pred_conf) / 2
            except Exception as e:
                logger.debug("world_model.predict failed: %s", e)

        return result

    # ─── 主决策入口 ─────────────────────────────────────────

    def generate_instructions(self,
                              system_prompt,
                              user_prompt,
                              images=[],
                              max_tokens=None,
                              temperature=0.7,
                              top_p=1.0,
                              response_format=None) -> Tuple[Optional[str], float]:
        """生成指令 — LAAP 因果增强版.

        签名与 SimWorld A2ALLM.generate_instructions 完全兼容。
        返回 ``(action_json, elapsed_time)``，action_json 是 str 或 None。
        """
        start_time = time.time()
        self._decision_count += 1

        # 发布感知事件
        self._publish(EV_PERCEPTION, {
            "op": "generate_instructions", "phase": "pre",
            "decision_count": self._decision_count,
            "has_images": bool(images),
            "prompt_len": len(user_prompt) if isinstance(user_prompt, str) else 0,
        })

        # ─── 1. 解析 SimWorld 状态 ───────────────────────────
        try:
            state = parse_simworld_state(user_prompt)
        except Exception as e:
            logger.warning("parse_simworld_state failed: %s", e)
            state = {"raw": str(user_prompt)}

        # ─── 2. 生成候选动作 ─────────────────────────────────
        try:
            candidates = candidate_actions(state)
        except Exception as e:
            logger.warning("candidate_actions failed: %s", e)
            candidates = []

        # ─── 3. LAAP 反事实评估 ──────────────────────────────
        laap_decision: Optional[Dict[str, Any]] = None
        try:
            evaluations = []
            for cand in candidates:
                eva = self._evaluate_action(cand, state)
                evaluations.append(eva)

            if evaluations:
                # 选 regret 最低的，regret 相同则选 relief 最高的
                evaluations.sort(
                    key=lambda x: (-x["regret"], -x["relief"])  # 先按 regret 升序需要反序
                )
                # 修正：regret 越低越好，所以应该按 regret 升序
                evaluations.sort(key=lambda x: x["regret"])
                laap_decision = evaluations[0]
                self._laap_success_count += 1
                self._last_decision = laap_decision
        except Exception as e:
            logger.warning("LAAP causal evaluation failed: %s", e)
            laap_decision = None

        # ─── 4. 组装 SimWorld 兼容 JSON ─────────────────────
        action_json_str: Optional[str] = None
        if laap_decision is not None:
            try:
                simworld_action = laap_decision_to_simworld_action(laap_decision)
                action_json_str = json.dumps(simworld_action, ensure_ascii=False)

                # 发布 ACTION_TAKEN 事件
                self._publish(EV_ACTION, {
                    "op": "generate_instructions", "phase": "laap_decision",
                    "action": laap_decision.get("action"),
                    "regret": laap_decision.get("regret"),
                    "relief": laap_decision.get("relief"),
                    "intensity": laap_decision.get("intensity"),
                    "reasoning": laap_decision.get("reasoning"),
                    "decision_count": self._decision_count,
                })
            except Exception as e:
                logger.warning("assemble action json failed: %s", e)
                action_json_str = None

        # ─── 5. Fallback 到纯 LLM ──────────────────────────
        if action_json_str is None and self.fallback_to_llm and self._has_parent_llm:
            try:
                parent_result = super().generate_instructions(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    images=images,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    top_p=top_p,
                    response_format=response_format,
                )
                self._fallback_count += 1
                self._publish(EV_ACTION, {
                    "op": "generate_instructions", "phase": "fallback_llm",
                    "decision_count": self._decision_count,
                })
                # parent_result 是 (action_json, elapsed_time)
                if isinstance(parent_result, tuple) and len(parent_result) == 2:
                    return parent_result
                return parent_result, time.time() - start_time
            except Exception as e:
                logger.warning("fallback to LLM failed: %s", e)
                # 最后兜底：返回 stop 动作
                if laap_decision is None:
                    laap_decision = {
                        "action": ACTION_STOP, "params": {},
                        "regret": 0.9, "relief": 0.1, "intensity": 0.3,
                        "reasoning": "all paths failed, fallback to stop",
                    }
                simworld_action = laap_decision_to_simworld_action(laap_decision)
                action_json_str = json.dumps(simworld_action, ensure_ascii=False)

        # 如果仍然没有 action_json_str（fallback 关闭 + LAAP 失败）
        if action_json_str is None:
            laap_decision = {
                "action": ACTION_STOP, "params": {},
                "regret": 0.9, "relief": 0.1, "intensity": 0.3,
                "reasoning": "no decision available, fallback to stop",
            }
            simworld_action = laap_decision_to_simworld_action(laap_decision)
            action_json_str = json.dumps(simworld_action, ensure_ascii=False)

        elapsed = time.time() - start_time
        return action_json_str, elapsed

    # ─── 状态查询 ───────────────────────────────────────────

    def stats(self) -> Dict[str, Any]:
        """返回 LAAPBrain 决策统计."""
        return {
            "decision_count": self._decision_count,
            "laap_success_count": self._laap_success_count,
            "fallback_count": self._fallback_count,
            "has_parent_llm": self._has_parent_llm,
            "parent_init_error": self._parent_init_error,
            "has_causal_engine": self.causal_engine is not None,
            "has_world_model": self.world_model is not None,
            "has_cognitive_bus": self.cognitive_bus is not None,
            "fallback_to_llm": self.fallback_to_llm,
            "last_decision": self._last_decision,
        }


# ─── 去除 LLMMetaclass 自动套用的 retry 装饰器 ───────────────
# SimWorld 的 LLMMetaclass 会把所有 public 方法用 retry_api_call() 装饰，
# 这会给 LAAPBrain 的 generate_instructions / stats 加上 3 秒前置 sleep
# 和 OpenAI 异常重试。LAAPBrain 不直接调用 OpenAI API（LAAP 决策走因果
# 引擎；fallback 时 super().generate_instructions 已有自己的 retry），
# 所以这里把装饰器剥掉，恢复原始方法。
def _unwrap_retry_methods(cls):
    for attr_name in list(vars(cls)):
        attr = getattr(cls, attr_name, None)
        if callable(attr) and hasattr(attr, "__wrapped__"):
            try:
                # functools.wraps 保留了原始函数在 __wrapped__
                original = attr.__wrapped__
                setattr(cls, attr_name, original)
            except Exception:
                pass
    return cls


_unwrap_retry_methods(LAAPBrain)
