"""
LAAP Embodied — Sim-to-Real 迁移
=================================

Genesis 物理仿真参数和真实物理世界之间存在差距。
这个模块负责缩小差距，使认知核心在仿真中学到的技能能迁移到真实机器人。

模块：
  domain_randomization.py   — 域随机化 (训练时随机化物理参数)
  calibration.py            — 参数标定 (从真实轨迹反推最优参数)
  system_id.py              — 系统辨识 (从力矩-运动数据辨识动力学参数)

用法：
    # 训练时：随机化参数使策略鲁棒
    randomizer = DomainRandomizer()
    randomizer.randomize()
    randomizer.apply_to_scene(scene)
    
    # 部署前：标定仿真参数匹配真实机器人
    calibrator = ParameterCalibrator()
    calibrator.add_real_trajectory(real_positions, timestamps)
    best = calibrator.calibrate(n_trials=100)
    calibrator.save_calibration('franka_calib.json')

印记: 仿真中学会的，现实中做到
"""

from .domain_randomization import DomainRandomizer, RandomizationConfig, SimParameters
from .calibration import ParameterCalibrator, CalibrationResult, TrajectoryData
from .system_id import SystemIdentifier, IdentifiedParams

__all__ = [
    "DomainRandomizer", "RandomizationConfig", "SimParameters",
    "ParameterCalibrator", "CalibrationResult", "TrajectoryData",
    "SystemIdentifier", "IdentifiedParams",
]
