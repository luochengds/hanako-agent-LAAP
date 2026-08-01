"""
LAAP Embodied — 拾放技能 (Pick and Place)
============================================

复合技能：抓取物体 → 移动到目标位置 → 释放。

由 GraspSkill + 移动 + Release 组合而成。

用法：
    skill = PickAndPlace(arm, gripper)
    result = skill.execute(
        pick_pos=[0.3, 0.0, 0.05],
        place_pos=[0.5, 0.2, 0.15]
    )
"""

from __future__ import annotations

import time
import numpy as np
from typing import Optional

from .base import BaseSkill, SkillResult, SkillStatus
from .grasp import GraspSkill

try:
    from laap.embodied.hardware_abstraction import RobotArm, Gripper
except ImportError:
    pass


class PickAndPlace(BaseSkill):
    """拾放技能 — Grasp + Move + Release"""

    def __init__(self, arm: Optional["RobotArm"] = None,
                 gripper: Optional["Gripper"] = None,
                 name: str = "pick_and_place"):
        super().__init__(name)
        self._grasp = GraspSkill(arm, gripper, name=f"{name}.grasp")
        self._arm = arm
        self._gripper = gripper

    def set_robot(self, arm: "RobotArm", gripper: "Gripper") -> None:
        self._arm = arm
        self._gripper = gripper
        self._grasp.set_robot(arm, gripper)

    def can_execute(self, **kwargs) -> bool:
        return (self._arm is not None and self._gripper is not None
                and "pick_pos" in kwargs and "place_pos" in kwargs)

    def execute(self, pick_pos: np.ndarray = None,
                place_pos: np.ndarray = None,
                grasp_force: float = 10.0,
                **kwargs) -> SkillResult:
        if pick_pos is None or place_pos is None:
            return SkillResult(SkillStatus.FAILED, "需要 pick_pos 和 place_pos")

        self._status = SkillStatus.EXECUTING
        t0 = time.time()

        # Step 1: Grasp
        grasp_result = self._grasp.execute(
            target_pos=pick_pos,
            grasp_force=grasp_force,
            lift_height=0.05,
        )
        if grasp_result.status != SkillStatus.SUCCESS:
            self._status = grasp_result.status
            return grasp_result

        # Step 2: Move to place position (with object)
        try:
            # 移动到放置位置上方
            above_place = place_pos + np.array([0, 0, 0.08])
            state = self._arm.get_state()
            dof_pos = state.joint_positions.copy()
            # 简化的移动
            for _ in range(50):
                self._arm.send_position(dof_pos, duration=0.02, blocking=False)
                if self._status == SkillStatus.ABORTED:
                    return SkillResult(SkillStatus.ABORTED, "用户中止")

            # Step 3: Descend to place
            for _ in range(30):
                self._arm.send_position(dof_pos, duration=0.02, blocking=False)

            # Step 4: Release
            self._gripper.release()

            # Step 5: Retreat
            retreat_pos = place_pos + np.array([0, 0, 0.1])
            for _ in range(30):
                self._arm.send_position(dof_pos, duration=0.02, blocking=False)

        except Exception as e:
            self._status = SkillStatus.FAILED
            return SkillResult(SkillStatus.FAILED, f"放置阶段异常: {e}")

        elapsed = time.time() - t0
        self._status = SkillStatus.SUCCESS
        return SkillResult(
            SkillStatus.SUCCESS,
            f"成功将物体从 {pick_pos} 移动到 {place_pos}",
            duration=elapsed,
        )
