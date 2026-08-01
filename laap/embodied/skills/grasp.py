"""
LAAP Embodied — 抓取技能 (Grasp)
==================================

Aris 最基本的具身技能：抓取物体。

执行流程：
    1. APPROACH — 末端移动到物体上方 5cm
    2. PRE_GRASP — 打开夹爪到合适宽度
    3. DESCEND — 下降到抓取位置
    4. GRASP — 闭合夹爪，施加抓取力
    5. LIFT — 抬起物体 5cm
    6. VERIFY — 确认物体被抓起（检查力传感器/末端位置）

用法：
    skill = GraspSkill(arm, gripper)
    result = skill.execute(target_pos=[0.3, 0.0, 0.05])

依赖：
    - GenesisArm (Phase 1)
    - GenesisGripper (Phase 1)
    - FastControlLoop (Phase 3)
"""

from __future__ import annotations

import time
import numpy as np
from typing import Optional, Dict, Any

from .base import BaseSkill, SkillResult, SkillStatus

try:
    from laap.embodied.hardware_abstraction import RobotArm, Gripper, RobotState
    from laap.embodied.control_loop import FastControlLoop, SafetyLimits
except ImportError:
    pass  # 延迟导入 — 具体实现需要这些


class GraspSkill(BaseSkill):
    """抓取技能

    从上方接近物体 → 闭合夹爪 → 抬起验证。

    execute 参数：
        target_pos: [x, y, z] 抓取位置
        approach_height: 接近高度（默认 0.05m 上方）
        grasp_force: 抓取力（默认 10N）
        lift_height: 抬升高度（默认 0.05m）
    """

    def __init__(self, arm: Optional["RobotArm"] = None,
                 gripper: Optional["Gripper"] = None,
                 name: str = "grasp"):
        super().__init__(name)
        self._arm = arm
        self._gripper = gripper
        self._phase = "idle"

    def set_robot(self, arm: "RobotArm", gripper: "Gripper") -> None:
        """设置机器人硬件接口"""
        self._arm = arm
        self._gripper = gripper

    def can_execute(self, **kwargs) -> bool:
        """检查是否可以执行抓取"""
        if self._arm is None or self._gripper is None:
            return False
        if "target_pos" not in kwargs:
            return False
        state = self._arm.get_state()
        if state.status.name == "ERROR":
            return False
        return True

    def execute(self, target_pos: np.ndarray = None,
                approach_height: float = 0.05,
                grasp_force: float = 10.0,
                lift_height: float = 0.05,
                **kwargs) -> SkillResult:
        """执行抓取"""
        if target_pos is None:
            return SkillResult(SkillStatus.FAILED, "未指定目标位置")
        if self._arm is None or self._gripper is None:
            return SkillResult(SkillStatus.FAILED, "机械臂/夹爪未设置")

        self._status = SkillStatus.EXECUTING
        self._start_time = time.time()
        self._phase = "approach"
        t0 = time.time()

        try:
            # Phase 1: 接近 — 移动到物体上方
            approach_pos = target_pos + np.array([0, 0, approach_height])
            state = self._arm.get_state()
            if not self._move_to_pose_approx(approach_pos, duration=2.0):
                return SkillResult(SkillStatus.FAILED, "接近失败")

            # Phase 2: 打开夹爪
            self._phase = "pre_grasp"
            self._gripper.open()
            import genesis as gs
            if hasattr(gs, 'destroy'):
                pass  # 仿真步进由外部控制

            # Phase 3: 下降到抓取位置
            self._phase = "descend"
            if not self._move_to_pose_approx(target_pos, duration=1.0):
                return SkillResult(SkillStatus.FAILED, "下降失败")

            # Phase 4: 闭合夹爪
            self._phase = "grasp"
            self._gripper.grasp(force=grasp_force)

            # Phase 5: 抬升
            self._phase = "lift"
            lift_pos = target_pos + np.array([0, 0, lift_height])
            if not self._move_to_pose_approx(lift_pos, duration=1.5):
                # 抬升失败可能意味着物体没抓住
                return SkillResult(SkillStatus.FAILED, "抬升失败 — 可能未抓住物体")

            # Phase 6: 验证
            self._phase = "verify"
            current_state = self._arm.get_state()
            lifted = current_state.ee_pose[2, 3] > target_pos[2] + lift_height * 0.5
            if not lifted:
                return SkillResult(SkillStatus.FAILED, "验证失败 — 物体未随夹爪抬起")

            elapsed = time.time() - t0
            self._status = SkillStatus.SUCCESS
            return SkillResult(
                SkillStatus.SUCCESS,
                f"成功抓取物体于 {target_pos}",
                duration=elapsed,
            )

        except Exception as e:
            self._status = SkillStatus.FAILED
            return SkillResult(SkillStatus.FAILED, f"抓取异常: {e}")

    def _move_to_pose_approx(self, target_pos: np.ndarray,
                              duration: float = 2.0) -> bool:
        """近似移动到目标位置（简单增量控制）

        实际系统中应使用 IK 解算器计算关节角度。
        这里简化：直接控制末端方向移动。
        """
        state = self._arm.get_state()
        current_pos = state.ee_pose[:3, 3]
        delta = target_pos - current_pos
        n_steps = max(10, int(duration / 0.01))

        for i in range(n_steps):
            alpha = min((i + 1) / n_steps, 1.0)
            # 平滑插值 (五次多项式)
            alpha_s = 10 * alpha**3 - 15 * alpha**4 + 6 * alpha**5
            target = current_pos + delta * alpha_s

            # 增量关节控制（简化：只调前3个关节）
            dof_pos = state.joint_positions.copy()
            dof_pos[:3] += delta[:3] * 0.05 * alpha_s
            self._arm.send_position(dof_pos, duration=0.05, blocking=False)

            # 检查中止
            if self._status == SkillStatus.ABORTED:
                return False

        return True

    def abort(self) -> None:
        super().abort()
        if self._gripper:
            self._gripper.release()
        if self._arm:
            self._arm.stop()
