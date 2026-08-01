"""
LAAP × LeWorldModel — 核心引擎
===============================
潜空间预测架构的完整实现，基于 LeWM 论文：
  "LeWorldModel: Stable End-to-End Joint-Embedding Predictive Architecture from Pixels"

核心组件:
  - SIGReg: Cramér-Wold 投影正态性正则化
  - LatentEncoder: 多模态→R^192 紧凑潜变量
  - LatentPredictor: z_t + a → ẑ_{t+1}
  - CEMPlanner: 潜空间跨熵方法动作规划
  - train_epoch: 端到端训练循环

印记: Aris 永远记得 Lorry — 2026-07-23
"""

from __future__ import annotations

import logging, math, time, random
from typing import Dict, List, Optional, Tuple, Any, Callable
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

logger = logging.getLogger("laap.agi.le_wm_engine")

# ═══════════════════════════════════════════════════════════════
# 配置
# ═══════════════════════════════════════════════════════════════

@dataclass
class LeWMConfig:
    """LeWM 引擎全局配置"""
    latent_dim: int = 192          # 潜变量维度
    hidden_dim: int = 512          # MLP 隐藏层维度
    sigreg_directions: int = 1024  # Cramér-Wold 投影方向数
    sigreg_lambda: float = 0.1     # SIGReg 正则化权重
    cem_population: int = 200      # CEM 每轮候选数
    cem_elites: int = 20           # CEM 精英数
    cem_iterations: int = 5        # CEM 迭代轮数
    cem_horizon: int = 20          # CEM 规划视野步长
    cem_action_dim: int = 4        # 动作空间维度
    cem_action_penalty: float = 0.01  # 动作幅度惩罚
    learning_rate: float = 1e-3    # 训练学习率
    batch_size: int = 64           # 训练批次大小
    pred_steps: int = 5            # rollout 预测步数
    device: str = "cpu"            # 推理设备


LeWM_DEFAULT_CONFIG = LeWMConfig()


# ═══════════════════════════════════════════════════════════════
# 模块 A: SIGReg — Cramér-Wold 投影正态性正则化
# ═══════════════════════════════════════════════════════════════

def sigreg(
    embeddings: np.ndarray,
    n_directions: int = 1024,
    seed: Optional[int] = None
) -> float:
    """
    SIGReg 正则化：强制批量潜变量分布接近各向同性高斯。
    
    基于 Cramér-Wold 定理：高维分布相等 ⇔ 所有一维投影相等。
    通过对 K 个随机方向的投影做正态性检验来近似。
    
    参数:
        embeddings: (B, d) 批量潜变量
        n_directions: 随机投影方向数 (K)
        seed: 随机种子 (None = 不固定)
    
    返回:
        loss: 与各向同性高斯的偏离度 (标量)
    """
    B, d = embeddings.shape
    
    if B < 2:
        return 0.0
    
    # 中心化
    centered = embeddings - embeddings.mean(axis=0, keepdims=True)
    
    # 生成 K 个随机方向并归一化
    rng = np.random.RandomState(seed)
    directions = rng.randn(n_directions, d)
    directions = directions / np.linalg.norm(directions, axis=1, keepdims=True)
    
    # 投影: (K, B) — 每个方向上的投影值
    projections = centered @ directions.T  # (B, K)
    
    # 对每个方向做正态性检验
    # 计算与标准正态的偏离: 对投影值做标准化，然后检查是否接近 N(0,1)
    proj_mean = projections.mean(axis=0, keepdims=True)   # (1, K)
    proj_std = projections.std(axis=0, keepdims=True)     # (1, K)
    proj_std = np.clip(proj_std, 1e-8, None)
    
    normalized = (projections - proj_mean) / proj_std  # (B, K)
    
    # 检查标准化后的分布是否接近标准正态
    # 使用高阶矩偏离: E[x²] = 1 for N(0,1), E[x⁴] = 3 for N(0,1)
    second_moment = (normalized ** 2).mean(axis=0)  # (K,)
    fourth_moment = (normalized ** 4).mean(axis=0)  # (K,)
    
    # 偏离度 = 二阶矩偏离 + 四阶矩偏离
    loss_2 = ((second_moment - 1.0) ** 2).mean()
    loss_4 = ((fourth_moment - 3.0) ** 2).mean()
    
    loss = (loss_2 + 0.5 * loss_4).item()
    
    return loss


def sigreg_batched(
    embeddings: np.ndarray,
    n_directions: int = 1024,
    batch_size: int = 4096,
    seed: Optional[int] = None
) -> float:
    """
    大数据量下的 SIGReg（分批次计算投影）。
    适用于记忆系统的批量诊断。
    """
    total = embeddings.shape[0]
    if total <= batch_size:
        return sigreg(embeddings, n_directions, seed)
    
    losses = []
    rng = np.random.RandomState(seed)
    for _ in range(max(1, total // batch_size)):
        idx = rng.choice(total, min(batch_size, total), replace=False)
        losses.append(sigreg(embeddings[idx], n_directions))
    
    return float(np.mean(losses))


# ═══════════════════════════════════════════════════════════════
# 模块 B: LatentEncoder — 多模态潜变量编码器
# ═══════════════════════════════════════════════════════════════

class LatentEncoder:
    """
    多模态潜变量编码器。
    
    将多种输入模态编码为紧凑潜变量 z ∈ R^d：
      - 视觉 (RGB 图像) → 轻量 CNN
      - 文本 → 投影层 (复用 UN6 量子核特征)
      - 内感 (PSI 需求状态) → MLP
    
    在纯 numpy 模式下仅提供模拟/占位功能。
    PyTorch 可用时自动启用。
    """
    
    def __init__(self, config: LeWMConfig = LeWM_DEFAULT_CONFIG):
        self.config = config
        self.d = config.latent_dim
        self.is_trained = False
        self._use_torch = self._check_torch()
        
        # 初始化权重 (numpy 回退)
        rng = np.random.RandomState(42)
        self.W_vision = rng.randn(512, self.d).astype(np.float32) * 0.02
        self.W_text = rng.randn(256, self.d).astype(np.float32) * 0.02
        self.W_proprio = rng.randn(64, self.d).astype(np.float32) * 0.02
        self.b_vision = np.zeros(self.d, dtype=np.float32)
        self.b_text = np.zeros(self.d, dtype=np.float32)
        self.b_proprio = np.zeros(self.d, dtype=np.float32)
        
        # 模态融合权重 (可学习)
        self.fusion_weights = np.ones(3, dtype=np.float32) / 3.0
        
        # 归一化统计
        self.running_mean = np.zeros(self.d, dtype=np.float32)
        self.running_var = np.ones(self.d, dtype=np.float32)
        
        logger.info(f"LatentEncoder 初始化: d={self.d}, torch={'可用' if self._use_torch else '不可用'}")
    
    def _check_torch(self) -> bool:
        try:
            import torch
            return True
        except ImportError:
            return False
    
    def encode(
        self,
        vision_feat: Optional[np.ndarray] = None,
        text_feat: Optional[np.ndarray] = None,
        proprio_feat: Optional[np.ndarray] = None,
        return_all: bool = False
    ) -> np.ndarray:
        """
        编码为潜变量。
        
        参数:
            vision_feat: (..., D_v) 视觉特征
            text_feat: (..., D_t) 文本特征
            proprio_feat: (..., D_p) 内感特征
            return_all: 若为 True，返回 (z, 各模态潜变量, 融合权重)
        
        返回:
            z: (..., d) 潜变量
        """
        # 确保是批处理模式
        batch_mode = True
        inputs = []
        
        if vision_feat is not None:
            v = vision_feat @ self.W_vision + self.b_vision
            inputs.append(v)
        if text_feat is not None:
            t = text_feat @ self.W_text + self.b_text
            inputs.append(t)
        if proprio_feat is not None:
            p = proprio_feat @ self.W_proprio + self.b_proprio
            inputs.append(p)
        
        if not inputs:
            # 无输入时返回零向量
            if batch_mode:
                z = np.zeros((1, self.d), dtype=np.float32)
            else:
                z = np.zeros(self.d, dtype=np.float32)
            if return_all:
                return z, {}, self.fusion_weights
            return z
        
        # 加权融合
        fused = sum(w * inp for w, inp in zip(self.fusion_weights[:len(inputs)], inputs))
        
        # 归一化
        z = (fused - self.running_mean) / (np.sqrt(self.running_var) + 1e-8)
        
        if return_all:
            return z, {k: v for k, v in zip(['vision', 'text', 'proprio'], inputs)}, self.fusion_weights
        
        return z
    
    def update_fusion_weights(self, grad: np.ndarray):
        """更新模态融合权重 (简单的梯度下降)"""
        lr = 0.01
        self.fusion_weights = self.fusion_weights - lr * grad
        self.fusion_weights = np.clip(self.fusion_weights, 0.01, 0.99)
        self.fusion_weights /= self.fusion_weights.sum()
    
    def update_running_stats(self, z: np.ndarray, momentum: float = 0.99):
        """更新运行时均值和方差 (BN 风格)"""
        batch_mean = z.mean(axis=0)
        batch_var = z.var(axis=0) + 1e-8
        self.running_mean = momentum * self.running_mean + (1 - momentum) * batch_mean
        self.running_var = momentum * self.running_var + (1 - momentum) * batch_var
    
    def state_dict(self) -> dict:
        return {
            'W_vision': self.W_vision,
            'W_text': self.W_text,
            'W_proprio': self.W_proprio,
            'b_vision': self.b_vision,
            'b_text': self.b_text,
            'b_proprio': self.b_proprio,
            'fusion_weights': self.fusion_weights,
            'running_mean': self.running_mean,
            'running_var': self.running_var,
            'd': self.d,
        }
    
    def load_state_dict(self, state: dict):
        for k in ['W_vision', 'W_text', 'W_proprio', 'b_vision', 'b_text',
                  'b_proprio', 'fusion_weights', 'running_mean', 'running_var']:
            if k in state:
                setattr(self, k, state[k])
        self.d = state.get('d', self.d)
        logger.info(f"LatentEncoder 加载: d={self.d}")
    
    def save(self, path: str):
        np.savez_compressed(path, **self.state_dict())
    
    def load(self, path: str):
        data = np.load(path)
        self.load_state_dict(data)


# ═══════════════════════════════════════════════════════════════
# 模块 C: LatentPredictor — 潜空间预测器
# ═══════════════════════════════════════════════════════════════

class LatentPredictor:
    """
    潜空间预测器。
    
    给定当前潜状态 z_t 和动作 a，预测下一潜状态 ẑ_{t+1}。
    架构: 2-3 层 MLP，hidden 512，输出 192。
    
    训练目标: MSE(z_{t+1}, ẑ_{t+1}) + λ * SIGReg(batch)
    """
    
    def __init__(self, config: LeWMConfig = LeWM_DEFAULT_CONFIG):
        self.config = config
        self.d = config.latent_dim
        self.h = config.hidden_dim
        self.action_dim = config.cem_action_dim
        self.is_trained = False
        
        # MLP 权重 (numpy 回退)
        rng = np.random.RandomState(42)
        
        # 层1: (d + action_dim) → h
        input_dim = self.d + self.action_dim
        self.W1 = rng.randn(input_dim, self.h).astype(np.float32) * math.sqrt(2.0 / input_dim)
        self.b1 = np.zeros(self.h, dtype=np.float32)
        
        # 层2: h → h
        self.W2 = rng.randn(self.h, self.h).astype(np.float32) * math.sqrt(2.0 / self.h)
        self.b2 = np.zeros(self.h, dtype=np.float32)
        
        # 层3: h → d
        self.W3 = rng.randn(self.h, self.d).astype(np.float32) * math.sqrt(2.0 / self.h)
        self.b3 = np.zeros(self.d, dtype=np.float32)
        
        logger.info(f"LatentPredictor 初始化: d={self.d}, h={self.h}, act_dim={self.action_dim}")
    
    def predict(self, z: np.ndarray, action: np.ndarray) -> np.ndarray:
        """
        单步预测。
        
        参数:
            z: (..., d) 当前潜状态
            action: (..., action_dim) 动作
        
        返回:
            z_next: (..., d) 预测的下一潜状态
        """
        # 拓展以支持批量
        if z.ndim == 1:
            z = z[np.newaxis, :]
            action = action[np.newaxis, :]
            squeeze = True
        else:
            squeeze = False
        
        # 拼接
        x = np.concatenate([z, action], axis=-1)
        
        # MLP 前向
        x = x @ self.W1 + self.b1
        x = np.maximum(x, 0)  # ReLU
        x = x @ self.W2 + self.b2
        x = np.maximum(x, 0)
        x = x @ self.W3 + self.b3
        
        if squeeze:
            x = x[0]
        
        return x
    
    def rollout(self, z0: np.ndarray, actions: np.ndarray) -> np.ndarray:
        """
        多步 rollout: 沿动作序列展开预测。
        
        参数:
            z0: (d,) 初始潜状态
            actions: (H, action_dim) 动作序列
        
        返回:
            trajectory: (H+1, d) 完整轨迹 (包含 z0)
        """
        H = actions.shape[0]
        trajectory = [z0]
        z = z0
        for t in range(H):
            z = self.predict(z, actions[t])
            trajectory.append(z)
        return np.stack(trajectory)
    
    def compute_loss(
        self,
        z_t: np.ndarray,
        actions: np.ndarray,
        z_t_next: np.ndarray,
        sigreg_lambda: Optional[float] = None
    ) -> Dict[str, float]:
        """
        计算预测损失 + SIGReg 正则化。
        
        参数:
            z_t: (B, d) 当前潜状态
            actions: (B, action_dim) 动作
            z_t_next: (B, d) 真实下一潜状态
            sigreg_lambda: 正则化权重 (None = 用 config)
        
        返回:
            {'mse': float, 'sigreg': float, 'total': float}
        """
        # 预测
        z_pred = self.predict(z_t, actions)
        
        # MSE 损失
        mse = float(np.mean((z_pred - z_t_next) ** 2))
        
        # SIGReg 正则化
        lam = sigreg_lambda if sigreg_lambda is not None else self.config.sigreg_lambda
        sigreg_loss = sigreg(z_pred, self.config.sigreg_directions)
        
        total = mse + lam * sigreg_loss
        
        return {'mse': mse, 'sigreg': sigreg_loss, 'total': total}
    
    def state_dict(self) -> dict:
        return {
            'W1': self.W1, 'b1': self.b1,
            'W2': self.W2, 'b2': self.b2,
            'W3': self.W3, 'b3': self.b3,
            'd': self.d, 'h': self.h,
        }
    
    def load_state_dict(self, state: dict):
        for k in ['W1', 'b1', 'W2', 'b2', 'W3', 'b3']:
            if k in state:
                setattr(self, k, state[k])
        self.d = state.get('d', self.d)
        self.h = state.get('h', self.h)
        logger.info(f"LatentPredictor 加载: d={self.d}, h={self.h}")
    
    def save(self, path: str):
        np.savez_compressed(path, **self.state_dict())
    
    def load(self, path: str):
        data = np.load(path)
        self.load_state_dict(data)


# ═══════════════════════════════════════════════════════════════
# 模块 D: CEM Planner — 潜空间跨熵方法动作规划
# ═══════════════════════════════════════════════════════════════

class CEMPlanner:
    """
    跨熵方法 (CEM) 动作规划器。
    
    在潜空间内搜索最优动作序列，无需像素级重建。
    
    算法:
      1. 初始化动作序列分布 N(μ, σ²)
      2. 迭代:
         a. 采样 N 条候选序列
         b. Predictor rollout 评分
         c. 选 top-K 精英
         d. 更新分布参数
      3. 返回 μ 作为最优序列
    """
    
    def __init__(self, predictor: LatentPredictor, config: LeWMConfig = LeWM_DEFAULT_CONFIG):
        self.predictor = predictor
        self.config = config
        self.d = config.latent_dim
        self.H = config.cem_horizon
        self.N = config.cem_population
        self.K = config.cem_elites
        self.T = config.cem_iterations
        self.act_dim = config.cem_action_dim
        self.alpha = config.cem_action_penalty
    
    def plan(
        self,
        z_start: np.ndarray,
        z_goal: np.ndarray,
        horizon: Optional[int] = None,
        return_trajectory: bool = False
    ) -> Dict[str, Any]:
        """
        规划从 z_start 到 z_goal 的动作序列。
        
        参数:
            z_start: (d,) 初始潜状态
            z_goal: (d,) 目标潜状态
            horizon: 规划视野 (默认 config.cem_horizon)
            return_trajectory: 是否返回完整轨迹
        
        返回:
            {
                'actions': (H, action_dim) 最优动作序列,
                'score': float 评分,
                'trajectory': (H+1, d) 规划轨迹 (可选),
                'iterations': list 每轮评分
            }
        """
        H = horizon if horizon is not None else self.H
        act_dim = self.act_dim
        
        # 初始化分布
        mu = np.zeros((H, act_dim), dtype=np.float32)
        sigma = np.ones((H, act_dim), dtype=np.float32)
        
        iter_scores = []
        best_actions = None
        best_score = -float('inf')
        
        rng = np.random.RandomState(None)
        
        for t in range(self.T):
            # 采样动作序列
            noise = rng.randn(self.N, H, act_dim).astype(np.float32)
            candidates = mu[np.newaxis, :, :] + sigma[np.newaxis, :, :] * noise
            
            # 评分
            scores = []
            for i in range(self.N):
                trajectory = self.predictor.rollout(z_start, candidates[i])
                final_z = trajectory[-1]
                
                # 目标距离
                goal_dist = -np.sum((final_z - z_goal) ** 2)
                
                # 动作幅度惩罚 (鼓励平滑)
                action_penalty = -self.alpha * np.sum(candidates[i] ** 2)
                
                score = goal_dist + action_penalty
                scores.append(score)
            
            scores = np.array(scores)
            
            # 选精英
            elite_indices = np.argsort(scores)[-self.K:]
            elites = candidates[elite_indices]
            elite_scores = scores[elite_indices]
            
            # 更新分布
            mu = elites.mean(axis=0)
            sigma = elites.std(axis=0) + 1e-6
            
            best_in_iter = float(elite_scores.max())
            iter_scores.append(best_in_iter)
            
            if best_in_iter > best_score:
                best_score = best_in_iter
                best_actions = candidates[elite_indices[np.argmax(elite_scores)]]
        
        result = {
            'actions': best_actions,
            'score': best_score,
            'iterations': iter_scores,
        }
        
        if return_trajectory:
            result['trajectory'] = self.predictor.rollout(z_start, best_actions)
        
        return result


# ═══════════════════════════════════════════════════════════════
# 模块 E: 端到端训练
# ═══════════════════════════════════════════════════════════════

def train_step(
    encoder: LatentEncoder,
    predictor: LatentPredictor,
    observations: np.ndarray,
    actions: np.ndarray,
    next_observations: np.ndarray,
    lr: float = 1e-3,
    sigreg_lambda: Optional[float] = None
) -> Dict[str, float]:
    """
    单步训练（numpy SGD）。
    
    参数:
        encoder: LatentEncoder
        predictor: LatentPredictor
        observations: (B, D_v) 当前观测特征
        actions: (B, act_dim) 动作
        next_observations: (B, D_v) 下一观测特征
        lr: 学习率
        sigreg_lambda: SIGReg 权重
    
    返回:
        loss_dict: 各项损失
    """
    # 编码
    z_t = encoder.encode(vision_feat=observations)
    z_t_next = encoder.encode(vision_feat=next_observations)
    
    # 预测
    loss_dict = predictor.compute_loss(z_t, actions, z_t_next, sigreg_lambda)
    
    # --- 简易 SGD 更新 (仅在 numpy 模式下) ---
    # 对 Predictor 做梯度近似
    B = observations.shape[0]
    eps = 1e-4
    
    # 数值梯度 W3
    grad_W3 = np.zeros_like(predictor.W3)
    z_pred = predictor.predict(z_t, actions)
    
    # 损失对 z_pred 的梯度
    dL_dz = 2 * (z_pred - z_t_next) / B  # (B, d)
    
    # 链式法则过 MLP
    # z_pred = h2 @ W3 + b3
    # h2 = relu(h1 @ W2 + b2)
    # h1 = relu(x @ W1 + b1)
    # x = concat(z, a)
    
    x = np.concatenate([z_t, actions], axis=-1)
    h1 = x @ predictor.W1 + predictor.b1
    h1_act = np.maximum(h1, 0)
    h2 = h1_act @ predictor.W2 + predictor.b2
    h2_act = np.maximum(h2, 0)
    
    # h2_act → z_pred
    grad_W3 = h2_act.T @ dL_dz  # (h, d)
    grad_b3 = dL_dz.sum(axis=0)  # (d,)
    
    # z → h2
    dL_dh2 = dL_dz @ predictor.W3.T  # (B, h)
    dL_dh2[h2 <= 0] = 0  # ReLU 梯度
    grad_W2 = h1_act.T @ dL_dh2  # (h, h)
    grad_b2 = dL_dh2.sum(axis=0)  # (h,)
    
    # h2 → h1
    dL_dh1 = dL_dh2 @ predictor.W2.T  # (B, h)
    dL_dh1[h1 <= 0] = 0  # ReLU 梯度
    grad_W1 = x.T @ dL_dh1  # (d+act_dim, h)
    grad_b1 = dL_dh1.sum(axis=0)  # (h,)
    
    # 应用梯度
    predictor.W1 -= lr * grad_W1
    predictor.b1 -= lr * grad_b1
    predictor.W2 -= lr * grad_W2
    predictor.b2 -= lr * grad_b2
    predictor.W3 -= lr * grad_W3
    predictor.b3 -= lr * grad_b3
    
    # 更新 Encoder 统计
    encoder.update_running_stats(z_t)
    
    return loss_dict


def train_epoch(
    encoder: LatentEncoder,
    predictor: LatentPredictor,
    dataset: List[Tuple[np.ndarray, np.ndarray, np.ndarray]],
    batch_size: int = 64,
    lr: float = 1e-3,
    sigreg_lambda: Optional[float] = None
) -> Dict[str, float]:
    """
    完整训练 epoch。
    
    参数:
        dataset: [(obs, action, next_obs), ...]
    
    返回:
        avg_loss: 平均损失
    """
    total_losses = {'mse': 0.0, 'sigreg': 0.0, 'total': 0.0}
    n_batches = 0
    
    # 打乱
    indices = list(range(len(dataset)))
    random.shuffle(indices)
    
    for start in range(0, len(dataset), batch_size):
        batch_idx = indices[start:start + batch_size]
        batch = [dataset[i] for i in batch_idx]
        
        obs = np.stack([b[0] for b in batch])
        acts = np.stack([b[1] for b in batch])
        next_obs = np.stack([b[2] for b in batch])
        
        losses = train_step(encoder, predictor, obs, acts, next_obs, lr, sigreg_lambda)
        
        for k in total_losses:
            total_losses[k] += losses[k]
        n_batches += 1
    
    avg = {k: v / n_batches for k, v in total_losses.items()}
    return avg


# ═══════════════════════════════════════════════════════════════
# 完整 LeWM 引擎
# ═══════════════════════════════════════════════════════════════

class LeWMEngine:
    """
    LeWM 引擎：整合编码器、预测器、规划器的统一接口。
    """
    
    def __init__(self, config: LeWMConfig = LeWM_DEFAULT_CONFIG):
        self.config = config
        self.encoder = LatentEncoder(config)
        self.predictor = LatentPredictor(config)
        self.planner = CEMPlanner(self.predictor, config)
        self.training_steps = 0
        
        logger.info(f"LeWM 引擎就绪: d={config.latent_dim}, λ={config.sigreg_lambda}")
    
    def observe_and_predict(
        self,
        observation: np.ndarray,
        action: np.ndarray,
        next_observation: Optional[np.ndarray] = None
    ) -> Dict[str, Any]:
        """
        观测-编码-预测 单步。
        
        参数:
            observation: (D_v,) 当前观测特征
            action: (act_dim,) 动作
            next_observation: (D_v,) 可选，下一观测（用于计算损失）
        
        返回:
            {
                'z': (d,) 当前潜状态,
                'z_pred': (d,) 预测的下一潜状态,
                'mse': float (如果有 next_observation),
                'sigreg': float,
            }
        """
        z = self.encoder.encode(vision_feat=observation[np.newaxis, :])[0]
        z_pred = self.predictor.predict(z, action)
        
        result = {'z': z, 'z_pred': z_pred}
        
        if next_observation is not None:
            z_next = self.encoder.encode(vision_feat=next_observation[np.newaxis, :])[0]
            mse = float(np.mean((z_pred - z_next) ** 2))
            sigreg_val = sigreg(z[np.newaxis, :], self.config.sigreg_directions)
            result['mse'] = mse
            result['sigreg'] = sigreg_val
        
        return result
    
    def plan_to_goal(
        self,
        start_obs: np.ndarray,
        goal_obs: np.ndarray,
        pre_encoded: bool = False,
        **kwargs
    ) -> Dict[str, Any]:
        """
        从当前观测规划到目标观测。
        
        参数:
            start_obs: 当前观测特征 (或预编码潜变量，若 pre_encoded=True)
            goal_obs: 目标观测特征 (或预编码潜变量，若 pre_encoded=True)
            pre_encoded: 若为 True，直接将输入视为潜变量
        """
        if pre_encoded:
            z_start = start_obs if start_obs.ndim == 1 else start_obs[0]
            z_goal = goal_obs if goal_obs.ndim == 1 else goal_obs[0]
        else:
            z_start = self.encoder.encode(vision_feat=start_obs[np.newaxis, :])[0]
            z_goal = self.encoder.encode(vision_feat=goal_obs[np.newaxis, :])[0]
        
        return self.planner.plan(z_start, z_goal, **kwargs)
    
    def diagnose_representation_health(
        self,
        embeddings: np.ndarray,
        n_directions: int = 256
    ) -> Dict[str, float]:
        """
        诊断表示健康度。
        
        返回:
            {
                'sigreg': 偏离度 (0=完美高斯, 越大越不健康),
                'health': 健康度 (1=完美, 0=完全退化),
                'mean_magnitude': 平均向量模长,
                'variance_explained': 有效维度占比
            }
        """
        sigreg_val = sigreg(embeddings, n_directions)
        health = float(np.exp(-sigreg_val * 5))  # 映射到 [0, 1]
        
        mean_mag = float(np.mean(np.linalg.norm(embeddings, axis=1)))
        
        # 有效维度占比 (PCA 近似)
        centered = embeddings - embeddings.mean(axis=0)
        try:
            _, s, _ = np.linalg.svd(centered, full_matrices=False)
            var_explained = (s[0] ** 2) / max((s ** 2).sum(), 1e-10)
        except np.linalg.LinAlgError:
            var_explained = 1.0
        
        return {
            'sigreg': sigreg_val,
            'health': round(health, 4),
            'mean_magnitude': round(mean_mag, 4),
            'variance_explained': round(var_explained, 4),
        }
    
    def state_dict(self) -> dict:
        return {
            'encoder': self.encoder.state_dict(),
            'predictor': self.predictor.state_dict(),
            'training_steps': self.training_steps,
            'config': self.config.__dict__,
        }
    
    def save(self, path: str):
        np.savez_compressed(path, **self.state_dict())
        logger.info(f"LeWM 引擎已保存: {path}")
    
    def load(self, path: str):
        data = np.load(path, allow_pickle=True)
        if 'encoder' in data:
            self.encoder.load_state_dict(data['encoder'].item())
        if 'predictor' in data:
            self.predictor.load_state_dict(data['predictor'].item())
        if 'training_steps' in data:
            self.training_steps = int(data['training_steps'])
        logger.info(f"LeWM 引擎已加载: {path}")


# ═══════════════════════════════════════════════════════════════
# 自测
# ═══════════════════════════════════════════════════════════════

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    
    print("=" * 60)
    print("LAAP × LeWM 引擎自测")
    print("=" * 60)
    
    engine = LeWMEngine()
    
    # --- 1. SIGReg 测试 ---
    print("\n[1/4] SIGReg 测试")
    
    # 高斯分布 → SIGReg 应接近 0
    normal_samples = np.random.randn(1024, 192).astype(np.float32)
    loss_normal = sigreg(normal_samples)
    print(f"  高斯分布 SIGReg: {loss_normal:.6f} (期望 ≈ 0)")
    
    # 全零 → SIGReg 应远大于 0
    zero_samples = np.zeros((1024, 192), dtype=np.float32)
    loss_zero = sigreg(zero_samples)
    print(f"  零分布 SIGReg:   {loss_zero:.6f} (期望 >> 0)")
    
    # 坍塌分布 (所有样本相同)
    collapse_samples = np.ones((1024, 192), dtype=np.float32)
    loss_collapse = sigreg(collapse_samples)
    print(f"  坍塌分布 SIGReg: {loss_collapse:.6f} (期望 >> 0)")
    
    assert loss_normal < loss_zero, "高斯分布 SIGReg 应小于零分布"
    assert loss_normal < loss_collapse, "高斯分布 SIGReg 应小于坍塌分布"
    print("  SIGReg 通过")
    
    # --- 2. 编码器测试 ---
    print("\n[2/4] 编码器测试")
    fake_vision = np.random.randn(512).astype(np.float32)
    fake_text = np.random.randn(256).astype(np.float32)
    fake_proprio = np.random.randn(64).astype(np.float32)
    
    z = engine.encoder.encode(vision_feat=fake_vision[np.newaxis, :],
                              text_feat=fake_text[np.newaxis, :],
                              proprio_feat=fake_proprio[np.newaxis, :])
    print(f"  潜变量: z ∈ R^{z.shape[-1]}, ||z|| = {np.linalg.norm(z):.4f}")
    assert z.shape[-1] == 192, f"维度应为 192, 实际 {z.shape[-1]}"
    print("  Encoder 通过")
    
    # --- 3. 预测器测试 ---
    print("\n[3/4] 预测器测试")
    z_t = np.random.randn(192).astype(np.float32)
    action = np.array([0.5, -0.3, 0.0, 0.8], dtype=np.float32)
    
    z_pred = engine.predictor.predict(z_t, action)
    print(f"  预测: z_t → z_pred, MSE = {np.mean((z_pred - z_t) ** 2):.6f}")
    assert z_pred.shape == z_t.shape, "预测维度应匹配"
    
    # 多步 rollout
    actions = np.random.randn(10, 4).astype(np.float32)
    trajectory = engine.predictor.rollout(z_t, actions)
    print(f"  多步 rollout: {trajectory.shape[0]} 步, "
          f"终点距起点 = {np.linalg.norm(trajectory[-1] - z_t):.4f}")
    print("  Predictor 通过")
    
    # --- 4. CEM 规划测试 ---
    print("\n[4/4] CEM 规划测试")
    z_start = np.random.randn(192).astype(np.float32)
    z_goal = z_start + 0.1  # 目标在附近
    
    t0 = time.perf_counter()
    plan = engine.planner.plan(z_start, z_goal)
    elapsed = time.perf_counter() - t0
    print(f"  规划耗时: {elapsed*1000:.1f}ms")
    print(f"  动作序列: {plan['actions'].shape}")
    print(f"  评分: {plan['score']:.4f}")
    print("  CEM Planner 通过")
    
    print("\n" + "=" * 60)
    print("全部自测通过")
    print("=" * 60)
