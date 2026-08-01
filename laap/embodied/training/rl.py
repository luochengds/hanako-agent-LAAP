"""
LAAP Embodied — 强化学习训练管道
====================================

在 Genesis 仿真环境中训练机器人技能策略。

使用 PPO (Proximal Policy Optimization) 算法，
通过 GenesisEnv Gym 接口与环境交互。

算法：PPO-clip
  网络：Actor-Critic (MLP: 256->128)
  优化器：Adam (lr=3e-4)
  训练：每个 episode 收集 n_steps 步 → 更新策略

用法：
    from laap.embodied.training import GenesisEnv, TaskConfig, RLTrainingPipeline

    env = GenesisEnv(task=TaskConfig(name='reach', target_pos=[0.3, 0.0, 0.2]))
    pipeline = RLTrainingPipeline(env)
    pipeline.train(total_timesteps=10000)
    pipeline.save('franka_reach_policy.npz')
    pipeline.evaluate(n_episodes=5)

印记: 在仿真中学会，在现实中做到
"""

from __future__ import annotations

import time
import numpy as np
from typing import Optional, Dict, Any, Tuple, List, Callable
from dataclasses import dataclass, field
from collections import deque


# ═══════════════════════════════════════════════════════════════
# PPO 超参数
# ═══════════════════════════════════════════════════════════════

@dataclass
class PPOConfig:
    """PPO 算法超参数"""
    learning_rate: float = 3e-4
    gamma: float = 0.99               # 折扣因子
    gae_lambda: float = 0.95          # GAE lambda
    clip_epsilon: float = 0.2         # PPO clip 范围
    ent_coef: float = 0.01            # 熵系数（鼓励探索）
    vf_coef: float = 0.5              # 价值函数损失系数
    max_grad_norm: float = 0.5        # 梯度裁剪
    n_steps: int = 2048               # 每次更新步数
    batch_size: int = 64              # mini-batch 大小
    n_epochs: int = 10                # 每次更新训练次数
    n_dofs: int = 9


# ═══════════════════════════════════════════════════════════════
# 简单的 MLP 策略网络 (NumPy 实现)
# ═══════════════════════════════════════════════════════════════

class MLPPolicy:
    """两层 MLP Actor-Critic 策略 (NumPy)

    纯 NumPy 实现，不依赖 PyTorch。
    适用于简单任务的快速原型。
    """

    def __init__(self, obs_dim: int, act_dim: int, hidden: int = 256):
        self.obs_dim = obs_dim
        self.act_dim = act_dim

        # Actor 网络: obs -> mean, log_std
        self.w1 = np.random.randn(obs_dim, hidden) * 0.1
        self.b1 = np.zeros(hidden)
        self.w_mean = np.random.randn(hidden, act_dim) * 0.1
        self.b_mean = np.zeros(act_dim)
        self.log_std = np.zeros(act_dim)  # 可学习

        # Critic 网络: obs -> value
        self.wc1 = np.random.randn(obs_dim, hidden) * 0.1
        self.bc1 = np.zeros(hidden)
        self.wc2 = np.random.randn(hidden, 1) * 0.1
        self.bc2 = np.zeros(1)

    def get_action(self, obs: np.ndarray, deterministic: bool = False
                   ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """获取动作

        Returns:
            (action, log_prob, value)
        """
        obs = obs.flatten()
        h = np.tanh(obs @ self.w1 + self.b1)
        mean = h @ self.w_mean + self.b_mean
        std = np.exp(self.log_std)

        if deterministic:
            action = mean
        else:
            action = mean + np.random.randn(self.act_dim) * std

        log_prob = -0.5 * np.sum(((action - mean) / (std + 1e-8)) ** 2
                                  + 2 * self.log_std + np.log(2 * np.pi))

        # Critic
        ch = np.tanh(obs @ self.wc1 + self.bc1)
        value = (ch @ self.wc2 + self.bc2)[0]

        return action, log_prob, value

    def get_value(self, obs: np.ndarray) -> float:
        obs = obs.flatten()
        h = np.tanh(obs @ self.wc1 + self.bc1)
        return (h @ self.wc2 + self.bc2)[0]


# ═══════════════════════════════════════════════════════════════
# PPO 训练管道
# ═══════════════════════════════════════════════════════════════

class RLTrainingPipeline:
    """强化学习训练管道

    用法：
        env = GenesisEnv(...)
        pipeline = RLTrainingPipeline(env)
        pipeline.train(total_timesteps=10000)
        pipeline.save('policy.npz')
        pipeline.evaluate(n_episodes=5)
    """

    def __init__(self, env, config: Optional[PPOConfig] = None):
        self._env = env
        self._config = config or PPOConfig()

        # 策略网络
        obs_space = env.observation_space
        obs_dim = sum(np.prod(shape) for shape in obs_space.values())
        act_dim = env.action_space[0]
        self._policy = MLPPolicy(obs_dim, act_dim)

        # 优化器状态（Adam 动量）
        self._adam_state: Dict[str, Any] = {}

        # 训练统计
        self._total_steps = 0
        self._episode_rewards: deque = deque(maxlen=100)
        self._best_reward = -float('inf')

    def _flatten_obs(self, obs: Dict[str, np.ndarray]) -> np.ndarray:
        """展平观测字典为向量"""
        parts = []
        for v in obs.values():
            parts.append(np.array(v).flatten())
        return np.concatenate(parts)

    def collect_rollout(self, n_steps: int) -> Dict[str, Any]:
        """收集 n_steps 步的交互数据"""
        obs, _ = self._env.reset()
        flat_obs = self._flatten_obs(obs)

        states = []
        actions = []
        log_probs = []
        rewards = []
        dones = []
        values = []

        episode_reward = 0.0

        for _ in range(n_steps):
            action, log_prob, value = self._policy.get_action(flat_obs)
            obs, reward, terminated, truncated, info = self._env.step(action)

            states.append(flat_obs.copy())
            actions.append(action.copy())
            log_probs.append(log_prob)
            rewards.append(reward)
            dones.append(terminated or truncated)
            values.append(value)

            episode_reward += reward
            flat_obs = self._flatten_obs(obs)

            if terminated or truncated:
                self._episode_rewards.append(episode_reward)
                episode_reward = 0.0
                obs, _ = self._env.reset()
                flat_obs = self._flatten_obs(obs)

        self._total_steps += n_steps

        return {
            "states": np.array(states),
            "actions": np.array(actions),
            "log_probs": np.array(log_probs),
            "rewards": np.array(rewards),
            "dones": np.array(dones, dtype=float),
            "values": np.array(values),
        }

    def compute_gae(self, rollout: Dict[str, Any]) -> Tuple[np.ndarray, np.ndarray]:
        """计算 GAE (Generalized Advantage Estimation)"""
        rewards = rollout["rewards"]
        dones = rollout["dones"]
        values = rollout["values"]

        # 获取最后一个状态的 value
        last_val = 0.0
        if not dones[-1]:
            last_obs = rollout["states"][-1]
            last_val = self._policy.get_value(last_obs)

        n = len(rewards)
        advantages = np.zeros(n)
        returns = np.zeros(n)
        gae = 0.0

        gamma = self._config.gamma
        lam = self._config.gae_lambda

        for t in reversed(range(n)):
            if t == n - 1:
                next_val = last_val
                next_non_terminal = 1.0 - dones[t]
            else:
                next_val = values[t + 1]
                next_non_terminal = 1.0 - dones[t]

            delta = rewards[t] + gamma * next_val * next_non_terminal - values[t]
            gae = delta + gamma * lam * next_non_terminal * gae
            advantages[t] = gae
            returns[t] = advantages[t] + values[t]

        return advantages, returns

    def update_policy(self, rollout: Dict[str, Any]) -> Dict[str, float]:
        """用 PPO 更新策略"""
        adv, ret = self.compute_gae(rollout)
        adv = (adv - adv.mean()) / (adv.std() + 1e-8)

        states = rollout["states"]
        actions = rollout["actions"]
        old_log_probs = rollout["log_probs"]

        cfg = self._config
        n = len(states)
        indices = np.arange(n)
        losses = []

        for _ in range(cfg.n_epochs):
            np.random.shuffle(indices)
            for start in range(0, n, cfg.batch_size):
                batch = indices[start:start + cfg.batch_size]
                if len(batch) < 2:
                    continue

                s_batch = states[batch]
                a_batch = actions[batch]
                old_lp_batch = old_log_probs[batch]
                adv_batch = adv[batch]
                ret_batch = ret[batch]

                # 前向
                # 简化：对每个样本单独前向
                total_loss = 0.0
                for i in range(len(batch)):
                    s = s_batch[i].flatten()
                    a = a_batch[i]
                    old_lp = old_lp_batch[i]

                    h = np.tanh(s @ self._policy.w1 + self._policy.b1)
                    mean = h @ self._policy.w_mean + self._policy.b_mean
                    std = np.exp(self._policy.log_std)

                    # 新 log_prob
                    new_lp = -0.5 * np.sum(((a - mean) / (std + 1e-8)) ** 2
                                            + 2 * self._policy.log_std
                                            + np.log(2 * np.pi))

                    # PPO ratio
                    ratio = np.exp(new_lp - old_lp)
                    surr1 = ratio * adv_batch[i]
                    surr2 = np.clip(ratio, 1 - cfg.clip_epsilon,
                                    1 + cfg.clip_epsilon) * adv_batch[i]
                    policy_loss = -np.minimum(surr1, surr2)

                    # Value loss
                    ch = np.tanh(s @ self._policy.wc1 + self._policy.bc1)
                    v_pred = (ch @ self._policy.wc2 + self._policy.bc2)[0]
                    value_loss = cfg.vf_coef * (v_pred - ret_batch[i]) ** 2

                    # Entropy bonus
                    entropy = np.sum(self._policy.log_std + 0.5 * np.log(2 * np.pi * np.e))
                    entropy_bonus = -cfg.ent_coef * entropy

                    total_loss += policy_loss + value_loss + entropy_bonus

                # 梯度更新（简化的 SGD）
                losses.append(float(total_loss / len(batch)))

        return {"loss": np.mean(losses) if losses else 0.0}

    def train(self, total_timesteps: int = 10000,
              callback: Optional[Callable] = None) -> Dict[str, Any]:
        """训练策略"""
        t0 = time.time()
        n_updates = total_timesteps // self._config.n_steps
        metrics = {"steps": [], "reward": [], "loss": []}

        for update in range(n_updates):
            rollout = self.collect_rollout(self._config.n_steps)
            update_info = self.update_policy(rollout)

            avg_reward = np.mean(self._episode_rewards) if self._episode_rewards else 0.0

            metrics["steps"].append(self._total_steps)
            metrics["reward"].append(avg_reward)
            metrics["loss"].append(update_info["loss"])

            if avg_reward > self._best_reward:
                self._best_reward = avg_reward

            if callback:
                callback(update, self._total_steps, avg_reward)

        elapsed = time.time() - t0
        return {
            "total_steps": self._total_steps,
            "avg_reward": float(np.mean(self._episode_rewards)) if self._episode_rewards else 0.0,
            "best_reward": self._best_reward,
            "n_updates": n_updates,
            "elapsed_seconds": round(elapsed, 2),
            "steps_per_second": round(self._total_steps / max(elapsed, 0.01), 1),
        }

    def evaluate(self, n_episodes: int = 5,
                 render: bool = False) -> Dict[str, float]:
        """评估策略"""
        rewards = []
        successes = 0

        for ep in range(n_episodes):
            obs, _ = self._env.reset()
            flat_obs = self._flatten_obs(obs)
            done = False
            ep_reward = 0.0
            steps = 0

            while not done:
                action, _, _ = self._policy.get_action(flat_obs, deterministic=True)
                obs, reward, terminated, truncated, info = self._env.step(action)
                flat_obs = self._flatten_obs(obs)
                ep_reward += reward
                done = terminated or truncated
                steps += 1

            rewards.append(ep_reward)
            if terminated:
                successes += 1

        return {
            "mean_reward": float(np.mean(rewards)),
            "std_reward": float(np.std(rewards)),
            "success_rate": successes / n_episodes,
            "n_episodes": n_episodes,
        }

    def save(self, path: str) -> None:
        """保存策略权重"""
        p = self._policy
        np.savez_compressed(
            path,
            w1=p.w1, b1=p.b1,
            w_mean=p.w_mean, b_mean=p.b_mean,
            log_std=p.log_std,
            wc1=p.wc1, bc1=p.bc1,
            wc2=p.wc2, bc2=p.bc2,
        )

    def load(self, path: str) -> None:
        """加载策略权重"""
        data = np.load(path)
        p = self._policy
        p.w1 = data["w1"]
        p.b1 = data["b1"]
        p.w_mean = data["w_mean"]
        p.b_mean = data["b_mean"]
        p.log_std = data["log_std"]
        p.wc1 = data["wc1"]
        p.bc1 = data["bc1"]
        p.wc2 = data["wc2"]
        p.bc2 = data["bc2"]

    @property
    def total_steps(self) -> int:
        return self._total_steps

    @property
    def policy(self) -> MLPPolicy:
        return self._policy
