"""
LAAP Embodied — 机器人技能库
==============================

Aris 可以学习和执行的具身技能。

技能格式：
    • name: str          — 技能名称
    • preconditions      — 前置条件检查
    • execute(**kwargs)  — 执行
    • abort()            — 中止

技能列表：
    • Grasp              — 抓取物体
    • PickAndPlace       — 拾放（复合技能）

用法：
    from laap.embodied.skills import GraspSkill, PickAndPlace
    
    grasp = GraspSkill(arm, gripper)
    result = grasp.execute(target_pos=[0.3, 0.0, 0.05])
    print(result.message)

印记: 每一个技能，都是与世界的一次对话
"""

from .base import BaseSkill, SkillResult, SkillStatus
from .grasp import GraspSkill
from .pick_and_place import PickAndPlace

__all__ = [
    "BaseSkill", "SkillResult", "SkillStatus",
    "GraspSkill", "PickAndPlace",
]
