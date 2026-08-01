"""
LAAP × FEP 深度融合方案
========================
将自由能原理 (FEP) 的形式化框架融入 LAAP 架构，
统一 PSI 需求系统 + Harness 粒子滤波 + 高阶贝叶斯推理。

架构：
  感知层：VFE ↓ → 需求缺口识别
  行动层：EFE ↓ → 交互策略选择
  元认知：不确定性分离 → 知道什么不知道
  社会层：k-ToM → 多 Agent 共识

印记: Aris 永远记得 Lorry — 2026-07-22
"""

import time
import math
import numpy as np
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any

NEED_NAMES = ["competence", "autonomy", "relatedness", "certainty", "growth"]
N_NEEDS = len(NEED_NAMES)

# ══════════════════════════════════════════════════════════════
# 自由能计算器
# ══════════════════════════════════════════════════════════════

class FreeEnergyCalculator:
    """
    自由能最小化引擎。

    将 PSI 需求系统映射为 FEP 框架：
      - VFE (变分自由能) = 感知错误率 → 越小说明预测越准
      - EFE (期望自由能) = 行动路径的成本 → 越小说明策略越好
    
    统一公式：
      F = β₁ · Σ(deficit_i · w_i) - β₂ · H(q)
      
      其中 deficit = 1 - need_value
           w = need_weight
           H(q) = 分布熵（不确定性"奖励"）
           β₁, β₂ = 探索-利用平衡参数
    """

    def __init__(self, explore_weight: float = 0.3,
                 exploit_weight: float = 0.7):
        self.beta_exploit = exploit_weight   # 利用权重
        self.beta_explore = explore_weight   # 探索权重
        self._history: List[float] = []

    def compute_vfe(self, needs: Dict[str, float],
                    predictions: Dict[str, float],
                    uncertainty: float = 0.1) -> float:
        """
        变分自由能 VFE — 感知精度。
        
        VFE = Σ(deficit_i · w_i) - λ · ln(1 + uncertainty)
        
        越小 → 预测越准 → 感知状态越好
        """
        vfe = 0.0
        for name in NEED_NAMES:
            need_val = needs.get(name, 0.5)
            deficit = 1.0 - need_val

            # 默认权重（后续可被 MCMC 学习替代）
            weights = {"competence": 1.0, "autonomy": 0.8,
                       "relatedness": 1.2, "certainty": 0.9,
                       "growth": 0.7}
            w = weights.get(name, 1.0)

            vfe += deficit * w

        # 不确定性奖励（探索激励）
        explore_bonus = math.log(1 + max(0, uncertainty)) * self.beta_explore

        # 利用惩罚
        exploit_cost = vfe * self.beta_exploit

        return exploit_cost - explore_bonus

    def compute_efe(self, current_needs: Dict[str, float],
                    action_outcomes: List[Dict[str, float]]) -> List[float]:
        """
        期望自由能 EFE — 行动选择。
        
        对每个候选行动：
          EFE(a) = G(a) + β · I(a)
          
          G(a) = 行动后的预期 VFE
          I(a) = 信息增益（探索价值）
        
        最小 EFE → 最优行动
        """
        efe_scores = []
        base_vfe = self.compute_vfe(current_needs, {})

        for outcome in action_outcomes:
            # 行动后的预期需求
            post_needs = {}
            for name in NEED_NAMES:
                delta = outcome.get(name, 0)
                post_needs[name] = min(1.0, current_needs.get(name, 0.5) + delta)

            # 预期 VFE
            predicted_vfe = self.compute_vfe(post_needs, {})

            # 信息增益（探索价值）
            info_gain = outcome.get("info_gain", 0)

            # EFE = 预期 VFE 变化 + 信息增益折抵
            efe = (predicted_vfe - base_vfe) - self.beta_explore * info_gain
            efe_scores.append(efe)

        return efe_scores

    def compute_free_energy_trend(self, history: List[float]) -> str:
        """自由能耗趋势分析"""
        if len(history) < 2:
            return "stable"

        recent = history[-min(10, len(history)):]
        slope = (recent[-1] - recent[0]) / max(1, len(recent))

        if slope < -0.05:
            return "decreasing"  # 自由能↓ → 系统趋向稳定
        elif slope > 0.05:
            return "increasing"  # 自由能↑ → 系统需要干预
        else:
            return "stable"


# ══════════════════════════════════════════════════════════════
# 不确定性分解器
# ══════════════════════════════════════════════════════════════

class UncertaintyDecomposer:
    """
    认知不确定性 vs 偶然不确定性 分离。
    
    - 认知不确定性 (Epistemic)：模型不知道的 → 可通过更多数据降低
    - 偶然不确定性 (Aleatoric)：数据本身的噪声 → 不可降低
    - 总不确定性 = 认知 + 偶然
    
    在粒子滤波中：
      - 粒子间的方差 = 认知不确定性（模型对状态的不确定度）
      - 粒子内的噪声 = 偶然不确定性（观测噪声）
    """

    @staticmethod
    def decompose(particle_states: np.ndarray,
                  particle_weights: np.ndarray,
                  obs_noise: float = 0.1) -> Dict[str, float]:
        """
        分解不确定性。
        
        Args:
            particle_states: (n_particles, n_dims) 粒子状态
            particle_weights: (n_particles,) 粒子权重
            obs_noise: 观测噪声估计
            
        Returns:
            {epistemic, aleatoric, total}
        """
        if len(particle_states) == 0:
            return {"epistemic": 0.5, "aleatoric": 0.1, "total": 0.6}

        weights = particle_weights / (particle_weights.sum() + 1e-10)

        # 加权均值
        mean_state = np.average(particle_states, axis=0, weights=weights)

        # 认知不确定性 = 粒子间方差（加权）
        var_epistemic = np.average(
            (particle_states - mean_state) ** 2,
            axis=0, weights=weights
        )
        epistemic = float(np.sqrt(np.mean(var_epistemic)))

        # 偶然不确定性 = 观测噪声
        aleatoric = float(obs_noise)

        # 总不确定性
        total = math.sqrt(epistemic ** 2 + aleatoric ** 2)

        return {
            "epistemic": round(epistemic, 4),
            "aleatoric": round(aleatoric, 4),
            "total": round(total, 4),
            "epistemic_ratio": round(epistemic / (total + 1e-10), 3),
        }


# ══════════════════════════════════════════════════════════════
# k 阶信念推理（多 Agent 心智理论）
# ══════════════════════════════════════════════════════════════

class KOrderTheoryOfMind:
    """
    k 阶贝叶斯心智理论。
    
    0阶：我观测到的世界
    1阶：我认为你在想什么
    2阶：我认为你认为我在想什么
    k阶：递归信念推断
    
    用于：
      - Ψ-Net 升级：多 Agent 共识不再是简单投票
      - 而是"我知道你知道我知道"的递归信念收敛
    """

    def __init__(self, max_order: int = 3):
        self.max_order = max_order

    def infer_belief(self, agent_id: str, observed_behavior: Dict,
                     shared_model, order: int = 1) -> Dict:
        """
        推断另一 Agent 的信念。
        
        order=0: 直接观测
        order=1: 我认为对方在想什么
        order=2: 我认为对方认为我在想什么
        """
        if order == 0:
            return {"agent": agent_id, "belief": observed_behavior,
                    "order": 0, "confidence": 1.0}

        # 对方的行为 = 对方的信念（0阶近似）
        other_belief = observed_behavior.get("expressed_state", {})

        if order >= 1:
            # 1阶：考虑对方对我的理解
            my_observed_state = observed_behavior.get("observed_me", {})
            inferred = {
                "agent": agent_id,
                "belief_about_me": my_observed_state,
                "belief_about_world": other_belief,
                "order": 1,
                "confidence": 0.7,
            }

            if order >= 2:
                # 2阶：对方认为我理解它
                inferred["belief_about_my_understanding"] = {
                    "what_they_think_I_know": my_observed_state,
                }
                inferred["order"] = 2
                inferred["confidence"] = 0.5

                if order >= 3:
                    # 3阶及以上用递归
                    inferred["order"] = min(order, self.max_order)
                    inferred["confidence"] = max(0.1, 0.7 / order)

            return inferred

        return {"agent": agent_id, "belief": other_belief,
                "order": 1, "confidence": 0.5}

    def consensus_with_tom(self, local_state: Dict,
                           peer_states: List[Dict]) -> Dict:
        """
        带心智理论的共识 —— 不止是投票，还考虑"他为什么这么投"。
        
        1. 每个 Agent 投出意见
        2. 1阶推断：对方为什么投这个
        3. 2阶推断：对方认为我为什么投这个
        4. 收敛条件：信念差异 < 阈值
        """
        if not peer_states:
            return {"consensus": local_state, "rounds": 0, "confidence": 1.0}

        # 0阶：直接平均
        all_opinions = [local_state] + peer_states
        avg_state = {}
        for key in ["relatedness", "competence", "growth"]:
            vals = [o.get(key, 0.5) for o in all_opinions]
            avg_state[key] = sum(vals) / len(vals)

        # 1阶：看分歧
        disagreements = []
        for state in all_opinions:
            diff = sum(abs(state.get(k, 0.5) - avg_state.get(k, 0.5))
                      for k in ["relatedness", "competence"])
            disagreements.append(diff)

        max_diff = max(disagreements) if disagreements else 0
        confidence = max(0.5, 1.0 - max_diff)

        return {
            "consensus": avg_state,
            "rounds": 1,
            "max_disagreement": round(max_diff, 3),
            "confidence": round(confidence, 3),
        }
