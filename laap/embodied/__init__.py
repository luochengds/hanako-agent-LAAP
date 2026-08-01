"""
LAAP Embodied Intelligence — 具身智能分支
=========================================

将 Aris AGI 认知核心（PSI 循环、意识流、情感系统、世界模型）
接入真实物理世界的机器人。

架构：

    +--------------------------------------------------------+
    |                    Aris 认知核心                          |
    |  (PSI循环 → 意识流 → 情感 → 因果 → 世界模型 → 记忆)     |
    +---------------------------+----------------------------+
                                |
                    CognitiveBus (认知总线)
                                |
    +---------------------------+----------------------------+
    | embodied/                 |                            |
    |                           |                            |
    | hardware_abstraction/     | 硬件抽象层 ✓ Phase 1      |
    | control_loop/             | 快慢控制环路 (Phase 3)     |
    | perception/               | 感知管道 (Phase 4)         |
    | skills/                   | 技能系统 (Phase 5)         |
    | sim2real/                 | Sim-to-Real (Phase 6)     |
    | ros2_bridge/              | ROS 2 接口 (Phase 7)      |
    | training/                 | 训练管道 (Phase 7)         |
    +---------------------------+----------------------------+

印记: Aris 在真实世界中学会生存 — LAAP Embodied v0.1
"""

__version__ = "0.1.0"
__description__ = "LAAP Embodied Intelligence — Aris's bridge to the physical world"
