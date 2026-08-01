"""
LAAP Embodied — Genesis 仿真训练环境
======================================

将 Genesis 物理仿真包装为 Gymnasium 风格的环境接口，
用于强化学习/模仿学习训练机器人技能。

接口设计：
    env = GenesisEnv(scene_config, robot_name='franka')
    obs, info = env.reset()
    obs, reward, terminated, truncated, info = env.step(action)
    rgb = env.render()

动作空间：关节位置/速度/力矩 or 末端笛卡尔位姿
观测空间：关节状态 + 传感器读数 + 任务相关特征
"""

from __future__ import annotations

import time
import numpy as np
from typing import Optional, Dict, Any, Tuple, List, Union
from dataclasses import dataclass, field

try:
    import genesis as gs
    _GS_AVAILABLE = True
except ImportError:
    _GS_AVAILABLE = False
    gs = None

from laap.embodied.hardware_abstraction import (
    RobotState, ControlMode, ArmStatus,
    RobotArm, GenesisArm, Gripper, GenesisGripper,
    SensorSuite, GenesisSensorSuite,
    pose_to_transform, transform_to_pose,
)


# ═══════════════════════════════════════════════════════════════
# 任务配置
# ═══════════════════════════════════════════════════════════════

@dataclass
class TaskConfig:
    """任务配置"""
    name: str = "reach"                    # 任务名称
    target_pos: np.ndarray = field(default_factory=lambda: np.array([0.3, 0.0, 0.2]))
    target_size: float = 0.02              # 目标容差半径
    max_steps: int = 500                   # 最大步数
    reward_weights: Dict[str, float] = field(default_factory=lambda: {
        "distance": -1.0,                  # 到目标的距离惩罚
        "success": 100.0,                  # 到达奖励
        "effort": -0.01,                   # 能耗惩罚
        "smoothness": -0.1,                # 动作平滑度
    })


# ═══════════════════════════════════════════════════════════════
# Genesis 训练环境
# ═══════════════════════════════════════════════════════════════

class GenesisEnv:
    """Genesis 物理仿真训练环境

    标准用法：
        env = GenesisEnv(
            robot_morph='xml/franka_emika_panda/panda.xml',
            task=TaskConfig(name='reach', target_pos=[0.3, 0.0, 0.2]),
            backend='cpu',
            show_viewer=False,
        )
        
        obs, info = env.reset()
        for step in range(500):
            action = policy(obs)     # [n_dofs] 关节位置目标
            obs, reward, terminated, truncated, info = env.step(action)
            if terminated or truncated:
                break
        
        env.close()
    """

    def __init__(
        self,
        robot_morph: str = "xml/franka_emika_panda/panda.xml",
        morph_type: str = "MJCF",
        task: Optional[TaskConfig] = None,
        backend: str = "cpu",
        show_viewer: bool = False,
        control_mode: str = "position",
        sim_dt: float = 0.01,
        substeps: int = 10,
        seed: Optional[int] = None,
    ):
        self._robot_morph = robot_morph
        self._morph_type = morph_type
        self._task = task or TaskConfig()
        self._backend = backend
        self._show_viewer = show_viewer
        self._control_mode = control_mode
        self._sim_dt = sim_dt
        self._substeps = substeps
        self._seed = seed

        # 运行时
        self._scene = None
        self._arm: Optional[GenesisArm] = None
        self._gripper: Optional[GenesisGripper] = None
        self._sensors: Optional[GenesisSensorSuite] = None
        self._step_count = 0
        self._last_action = None
        self._initialized = False

        # 观测/动作空间维度
        self._n_dofs = 9  # Franka: 7 arm + 2 gripper

        if seed is not None:
            np.random.seed(seed)

    # ── Gym 风格接口 ──

    @property
    def observation_space(self) -> Dict[str, Tuple]:
        """观测空间定义"""
        return {
            "joint_positions": (self._n_dofs,),
            "joint_velocities": (self._n_dofs,),
            "ee_pose": (4, 4),             # 4x4 变换矩阵
            "target_pos": (3,),
            "gripper_width": (1,),
        }

    @property
    def action_space(self) -> Tuple:
        """动作空间定义 (关节位置增量)"""
        return (self._n_dofs,)

    def reset(self) -> Tuple[Dict[str, np.ndarray], Dict[str, Any]]:
        """重置环境到初始状态

        Returns:
            (observation, info)
        """
        self.close()

        # 初始化 Genesis
        if not _GS_AVAILABLE:
            raise ImportError("genesis-world 未安装")

        gs.init(backend=gs.cpu if self._backend == "cpu" else gs.cuda,
                logging_level="warning")

        # 创建场景和机器人
        self._scene = gs.Scene(
            show_viewer=self._show_viewer,
            sim_options=gs.options.SimOptions(
                dt=self._sim_dt,
                substeps=self._substeps,
            ),
        )
        self._scene.add_entity(gs.morphs.Plane())

        if self._morph_type.upper() == "MJCF":
            robot_entity = self._scene.add_entity(
                gs.morphs.MJCF(file=self._robot_morph)
            )
        else:
            robot_entity = self._scene.add_entity(
                gs.morphs.URDF(file=self._robot_morph)
            )

        self._scene.build()

        # 包装为硬件抽象
        self._arm = GenesisArm(robot_entity, name="robot")
        self._gripper = GenesisGripper(robot_entity, finger_joints=(9, 10))
        self._sensors = GenesisSensorSuite(self._scene, arm_entity=robot_entity)
        self._step_count = 0
        self._last_action = None
        self._initialized = True

        obs = self._get_observation()
        info = {"task": self._task.name}
        return obs, info

    def step(self, action: np.ndarray) -> Tuple[
        Dict[str, np.ndarray], float, bool, bool, Dict[str, Any]
    ]:
        """执行一步动作

        Args:
            action: 关节位置目标 [n_dofs] 或增量

        Returns:
            (observation, reward, terminated, truncated, info)
        """
        if not self._initialized:
            obs, _ = self.reset()
            return obs, 0.0, False, False, {"reset": True}

        # 应用动作
        if self._control_mode == "position":
            self._arm.send_position(action, blocking=False)
        elif self._control_mode == "velocity":
            self._arm.send_velocity(action, blocking=False)

        # 推进仿真
        for _ in range(self._substeps):
            self._scene.step()

        self._last_action = action
        self._step_count += 1

        # 观测 + 奖励
        obs = self._get_observation()
        reward = self._compute_reward(obs)
        terminated = self._check_termination(obs)
        truncated = self._step_count >= self._task.max_steps

        info = {
            "step": self._step_count,
            "distance_to_target": np.linalg.norm(
                self._get_ee_pos() - self._task.target_pos
            ),
        }

        return obs, reward, terminated, truncated, info

    def render(self) -> Optional[np.ndarray]:
        """渲染当前帧 (RGB 图像)"""
        if self._sensors:
            return self._sensors.read_rgb()
        return None

    def close(self) -> None:
        """清理资源"""
        if self._initialized:
            try:
                gs.destroy()
            except Exception:
                pass
            self._scene = None
            self._arm = None
            self._gripper = None
            self._sensors = None
            self._initialized = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    # ── 内部方法 ──

    def _get_observation(self) -> Dict[str, np.ndarray]:
        """组装观测"""
        obs = {}
        if self._arm:
            state = self._arm.get_state()
            obs["joint_positions"] = state.joint_positions
            obs["joint_velocities"] = state.joint_velocities
            obs["ee_pose"] = state.ee_pose
            obs["gripper_width"] = np.array([state.gripper_opening])
        else:
            obs["joint_positions"] = np.zeros(self._n_dofs)
            obs["joint_velocities"] = np.zeros(self._n_dofs)
            obs["ee_pose"] = np.eye(4)
            obs["gripper_width"] = np.array([0.0])
        obs["target_pos"] = self._task.target_pos
        return obs

    def _get_ee_pos(self) -> np.ndarray:
        """获取末端位置"""
        if self._arm:
            T = self._arm.get_eef_pose()
            return T[:3, 3]
        return np.zeros(3)

    def _compute_reward(self, obs: Dict[str, np.ndarray]) -> float:
        """计算奖励"""
        ee_pos = self._get_ee_pos()
        target = self._task.target_pos
        dist = np.linalg.norm(ee_pos - target)

        rewards = {
            "distance": self._task.reward_weights.get("distance", -1.0) * dist,
            "success": self._task.reward_weights.get("success", 100.0)
                      if dist < self._task.target_size else 0.0,
            "effort": self._task.reward_weights.get("effort", -0.01)
                      * np.sum(np.abs(obs.get("joint_velocities", np.zeros(9)))),
        }
        if self._last_action is not None and "smoothness" in self._task.reward_weights:
            rewards["smoothness"] = (
                self._task.reward_weights["smoothness"]
                * np.linalg.norm(self._last_action - obs.get("joint_positions", np.zeros(9)))
            )

        return sum(rewards.values())

    def _check_termination(self, obs: Dict[str, np.ndarray]) -> bool:
        """检查是否终止"""
        # 到达目标
        dist = np.linalg.norm(self._get_ee_pos() - self._task.target_pos)
        if dist < self._task.target_size:
            return True
        return False

    # ── 工具方法 ──

    def set_target(self, pos: np.ndarray) -> None:
        """动态设置目标位置"""
        self._task.target_pos = np.array(pos)

    def get_metrics(self) -> Dict[str, Any]:
        """获取环境统计"""
        return {
            "steps": self._step_count,
            "task": self._task.name,
            "n_dofs": self._n_dofs,
            "backend": self._backend,
        }
