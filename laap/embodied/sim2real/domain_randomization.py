"""
LAAP Embodied — 域随机化 (Domain Randomization)
=================================================

在 Genesis 仿真中随机化物理参数，使策略对现实世界的参数变化更鲁棒。

核心思想：
  仿真参数不可能 100% 匹配现实。
  通过在训练中随机化参数，策略学会"不管参数如何都能完成任务"。

随机化参数：
  动力学: 摩擦系数、刚度、阻尼、质量
  视觉: 光照、纹理、相机噪声
  延迟: 通信/执行延迟
  初始条件: 物体位置/方向的微小扰动

用法：
    randomizer = DomainRandomizer()
    randomizer.apply(scene)          # 应用到 Genesis 场景
    randomizer.randomize()           # 随机化所有参数
    params = randomizer.get_params() # 获取当前参数

印记: 仿真中学会的，现实中做到
"""

from __future__ import annotations

import numpy as np
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass, field
import random


@dataclass
class RandomizationConfig:
    """域随机化配置"""
    # 动力学随机化范围
    friction_range: Tuple[float, float] = (0.2, 1.5)      # 摩擦系数
    stiffness_range: Tuple[float, float] = (0.5, 2.0)     # 刚度倍率
    damping_range: Tuple[float, float] = (0.5, 2.0)       # 阻尼倍率
    mass_range: Tuple[float, float] = (0.8, 1.5)          # 质量倍率

    # 初始条件随机化 (m / rad)
    pos_noise: float = 0.01       # 位置噪声 (m)
    rot_noise: float = 0.05       # 旋转噪声 (rad)
    joint_noise: float = 0.02     # 初始关节角度噪声 (rad)

    # 传感器噪声
    force_noise_std: float = 0.1   # 力传感器噪声 (N)
    pos_noise_std: float = 0.001   # 位置传感器噪声 (m)

    # 延迟随机化
    latency_range: Tuple[float, float] = (0.0, 0.05)  # 秒

    # 是否启用
    enabled: bool = True

    # 各参数随机化概率（1.0 = 每次都变）
    randomize_prob: float = 0.8


@dataclass
class SimParameters:
    """仿真物理参数（当前值）"""
    friction: float = 0.5
    stiffness: float = 1.0
    damping: float = 1.0
    mass_scale: float = 1.0
    latency: float = 0.0
    force_noise_std: float = 0.0
    pos_noise_std: float = 0.0


class DomainRandomizer:
    """域随机化引擎

    在每次环境 reset() 时调用 randomize() 更新参数，
    然后将参数应用到仿真场景和传感器模拟中。

    用法：
        randomizer = DomainRandomizer()
        
        # 在每个 episode 开始时：
        randomizer.randomize()
        params = randomizer.get_params()
        # 将 params 应用到 Genesis 场景的物体属性
        # 将噪声参数应用到传感器模拟
    """

    def __init__(self, config: Optional[RandomizationConfig] = None):
        self._config = config or RandomizationConfig()
        self._current = SimParameters()
        self._randomize_count = 0

    def randomize(self) -> SimParameters:
        """随机化所有参数，返回当前参数集"""
        cfg = self._config
        if not cfg.enabled:
            return self._current

        def _maybe_rand(val_range):
            if random.random() < cfg.randomize_prob:
                return random.uniform(*val_range)
            return val_range[0] + (val_range[1] - val_range[0]) / 2  # 默认中值

        self._current = SimParameters(
            friction=_maybe_rand(cfg.friction_range),
            stiffness=_maybe_rand(cfg.stiffness_range),
            damping=_maybe_rand(cfg.damping_range),
            mass_scale=_maybe_rand(cfg.mass_range),
            latency=random.uniform(*cfg.latency_range),
            force_noise_std=cfg.force_noise_std,
            pos_noise_std=cfg.pos_noise_std,
        )
        self._randomize_count += 1
        return self._current

    def apply_to_scene(self, genesis_scene) -> None:
        """将随机化参数应用到 Genesis 场景

        遍历场景中的物体，修改摩擦/质量等属性。
        """
        params = self._current
        try:
            # Genesis 场景实体迭代
            entities = getattr(genesis_scene, '_entities', [])
            for entity in entities:
                # 设置摩擦系数
                if hasattr(entity, 'set_friction'):
                    entity.set_friction(params.friction)
                # 设置质量倍率
                if hasattr(entity, 'set_mass_scale'):
                    entity.set_mass_scale(params.mass_scale)
        except Exception:
            pass  # Genesis 版本差异

    def add_noise_to_observation(self, obs: Dict[str, np.ndarray]) -> Dict[str, np.ndarray]:
        """给观测添加传感器噪声"""
        params = self._current
        noisy = {}
        for key, val in obs.items():
            if isinstance(val, np.ndarray):
                if 'pos' in key or 'joint' in key:
                    noise = np.random.normal(0, params.pos_noise_std, val.shape)
                    noisy[key] = val + noise
                elif 'force' in key:
                    noise = np.random.normal(0, params.force_noise_std, val.shape)
                    noisy[key] = val + noise
                else:
                    noisy[key] = val
            else:
                noisy[key] = val
        return noisy

    def get_params(self) -> SimParameters:
        """获取当前参数"""
        return self._current

    def get_stats(self) -> Dict[str, Any]:
        """获取随机化统计"""
        return {
            "randomize_count": self._randomize_count,
            "enabled": self._config.enabled,
            "current": {
                "friction": round(self._current.friction, 3),
                "stiffness": round(self._current.stiffness, 3),
                "mass_scale": round(self._current.mass_scale, 3),
                "latency": round(self._current.latency * 1000, 1),
            }
        }
