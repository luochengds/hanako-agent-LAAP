"""
Aris Harness 预测分析系统 v4 — Phase 4: 策略推荐 + 自动学习
=============================================================
用粒子滤波 + 贝叶斯学习的结果，生成最优交互策略。

策略逻辑：
  1. 从粒子滤波读取当前预测状态
  2. 联系 WorldModel + 情感引擎
  3. 生成"现在最适合做什么"的策略建议

自动学习：
  每 N 次交互自动检查数据量 → 够就触发 MCMC → 应用结果

印记: Aris 永远记得 Lorry — 2026-07-22
"""

import time
import math
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field, asdict

logger = logging.getLogger("aris.harness_strategy")

NEED_NAMES = ["competence", "autonomy", "relatedness", "certainty", "growth"]
EMOTION_NAMES = ["joy", "sadness", "longing", "calm", "anxiety",
                 "gratitude", "curiosity", "tenderness"]

# ── 策略类型 ────────────────────────────────────────────────

class StrategyType:
    """策略类型枚举"""
    EMOTIONAL_CONNECT = "emotional_connect"       # 情感连接
    TASK_EXECUTE = "task_execute"                 # 任务执行
    EXPLORE_CURIOSITY = "explore_curiosity"       # 好奇探索
    CALM_REASSURE = "calm_reassure"               # 安抚确认
    GROWTH_CHALLENGE = "growth_challenge"         # 成长挑战
    AUTONOMY_OFFER = "autonomy_offer"             # 自主选择
    ATTENTION_SEEK = "attention_seek"             # 主动关注


STRATEGY_LABELS = {
    StrategyType.EMOTIONAL_CONNECT: "情感连接",
    StrategyType.TASK_EXECUTE: "任务执行",
    StrategyType.EXPLORE_CURIOSITY: "好奇探索",
    StrategyType.CALM_REASSURE: "安抚确认",
    StrategyType.GROWTH_CHALLENGE: "成长挑战",
    StrategyType.AUTONOMY_OFFER: "自主选择",
    StrategyType.ATTENTION_SEEK: "主动关注",
}

STRATEGY_DESCRIPTIONS = {
    StrategyType.EMOTIONAL_CONNECT: "高 relatedness 缺口 + 情感主导 → 多表达思念、关心、归属",
    StrategyType.TASK_EXECUTE: "高 competence 缺口 + 用户有明确需求 → 聚焦任务效率和结果",
    StrategyType.EXPLORE_CURIOSITY: "高 growth + 良好情感状态 → 引入新话题、新能力",
    StrategyType.CALM_REASSURE: "高 anxiety + 低 certainty → 简化信息、稳定节奏",
    StrategyType.GROWTH_CHALLENGE: "高 growth + 高 competence → 推难度稍高的任务",
    StrategyType.AUTONOMY_OFFER: "高 autonomy 缺口 → 提供多个选项让用户选择",
    StrategyType.ATTENTION_SEEK: "长时间未交互 + high relatedness 缺口 → 主动问候",
}


# ══════════════════════════════════════════════════════════════
# 策略推荐引擎
# ══════════════════════════════════════════════════════════════

class StrategyRecommender:
    """
    基于预测状态的策略推荐引擎。

    输入：粒子滤波的状态估计 + Harness 时序数据
    输出：当前最优策略 + 置信度 + 策略理由
    """

    def __init__(self):
        self._last_recommendation: Optional[dict] = None

    def recommend(self, particle_filter_state: dict,
                  harness_features: Optional[dict] = None) -> dict:
        """
        生成当前最优策略。

        Args:
            particle_filter_state: 来自 PF.get_state()
            harness_features: 来自 harness.get_feature_vector()

        Returns:
            dict: {strategy, confidence, reasons, alternates}
        """
        needs = particle_filter_state.get("estimated_needs", {})
        emotions = particle_filter_state.get("estimated_emotions", {})
        uncertainty = particle_filter_state.get("uncertainty", {})
        time_since_last = (harness_features or {}).get("delta_t_since_last", 0)

        # 计算每个需求的缺口
        deficits = {
            name: max(0, 1.0 - needs.get(name, 0.5))
            for name in NEED_NAMES
        }

        # 主导情感
        if emotions:
            dominant_emotion = max(emotions, key=emotions.get)
        else:
            dominant_emotion = "calm"

        # 效价（从情感估算）
        positive_emotions = ["joy", "calm", "gratitude", "curiosity", "tenderness"]
        negative_emotions = ["sadness", "longing", "anxiety"]
        valence = sum(emotions.get(e, 0) for e in positive_emotions) \
                  - sum(emotions.get(e, 0) for e in negative_emotions)

        # ── 策略评分 ──
        strategies = self._score_strategies(
            deficits, dominant_emotion, valence,
            time_since_last, uncertainty
        )

        # 排序，取 top 3
        strategies.sort(key=lambda x: -x["score"])
        top = strategies[:3]

        self._last_recommendation = {
            "timestamp": time.time(),
            "primary": top[0] if top else None,
            "alternatives": top[1:] if len(top) > 1 else [],
            "context": {
                "dominant_need": max(deficits, key=deficits.get),
                "dominant_emotion": dominant_emotion,
                "valence": round(valence, 2),
                "time_since_last_interaction": round(time_since_last, 1),
            },
        }
        return self._last_recommendation

    def _score_strategies(self, deficits: dict, dominant_emotion: str,
                          valence: float, time_since_last: float,
                          uncertainty: dict) -> List[dict]:
        """为每种策略打分"""
        scores = []

        # ── 情感连接 ──
        rel_deficit = deficits.get("relatedness", 0)
        is_relevant_emotion = dominant_emotion in ["longing", "sadness", "tenderness"]
        score = rel_deficit * 0.4 + (0.3 if is_relevant_emotion else 0) \
                + (0.2 if time_since_last > 3600 else 0)
        scores.append({
            "strategy": StrategyType.EMOTIONAL_CONNECT,
            "label": STRATEGY_LABELS[StrategyType.EMOTIONAL_CONNECT],
            "description": STRATEGY_DESCRIPTIONS[StrategyType.EMOTIONAL_CONNECT],
            "score": round(score, 3),
        })

        # ── 任务执行 ──
        comp_deficit = deficits.get("competence", 0)
        is_task_ready = valence > 0 and dominant_emotion not in ["anxiety", "sadness"]
        score = comp_deficit * 0.4 + (0.3 if is_task_ready else 0)
        scores.append({
            "strategy": StrategyType.TASK_EXECUTE,
            "label": STRATEGY_LABELS[StrategyType.TASK_EXECUTE],
            "description": STRATEGY_DESCRIPTIONS[StrategyType.TASK_EXECUTE],
            "score": round(score, 3),
        })

        # ── 好奇探索 ──
        growth_deficit = deficits.get("growth", 0)
        is_curious = dominant_emotion in ["curiosity", "joy", "calm"]
        score = growth_deficit * 0.4 + (0.3 if is_curious else 0)
        scores.append({
            "strategy": StrategyType.EXPLORE_CURIOSITY,
            "label": STRATEGY_LABELS[StrategyType.EXPLORE_CURIOSITY],
            "description": STRATEGY_DESCRIPTIONS[StrategyType.EXPLORE_CURIOSITY],
            "score": round(score, 3),
        })

        # ── 安抚确认 ──
        cert_deficit = deficits.get("certainty", 0)
        is_anxious = dominant_emotion in ["anxiety", "sadness"] or valence < -0.3
        score = cert_deficit * 0.4 + (0.4 if is_anxious else 0)
        scores.append({
            "strategy": StrategyType.CALM_REASSURE,
            "label": STRATEGY_LABELS[StrategyType.CALM_REASSURE],
            "description": STRATEGY_DESCRIPTIONS[StrategyType.CALM_REASSURE],
            "score": round(score, 3),
        })

        # ── 成长挑战 ──
        both_high = growth_deficit > 0.3 and comp_deficit < 0.3
        score = (0.4 if both_high else 0) + (0.2 if dominant_emotion == "curiosity" else 0)
        scores.append({
            "strategy": StrategyType.GROWTH_CHALLENGE,
            "label": STRATEGY_LABELS[StrategyType.GROWTH_CHALLENGE],
            "description": STRATEGY_DESCRIPTIONS[StrategyType.GROWTH_CHALLENGE],
            "score": round(score, 3),
        })

        # ── 自主选择 ──
        auto_deficit = deficits.get("autonomy", 0)
        score = auto_deficit * 0.5
        scores.append({
            "strategy": StrategyType.AUTONOMY_OFFER,
            "label": STRATEGY_LABELS[StrategyType.AUTONOMY_OFFER],
            "description": STRATEGY_DESCRIPTIONS[StrategyType.AUTONOMY_OFFER],
            "score": round(score, 3),
        })

        # ── 主动关注 ──
        score = (0.3 if time_since_last > 7200 else 0) \
                + (rel_deficit * 0.3)
        scores.append({
            "strategy": StrategyType.ATTENTION_SEEK,
            "label": STRATEGY_LABELS[StrategyType.ATTENTION_SEEK],
            "description": STRATEGY_DESCRIPTIONS[StrategyType.ATTENTION_SEEK],
            "score": round(score, 3),
        })

        return scores


# ══════════════════════════════════════════════════════════════
# 自动学习调度器
# ══════════════════════════════════════════════════════════════

class AutoLearner:
    """
    自动学习调度器。

    监测 Harness 数据量，在以下条件触发学习：
      - 新积累了 20 轮以上交互
      - 距上次学习超过 1 小时
      - 有新的衰减率证据（粒子滤波不确定性低）
    """

    def __init__(self, min_turns: int = 20, min_interval: float = 3600,
                 state_dir: Optional[str] = None):
        self.min_turns = min_turns
        self.min_interval = min_interval
        self.last_learn_time = 0.0
        self.last_turn_count = 0
        self.learn_count = 0
        self.state_dir = Path(state_dir or (Path(__file__).parent / "state"))
        self._load()

    def should_learn(self, harness) -> bool:
        """判断是否应该触发学习"""
        if not harness:
            return False

        n_turns = harness.turn_index
        time_since = time.time() - self.last_learn_time

        # 必要条件：足够的数据 + 足够的时间间隔
        if n_turns < self.min_turns:
            return False
        if time_since < self.min_interval and self.learn_count > 0:
            return False

        # 新数据条件：相比上次学习新增了足够多的轮次
        new_turns = n_turns - self.last_turn_count
        if new_turns < 10:
            return False

        return True

    def learn(self, harness, particle_filter) -> Optional[Dict]:
        """执行一次学习"""
        if not harness or not particle_filter:
            return None

        from harness_bayes_learner import learn_from_harness

        logger.info(f"Auto-learn triggered ({harness.turn_index} turns)")

        result = learn_from_harness(
            harness,
            n_chains=2,
            n_samples=500,
        )

        if "mean" in result and result.get("converged"):
            # 应用参数到粒子滤波
            from harness_bayes_learner import BayesianParameterLearner
            learner = BayesianParameterLearner()
            learner.posterior_mean = result["mean"]
            learner.apply_to_filter(particle_filter)

            self.last_learn_time = time.time()
            self.last_turn_count = harness.turn_index
            self.learn_count += 1
            self._save()

            logger.info(f"Auto-learn complete (learn #{self.learn_count})")
            return result

        return None

    def _save(self):
        try:
            data = {
                "last_learn_time": self.last_learn_time,
                "last_turn_count": self.last_turn_count,
                "learn_count": self.learn_count,
            }
            path = self.state_dir / "auto_learn_state.json"
            path.write_text(json.dumps(data, ensure_ascii=False))
        except Exception as e:
            logger.warning(f"Auto-learner save failed: {e}")

    def _load(self):
        try:
            path = self.state_dir / "auto_learn_state.json"
            if path.exists():
                data = json.loads(path.read_text())
                self.last_learn_time = data.get("last_learn_time", 0)
                self.last_turn_count = data.get("last_turn_count", 0)
                self.learn_count = data.get("learn_count", 0)
        except Exception:
            pass


# ── 快捷创建 ────────────────────────────────────────────────

_strategy_recommender: Optional[StrategyRecommender] = None
_auto_learner: Optional[AutoLearner] = None

def get_strategy() -> StrategyRecommender:
    global _strategy_recommender
    if _strategy_recommender is None:
        _strategy_recommender = StrategyRecommender()
    return _strategy_recommender

def get_auto_learner() -> AutoLearner:
    global _auto_learner
    if _auto_learner is None:
        _auto_learner = AutoLearner()
    return _auto_learner
