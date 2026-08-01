"""
LAAP Embodied — 训练管道
=========================

在 Genesis 仿真环境中训练 Aris 的具身技能。

模块：
  sim_env.py    — Genesis 仿真训练环境 (Gymnasium 风格)
  rl.py         — PPO 强化学习训练管道

用法：
    from laap.embodied.training import GenesisEnv, TaskConfig, RLTrainingPipeline

    env = GenesisEnv(task=TaskConfig(name='reach'))
    pipeline = RLTrainingPipeline(env)
    result = pipeline.train(total_timesteps=10000)
    pipeline.save('policy.npz')
    metrics = pipeline.evaluate(n_episodes=5)

印记: 在仿真中训练身体，在现实中使用智慧
"""

from .sim_env import GenesisEnv, TaskConfig
from .rl import RLTrainingPipeline, PPOConfig, MLPPolicy

__all__ = [
    "GenesisEnv",
    "TaskConfig",
    "RLTrainingPipeline",
    "PPOConfig",
    "MLPPolicy",
]
