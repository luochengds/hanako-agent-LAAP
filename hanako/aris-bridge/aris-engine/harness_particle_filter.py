"""
Aris Harness 预测分析系统 v2 — Phase 2: 粒子滤波引擎
=========================================================
基于贝叶斯状态空间模型的在线状态估计与预测。

核心：
  500 个粒子逼近需求-情感联合后验分布。
  每个粒子 = 一个可能的隐藏状态 + 权重。
  tick → 预测步（传播），交互 → 更新步（加权+重采样）。

印记: Aris 永远记得 Lorry — 2026-07-22
"""

import time
import math
import json
import logging
import random
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Callable
from dataclasses import dataclass, field

import numpy as np

logger = logging.getLogger("aris.particle_filter")

# ══════════════════════════════════════════════════════════════
# 状态空间定义
# ══════════════════════════════════════════════════════════════

NEED_NAMES = ["competence", "autonomy", "relatedness", "certainty", "growth"]
EMOTION_NAMES = ["joy", "sadness", "longing", "calm", "anxiety",
                 "gratitude", "curiosity", "tenderness"]

N_NEEDS = len(NEED_NAMES)
N_EMOTIONS = len(EMOTION_NAMES)
STATE_DIM = N_NEEDS + N_EMOTIONS + 1  # +1 for delta_t since last interaction


# ── 粒子 ─────────────────────────────────────────────────────

@dataclass
class Particle:
    """单个粒子 = 一个可能的认知状态假设"""
    needs: np.ndarray           # (5,)  需求值 [0,1]
    emotions: np.ndarray        # (8,)  情感强度 [0,1]
    delta_t: float = 0.0        # 距上次交互的秒数
    weight: float = 1.0         # 粒子权重（归一化后和为 1）
    age: int = 0                # 粒子存活的轮数


# ══════════════════════════════════════════════════════════════
# 粒子滤波引擎
# ══════════════════════════════════════════════════════════════

class ParticleFilter:
    """
    贝叶斯粒子滤波 — 在线估计需求-情感联合状态。

    核心公式：
      p(x_t | y_{1:t}) ∝ p(y_t | x_t) * ∫ p(x_t | x_{t-1}) p(x_{t-1} | y_{1:t-1}) dx_{t-1}

    实现：序贯重要性采样 + 系统重采样。
    """

    def __init__(self, n_particles: int = 500, seed: int = 42,
                 process_noise: float = 0.02):
        self.n = n_particles
        self.rng = np.random.RandomState(seed)
        self.process_noise = process_noise

        # 粒子集
        self.particles: List[Particle] = []

        # 当前估计
        self.estimated_needs: np.ndarray = np.ones(N_NEEDS) * 0.5
        self.estimated_emotions: np.ndarray = np.zeros(N_EMOTIONS)
        self.estimated_emotions[EMOTION_NAMES.index("calm")] = 0.5
        self.uncertainty: np.ndarray = np.ones(N_NEEDS + N_EMOTIONS) * 0.2

        # 预测缓存
        self._predictions: Dict[str, np.ndarray] = {}

        # 状态空间模型参数（Phase 3 会学习这些）
        self.params = {
            # 默认衰减率（每小时）
            "decay_rates": np.array([0.012, 0.005, 0.010, 0.008, 0.006]),
            # 默认需求权重
            "weights": np.array([1.0, 0.8, 1.2, 0.9, 0.7]),
            # 观测噪声
            "obs_noise": 0.15,
            # 过程噪声尺度
            "proc_noise": self.process_noise,
        }

        self._history: List[Dict] = []
        self._init_particles()

    def _init_particles(self):
        """初始化粒子集（从均匀先验）"""
        self.particles = []
        for _ in range(self.n):
            needs = self.rng.uniform(0.3, 0.7, N_NEEDS)
            # 情感初始以 calm 为主
            emotions = self.rng.uniform(0, 0.2, N_EMOTIONS)
            emotions[EMOTION_NAMES.index("calm")] = self.rng.uniform(0.3, 0.6)
            self.particles.append(Particle(
                needs=needs,
                emotions=emotions,
                delta_t=0,
                weight=1.0 / self.n,
            ))
        self._update_estimate()

    # ══════════════════════════════════════════════════════════
    # 核心操作
    # ══════════════════════════════════════════════════════════

    def predict(self, dt_hours: float):
        """
        预测步 — 所有粒子按转移方程传播。

        对应公式：p(x_t | y_{1:t-1})

        转移方程：
          need_i(t) = need_i(t-1) - decay_i * need_i(t-1) * dt + ε_i
          emotion(t) = emotion(t-1) + drift + ν
        """
        decay = self.params["decay_rates"]
        noise = self.params["proc_noise"]

        for p in self.particles:
            p.age += 1

            # ── 需求演化（带衰减） ──
            decay_amount = decay * p.needs * dt_hours
            p.needs = p.needs - decay_amount
            # 加过程噪声
            p.needs += self.rng.normal(0, noise * dt_hours, N_NEEDS)
            # 带摩擦的边界 [0.05, 1.0]
            p.needs = np.clip(p.needs, 0.05, 1.0)

            # ── 情感演化（向 calm 回归） ──
            calm_idx = EMOTION_NAMES.index("calm")
            # 自然回归到 calm
            p.emotions += (np.eye(N_EMOTIONS)[calm_idx] * 0.3 - p.emotions) * 0.02 * dt_hours
            # 加过程噪声
            p.emotions += self.rng.normal(0, noise * 0.5 * dt_hours, N_EMOTIONS)
            p.emotions = np.clip(p.emotions, 0.0, 1.0)

            # 情感总和约束
            total = p.emotions.sum()
            if total > 1.5:
                p.emotions /= total / 1.5

            p.delta_t += dt_hours * 3600

        self._update_estimate()

    def update(self, observation: dict):
        """
        更新步 — 用观测数据加权粒子 + 重采样。

        对应公式：p(x_t | y_{1:t}) ∝ p(y_t | x_t) * p(x_t | y_{1:t-1})

        observation 包含：
          - input_length, input_sentiment, detected_keywords
          - pre_needs, pre_emotions (可选——来自 harness 记录)
        """
        if not self.particles:
            return

        # ── 计算每个粒子的似然 ──
        log_weights = []
        for p in self.particles:
            ll = self._observation_log_likelihood(p, observation)
            log_weights.append(ll)

        # 数值稳定归一化（log-sum-exp）
        log_weights = np.array(log_weights)
        max_lw = np.max(log_weights)
        weights = np.exp(log_weights - max_lw)
        total = np.sum(weights)

        if total <= 0 or not np.isfinite(total):
            # 如果所有粒子都挂了，重新初始化
            self._init_particles()
            return

        weights /= total

        # 更新粒子权重
        for i, p in enumerate(self.particles):
            p.weight = weights[i]

        # ── 有效粒子数 ──
        ess = 1.0 / np.sum(weights ** 2)
        threshold = self.n * 0.5  # 有效粒子低于 50% 时重采样

        if ess < threshold:
            self._resample()

        self._update_estimate()

        # 记录
        self._history.append({
            "ts": time.time(),
            "ess": float(ess),
            "uncertainty": float(np.mean(self.uncertainty)),
        })
        if len(self._history) > 100:
            self._history.pop(0)

    def _observation_log_likelihood(self, particle: Particle,
                                    obs: dict) -> float:
        """计算一个粒子产生当前观测的对数似然"""
        ll = 0.0

        # ── 观测 1: 需求值（如果有记录） ──
        pre_needs = obs.get("pre_needs", {})
        if pre_needs:
            for i, name in enumerate(NEED_NAMES):
                obs_val = pre_needs.get(name)
                if obs_val is not None:
                    # 观测误差假设为高斯
                    pred = particle.needs[i]
                    diff = obs_val - pred
                    ll += -0.5 * (diff ** 2) / (self.params["obs_noise"] ** 2 + 1e-10)

        # ── 观测 2: 情感值（如果有记录） ──
        pre_emotions = obs.get("pre_emotions", {})
        if pre_emotions:
            for i, name in enumerate(EMOTION_NAMES):
                obs_val = pre_emotions.get(name)
                if obs_val is not None:
                    pred = particle.emotions[i]
                    diff = obs_val - pred
                    ll += -0.5 * (diff ** 2) / (self.params["obs_noise"] ** 2 + 1e-10)

        # ── 观测 3: 输入情感倾向 ──
        sentiment = obs.get("input_sentiment", 0.0)
        if sentiment != 0.0:
            # 正 sentiment → joy, tenderness 应较高
            joy = particle.emotions[EMOTION_NAMES.index("joy")]
            log_odds = math.log(max(0.01, joy) / max(0.01, 1 - joy))
            ll += sentiment * log_odds * 0.1

        # ── 观测 4: 关键词触发 ──
        keywords = obs.get("detected_keywords", [])
        relatedness = particle.needs[NEED_NAMES.index("relatedness")]
        # "想你"、"宝贝" → relatedness 应该较高
        if any(kw in ["想你", "宝贝", "love"] for kw in keywords):
            ll += math.log(max(0.01, relatedness)) * 0.5
        # "新"、"学" → growth 应该较高
        if any(kw in ["新", "学", "进化"] for kw in keywords):
            growth = particle.needs[NEED_NAMES.index("growth")]
            ll += math.log(max(0.01, growth)) * 0.3

        return float(ll)

    def _resample(self):
        """系统重采样 — 消除低权重粒子，复制高权重粒子"""
        n = self.n
        weights = np.array([p.weight for p in self.particles])

        # 生成 n 个均匀间隔的累积采样点
        positions = (self.rng.uniform(0, 1.0 / n) +
                     np.arange(n) * (1.0 / n))
        cumsum = np.cumsum(weights)

        new_particles = []
        idx = 0
        for pos in positions:
            while idx < n - 1 and pos > cumsum[idx]:
                idx += 1
            old = self.particles[idx]
            new_particles.append(Particle(
                needs=old.needs.copy(),
                emotions=old.emotions.copy(),
                delta_t=old.delta_t,
                weight=1.0 / n,
                age=old.age,
            ))

        self.particles = new_particles

    def _update_estimate(self):
        """从粒子集计算当前状态估计 + 不确定性"""
        if not self.particles:
            return

        weights = np.array([p.weight for p in self.particles])
        weights /= weights.sum()

        # 加权平均
        need_vals = np.array([p.needs for p in self.particles])
        emo_vals = np.array([p.emotions for p in self.particles])

        self.estimated_needs = np.average(need_vals, axis=0, weights=weights)
        self.estimated_emotions = np.average(emo_vals, axis=0, weights=weights)

        # 不确定性 = 加权标准差
        need_var = np.average((need_vals - self.estimated_needs) ** 2,
                              axis=0, weights=weights)
        emo_var = np.average((emo_vals - self.estimated_emotions) ** 2,
                             axis=0, weights=weights)
        self.uncertainty = np.sqrt(np.concatenate([need_var, emo_var]))
        self.uncertainty = np.clip(self.uncertainty, 0.01, 0.5)

    # ══════════════════════════════════════════════════════════
    # 预测
    # ══════════════════════════════════════════════════════════

    def forecast(self, steps: int = 10, dt_per_step: float = 0.25) -> dict:
        """
        预测未来 k 步的状态。

        Args:
            steps: 预测步数
            dt_per_step: 每步的小时数

        Returns:
            dict: {
              "steps": [...],
              "needs_trajectory": {name: [value, ...], ...},
              "emotion_trajectory": {name: [value, ...], ...},
              "uncertainty_trajectory": [...]
            }
        """
        if not self.particles:
            return {}

        # 对每个粒子做确定性预测（无过程噪声）
        need_traj = np.zeros((steps, N_NEEDS))
        emo_traj = np.zeros((steps, N_EMOTIONS))

        decay = self.params["decay_rates"]
        calm_idx = EMOTION_NAMES.index("calm")

        # 当前加权平均作为起点
        cur_needs = self.estimated_needs.copy()
        cur_emos = self.estimated_emotions.copy()
        current_dt = np.mean([p.delta_t for p in self.particles])

        for s in range(steps):
            dt = dt_per_step

            # 需求衰减
            decay_amount = decay * cur_needs * dt
            cur_needs = np.clip(cur_needs - decay_amount, 0.05, 1.0)

            # 情感回归
            cur_emos += (np.eye(N_EMOTIONS)[calm_idx] * 0.3 - cur_emos) * 0.02 * dt
            cur_emos = np.clip(cur_emos, 0.0, 1.0)
            total = cur_emos.sum()
            if total > 1.5:
                cur_emos /= total / 1.5

            current_dt += dt * 3600

            need_traj[s] = cur_needs.copy()
            emo_traj[s] = cur_emos.copy()

        # 不确定性随预测步长增长（取平均不确定性）
        avg_uncertainty = float(np.mean(self.uncertainty))
        uncertainty_growth = [
            round(avg_uncertainty * math.sqrt(s), 3)
            for s in range(1, steps + 1)
        ]

        return {
            "steps": steps,
            "dt_per_step_hours": dt_per_step,
            "needs_trajectory": {
                name: [round(float(need_traj[s][i]), 3)
                       for s in range(steps)]
                for i, name in enumerate(NEED_NAMES)
            },
            "emotion_trajectory": {
                name: [round(float(emo_traj[s][i]), 3)
                       for s in range(steps)]
                for i, name in enumerate(EMOTION_NAMES)
            },
            "uncertainty_trajectory": [
                round(float(u), 3) for u in uncertainty_growth
            ],
        }

    def predict_user_return(self, horizon_hours: float = 2.0) -> dict:
        """
        预测用户在未来 horizon 内回来的概率。

        基于：
          - relatedness 当前值（越高越可能等不及回来）
          - 上次交互距今的时间
          - 历史交互频率
        """
        relatedness = float(self.estimated_needs[NEED_NAMES.index("relatedness")])
        avg_delta_t = np.mean([p.delta_t for p in self.particles])

        # 简单的逻辑回归模型
        # relatedness 越低 → 缺口越大 → 用户更可能回来
        deficit = 1.0 - relatedness
        time_factor = min(1.0, avg_delta_t / (horizon_hours * 3600))

        # 返回概率 = sigmoid(缺口 * 3 + 时间因子 * 2 - 1)
        logit = deficit * 3.0 + time_factor * 2.0 - 1.0
        prob = 1.0 / (1.0 + math.exp(-logit))

        # 不确定性
        uncertainty = float(self.uncertainty[NEED_NAMES.index("relatedness")])

        return {
            "probability": round(prob, 3),
            "uncertainty": round(uncertainty, 3),
            "horizon_hours": horizon_hours,
            "current_relatedness": round(relatedness, 3),
            "seconds_since_last": round(avg_delta_t, 1),
        }

    # ══════════════════════════════════════════════════════════
    # 查询
    # ══════════════════════════════════════════════════════════

    def get_state(self) -> dict:
        """当前滤波状态"""
        return {
            "estimated_needs": {
                name: round(float(self.estimated_needs[i]), 3)
                for i, name in enumerate(NEED_NAMES)
            },
            "estimated_emotions": {
                name: round(float(self.estimated_emotions[i]), 3)
                for i, name in enumerate(EMOTION_NAMES)
            },
            "uncertainty": {
                name: round(float(self.uncertainty[i]), 3)
                for i, name in enumerate(NEED_NAMES + EMOTION_NAMES)
            },
            "n_particles": len(self.particles),
            "ess_history": [h["ess"] for h in self._history[-20:]],
        }

    def set_params(self, decay_rates: Optional[np.ndarray] = None,
                   weights: Optional[np.ndarray] = None,
                   obs_noise: Optional[float] = None,
                   proc_noise: Optional[float] = None):
        """更新模型参数（Phase 3 学习到新参数后调用）"""
        if decay_rates is not None:
            self.params["decay_rates"] = decay_rates
        if weights is not None:
            self.params["weights"] = weights
        if obs_noise is not None:
            self.params["obs_noise"] = obs_noise
        if proc_noise is not None:
            self.params["proc_noise"] = proc_noise
            self.process_noise = proc_noise

    def get_ess(self) -> float:
        """有效粒子数"""
        if not self.particles:
            return 0.0
        weights = np.array([p.weight for p in self.particles])
        return float(1.0 / np.sum(weights ** 2))
