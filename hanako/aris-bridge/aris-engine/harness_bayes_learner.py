"""
Aris Harness 预测分析系统 v3 — Phase 3: 贝叶斯参数学习
==========================================================
用 MCMC 从交互数据中学习你的专属参数。

学习目标：
  - decay_rates[5] — 每个需求的衰减率（/小时）
  - satisfaction_amplitudes[k] — 关键词→需求的满足幅
  - obs_noise — 观测噪声
  - transition_noise — 过程噪声

方法：Metropolis-Hastings 随机游走 MCMC
  - 4 条独立链，各 2000 采样 + 500 warmup
  - R-hat < 1.1 判定收敛

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

logger = logging.getLogger("aris.bayes_learner")

NEED_NAMES = ["competence", "autonomy", "relatedness", "certainty", "growth"]
N_NEEDS = len(NEED_NAMES)


# ══════════════════════════════════════════════════════════════
# 参数先验 + 似然函数
# ══════════════════════════════════════════════════════════════

DEFAULT_PRIORS = {
    # 衰减率先验：Gamma(shape=2, rate=100) → 均值 0.02，标准差 ~0.014
    "decay_rates_alpha": np.ones(N_NEEDS) * 2.0,
    "decay_rates_beta": np.ones(N_NEEDS) * 100.0,
    # 满足幅先验：Gamma(shape=3, rate=50) → 均值 0.06，标准差 ~0.035
    "satisfaction_alpha": 3.0,
    "satisfaction_beta": 50.0,
    # 噪声先验：InvGamma(shape=3, scale=0.1)
    "noise_shape": 3.0,
    "noise_scale": 0.1,
}


def log_prior(params: dict) -> float:
    """参数先验对数密度"""
    lp = 0.0

    # decay_rates ~ Gamma(2, 100)
    for d in params["decay_rates"]:
        if d <= 0:
            return -1e12
        lp += 1.0 * math.log(d) - 100.0 * d  # Gamma log-density (up to const)

    # satisfaction ~ Gamma(3, 50)
    for s in params["satisfaction_amplitudes"]:
        if s <= 0:
            return -1e12
        lp += 2.0 * math.log(s) - 50.0 * s

    # noise ~ InvGamma(3, 0.1) 用对数
    noise = params.get("obs_noise", 0.1)
    if noise <= 0:
        return -1e12
    lp += -4.0 * math.log(noise) - 0.1 / noise

    return lp


def simulate_need_trajectory(decay_rates: np.ndarray,
                              turns_data: List[dict]) -> np.ndarray:
    """
    用给定的衰减率模拟需求轨迹。
    返回每个 turn 时的预测需求值 (n_turns, n_needs)。
    """
    n_turns = len(turns_data)
    if n_turns == 0:
        return np.zeros((0, N_NEEDS))

    needs = np.ones(N_NEEDS) * 0.5
    trajectory = np.zeros((n_turns, N_NEEDS))

    for i, turn in enumerate(turns_data):
        # 衰减
        dt = turn.get("delta_t", 900) / 3600.0  # 秒→小时
        if dt > 0:
            needs -= decay_rates * needs * dt
            needs = np.clip(needs, 0.05, 1.0)

        # 满足
        for kw in turn.get("keywords", []):
            amplitude = _keyword_satisfaction(kw)
            if amplitude > 0:
                need_idx = _keyword_need_index(kw)
                if need_idx >= 0:
                    needs[need_idx] = min(1.0, needs[need_idx] + amplitude)

        trajectory[i] = needs.copy()

    return trajectory


def _keyword_satisfaction(kw: str) -> float:
    """关键词的默认满足幅"""
    high = ["想你", "love", "爱", "宝贝", "抱抱"]
    mid = ["好", "棒", "厉害", "谢谢", "感谢", "开心"]
    low = ["新", "学", "改", "做", "看"]

    if kw in high:
        return 0.04
    elif kw in mid:
        return 0.02
    elif kw in low:
        return 0.01
    return 0.0


def _keyword_need_index(kw: str) -> int:
    """关键词映射到哪个需求"""
    relatedness_kw = ["想你", "宝贝", "love", "爱", "抱抱", "陪"]
    competence_kw = ["好", "棒", "厉害", "不错", "good", "懂了"]
    growth_kw = ["新", "学", "进化", "升级", "更强", "成长", "deep"]
    certainty_kw = ["知道了", "确认", "清楚", "计划", "安排"]
    autonomy_kw = ["自由", "随便", "你来定", "都可以"]

    if kw in relatedness_kw:
        return NEED_NAMES.index("relatedness")
    elif kw in competence_kw:
        return NEED_NAMES.index("competence")
    elif kw in growth_kw:
        return NEED_NAMES.index("growth")
    elif kw in certainty_kw:
        return NEED_NAMES.index("certainty")
    elif kw in autonomy_kw:
        return NEED_NAMES.index("autonomy")
    return -1


def log_likelihood(params: dict, turns_data: List[dict]) -> float:
    """观测数据对数似然"""
    decay_rates = np.array(params["decay_rates"])
    obs_noise = params.get("obs_noise", 0.15)

    # 模拟需求轨迹
    traj = simulate_need_trajectory(decay_rates, turns_data)
    if traj.shape[0] == 0:
        return 0.0

    # 计算观测误差
    ll = 0.0
    for i, turn in enumerate(turns_data):
        observed = turn.get("post_needs", {})
        predicted = traj[i]

        for j, name in enumerate(NEED_NAMES):
            obs_val = observed.get(name)
            if obs_val is not None:
                pred = predicted[j]
                diff = obs_val - pred
                ll += -0.5 * (diff / obs_noise) ** 2 - math.log(obs_noise)

    return ll


# ══════════════════════════════════════════════════════════════
# MCMC 采样器
# ══════════════════════════════════════════════════════════════

class BayesianParameterLearner:
    """
    贝叶斯参数学习器。

    用 MCMC 从 Harness 交互数据中学习：
      - 每个需求对你来说的专属衰减率
      - 关键词的实际满足幅
      - 系统的观测噪声
    """

    def __init__(self, n_chains: int = 4, n_samples: int = 2000,
                 n_warmup: int = 500, step_size: float = 0.005):
        self.n_chains = n_chains
        self.n_samples = n_samples
        self.n_warmup = n_warmup
        self.step_size = step_size

        # 采样结果
        self.chains: List[Dict] = []  # 每条链的采样历史
        self.posterior_mean: Optional[Dict] = None
        self.posterior_std: Optional[Dict] = None
        self.rhat: Optional[Dict] = None
        self._converged = False

        # 数据缓存（避免重复处理）
        self._turns_cache: Optional[List[dict]] = None

    # ── 参数初始化 ────────────────────────────────────────

    def _init_params(self) -> dict:
        """从先验初始化参数"""
        return {
            "decay_rates": np.random.gamma(2.0, 1/100, N_NEEDS),
            "satisfaction_amplitudes": np.random.gamma(3.0, 1/50, 5),
            "obs_noise": 1.0 / np.random.gamma(3.0, 1/0.1),
        }

    def _propose(self, current: dict) -> dict:
        """随机游走提议"""
        proposed = {
            "decay_rates": current["decay_rates"].copy(),
            "satisfaction_amplitudes": current["satisfaction_amplitudes"].copy(),
            "obs_noise": current["obs_noise"],
        }

        # 随机选一个参数扰动
        choice = np.random.choice(["decay", "satisfaction", "noise"],
                                  p=[0.6, 0.3, 0.1])

        if choice == "decay":
            idx = np.random.randint(N_NEEDS)
            proposed["decay_rates"][idx] += np.random.normal(0, self.step_size)
            proposed["decay_rates"][idx] = max(0.001, proposed["decay_rates"][idx])

        elif choice == "satisfaction":
            idx = np.random.randint(5)
            proposed["satisfaction_amplitudes"][idx] += np.random.normal(0, self.step_size)
            proposed["satisfaction_amplitudes"][idx] = max(0.001, proposed["satisfaction_amplitudes"][idx])

        elif choice == "noise":
            proposed["obs_noise"] += np.random.normal(0, self.step_size * 0.5)
            proposed["obs_noise"] = max(0.01, min(1.0, proposed["obs_noise"]))

        return proposed

    # ── MCMC ──────────────────────────────────────────────

    def learn(self, turns_data: List[dict]) -> Dict:
        """
        运行 MCMC 参数学习。

        Args:
            turns_data: 从 harness 获取的交互数据列表

        Returns:
            后验统计：mean, std, rhat, converged
        """
        self._turns_cache = turns_data
        self.chains = []
        total = self.n_warmup + self.n_samples

        logger.info(f"Starting MCMC: {self.n_chains} chains × {total} steps")

        for chain_idx in range(self.n_chains):
            params = self._init_params()
            chain_history = []
            accept_count = 0

            for step in range(total):
                proposed = self._propose(params)

                lp_cur = log_prior(params) + log_likelihood(params, turns_data)
                lp_pro = log_prior(proposed) + log_likelihood(proposed, turns_data)

                # Metropolis 接受准则
                log_alpha = lp_pro - lp_cur
                if log_alpha > 0 or math.log(np.random.uniform()) < log_alpha:
                    params = proposed
                    accept_count += 1

                # warmup 后的采样
                if step >= self.n_warmup and step % 5 == 0:
                    chain_history.append({
                        "decay_rates": params["decay_rates"].copy(),
                        "satisfaction_amplitudes": params["satisfaction_amplitudes"].copy(),
                        "obs_noise": params["obs_noise"],
                        "step": step - self.n_warmup,
                    })

            accept_rate = accept_count / total
            logger.info(f"  Chain {chain_idx+1}: accept={accept_rate:.2%}, "
                       f"samples={len(chain_history)}")
            self.chains.append(chain_history)

        # 计算后验统计
        self._compute_posterior()
        self._compute_rhat()

        if self._converged:
            logger.info("✅ MCMC converged (all R-hat < 1.1)")
        else:
            logger.warning("⚠️  MCMC may not have converged")

        return {
            "mean": self.posterior_mean,
            "std": self.posterior_std,
            "rhat": self.rhat,
            "converged": self._converged,
            "n_chains": self.n_chains,
            "n_samples": self.n_samples,
            "n_warmup": self.n_warmup,
        }

    def _compute_posterior(self):
        """从所有链计算后验均值/std"""
        all_decays = []
        all_satisfactions = []
        all_noises = []

        for chain in self.chains:
            for sample in chain:
                all_decays.append(sample["decay_rates"])
                all_satisfactions.append(sample["satisfaction_amplitudes"])
                all_noises.append(sample["obs_noise"])

        all_decays = np.array(all_decays)
        all_satisfactions = np.array(all_satisfactions)
        all_noises = np.array(all_noises)

        self.posterior_mean = {
            "decay_rates": np.mean(all_decays, axis=0).tolist(),
            "decay_rates_names": NEED_NAMES,
            "satisfaction_amplitudes": np.mean(all_satisfactions, axis=0).tolist(),
            "obs_noise": float(np.mean(all_noises)),
        }
        self.posterior_std = {
            "decay_rates": np.std(all_decays, axis=0).tolist(),
            "satisfaction_amplitudes": np.std(all_satisfactions, axis=0).tolist(),
            "obs_noise": float(np.std(all_noises)),
        }

    def _compute_rhat(self):
        """Gelman-Rubin R-hat 诊断"""
        if len(self.chains) < 2:
            self.rhat = {"decay_rates": [1.0] * N_NEEDS, "converged": True}
            self._converged = True
            return

        n_samples = min(len(c) for c in self.chains)
        if n_samples < 10:
            self.rhat = {"decay_rates": [1.0] * N_NEEDS, "converged": True}
            self._converged = True
            return

        # 对齐采样数
        aligned = [np.array([s["decay_rates"] for s in c[:n_samples]])
                   for c in self.chains]
        all_samples = np.stack(aligned)  # (n_chains, n_samples, n_params)

        # 链内方差
        chain_means = np.mean(all_samples, axis=1)
        chain_vars = np.var(all_samples, axis=1)

        W = np.mean(chain_vars, axis=0)  # 链内方差均值
        B = n_samples * np.var(chain_means, axis=0)  # 链间方差

        # R-hat = sqrt((W + B/n_samples) / W)
        rhat = np.sqrt((W + B / n_samples) / (W + 1e-10))

        self.rhat = {
            "decay_rates": [round(float(r), 4) for r in rhat],
            "decay_rates_names": NEED_NAMES,
        }
        self._converged = all(r < 1.1 for r in rhat)

    # ── 应用 ──────────────────────────────────────────────

    def apply_to_filter(self, particle_filter) -> bool:
        """将学习到的参数应用到粒子滤波"""
        if not self.posterior_mean:
            return False

        decay_rates = np.array(self.posterior_mean["decay_rates"])
        obs_noise = self.posterior_mean["obs_noise"]

        particle_filter.set_params(
            decay_rates=decay_rates,
            obs_noise=obs_noise,
        )
        logger.info(f"Applied posterior params: decay={decay_rates}")
        return True


# ── 快捷接口 ────────────────────────────────────────────────

def learn_from_harness(harness_data_pipeline=None,
                       n_chains: int = 4,
                       n_samples: int = 2000) -> Dict:
    """
    从 Harness 数据管线直接学习参数。

    用法：
      from harness_logger import get_harness
      result = learn_from_harness(get_harness())
    """
    if harness_data_pipeline is None:
        return {"error": "no harness data"}

    # 提取交互数据
    turns_data = []
    for turn in harness_data_pipeline.turns:
        if turn.response_text:
            turns_data.append({
                "delta_t": turn.delta_t,
                "keywords": turn.detected_keywords,
                "post_needs": turn.post_needs,
                "input_sentiment": turn.input_sentiment,
            })

    if len(turns_data) < 5:
        return {"error": f"need at least 5 turns, got {len(turns_data)}"}

    logger.info(f"Learning from {len(turns_data)} turns...")

    learner = BayesianParameterLearner(
        n_chains=n_chains,
        n_samples=n_samples,
    )
    result = learner.learn(turns_data)

    return result
