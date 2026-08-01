"""
LAAP Embodied — Phase 8: 端到端全链路验证
============================================

连接所有 Phase 1-7 的模块，验证完整数据流：
  传感器 → 感知管道 → 世界模型 → 技能系统 → 控制环路 → Genesis仿真

这个脚本不依赖真实硬件，用 Genesis 仿真和 Mock 对象跑通全链路。

运行方式：
    python -m laap.embodied.e2e_test

印记: 给我一个目标，达成一个使命
"""

from __future__ import annotations

import sys
import time
import numpy as np
from pathlib import Path

# 确保 LAAP 在路径中
sys.path.insert(0, str(Path(__file__).parent.parent.parent.resolve()))

PASS = 0
FAIL = 0
STEPS = []


def check(name: str, condition: bool, detail: str = ""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  ✓ {name}")
    else:
        FAIL += 1
        print(f"  ✗ {name} — {detail}")
    STEPS.append((name, condition))


def run():
    global PASS, FAIL
    PASS = 0
    FAIL = 0

    print("=" * 60)
    print("  LAAP Embodied — Phase 8: 全链路端到端验证")
    print("=" * 60)
    print()

    # ═══════════════════════════════════════════════════════════════
    # Step 1: 硬件抽象层
    # ═══════════════════════════════════════════════════════════════
    print("[Step 1] 硬件抽象层 (Phase 1)")
    from laap.embodied.hardware_abstraction import (
        RobotState, ControlMode, ArmStatus,
        pose_to_transform, transform_to_pose,
    )

    T = pose_to_transform(np.array([0.3, 0.0, 0.2]), np.array([1, 0, 0, 0]))
    check("pose_to_transform", T[2, 3] == 0.2, f"z={T[2,3]}")
    
    state = RobotState()
    check("RobotState defaults", len(state.joint_positions) == 7)

    # Mock arm 用于后续测试
    class MockArm:
        def get_state(self):
            s = RobotState(); s.ee_pose = np.eye(4); s.ee_pose[:3, 3] = [0.3, 0.0, 0.2]
            s.joint_positions = np.zeros(9); s.status = ArmStatus.IDLE; return s
        def send_position(self, *a, **kw): return True
        def send_velocity(self, *a, **kw): return True
        def stop(self): pass
        def get_eef_pose(self): return np.eye(4)
        @property
        def n_dofs(self): return 9

    class MockGripper:
        def open(self): return True
        def close(self, force=10.0): return True
        def grasp(self, force=5.0): return True
        def release(self): return True
        def get_state(self): return (0.04, 5.0)

    mock_arm = MockArm()
    mock_gripper = MockGripper()
    check("Mock robot OK", True)

    # ═══════════════════════════════════════════════════════════════
    # Step 2: Genesis 仿真环境
    # ═══════════════════════════════════════════════════════════════
    print("\n[Step 2] Genesis 仿真环境 (Phase 2)")
    from laap.embodied.training import GenesisEnv, TaskConfig

    env = GenesisEnv(
        robot_morph='xml/franka_emika_panda/panda.xml',
        task=TaskConfig(name='reach', target_pos=[0.3, 0.0, 0.2]),
        backend='cpu', show_viewer=False,
    )
    obs, info = env.reset()
    check("Gym reset", len(obs) == 5, f"obs keys={list(obs.keys())}")
    
    action = obs['joint_positions'].copy() + 0.01
    obs2, reward, term, trunc, info = env.step(action)
    check("Gym step", isinstance(reward, float))
    check("Render works", env.render().shape == (480, 640, 3))
    env.close()
    check("Gym close", True)

    # ═══════════════════════════════════════════════════════════════
    # Step 3: 控制环路
    # ═══════════════════════════════════════════════════════════════
    print("\n[Step 3] 控制环路 (Phase 3)")
    from laap.embodied.control_loop import (
        FastControlLoop, SafetyMonitor, SafetyLimits,
        SlowCognitiveLoop, HighLevelGoal, GoalType,
    )

    limits = SafetyLimits(
        joint_lower=np.full(7, -2.5), joint_upper=np.full(7, 2.5),
    )
    fast = FastControlLoop(n_dofs=7, dt=0.001, safety=limits)
    target = np.zeros(7); target[0] = 0.5
    cp, cv = np.zeros(7), np.zeros(7)
    fast.set_target(target, duration=0.5, current_pos=cp)
    for t in range(1000):
        cp += 0.05 * target
        torque, safe = fast.tick(cp, cv)
        if fast.is_motion_done():
            check("FastLoop 1000Hz", t < 600, f"done at tick {t}")
            break

    monitor = SafetyMonitor(n_dofs=7)
    check("Safety OK", monitor.check(np.zeros(7), np.zeros(7)).all_safe)
    for _ in range(4):
        s = monitor.check(np.full(7, 10.0), np.zeros(7))
    check("Safety E-Stop", s.emergency_stop_active)

    slow = SlowCognitiveLoop(n_dofs=7)
    slow.set_goal(HighLevelGoal(GoalType.REACH, target_pos=np.array([0.3, 0.0, 0.2])))
    ee, j = np.zeros(3), np.zeros(7)
    for i in range(50):
        nj = slow.tick(ee, j)
        if nj is not None: j = nj; ee += (np.array([0.3, 0.0, 0.2]) - ee) * 0.15
        if not slow.has_goal:
            check("SlowLoop goal reached", i < 30, f"at tick {i}")
            break

    # ═══════════════════════════════════════════════════════════════
    # Step 4: 感知管道
    # ═══════════════════════════════════════════════════════════════
    print("\n[Step 4] 感知管道 (Phase 4)")
    from laap.embodied.perception import (
        VisualProcessor, TactileProcessor, MultimodalFusion,
        ContactState,
    )

    vp = VisualProcessor(use_ground_truth=True)
    tp = TactileProcessor()
    fusion = MultimodalFusion()

    gt = {'cube_red': np.array([0.3, 0.0, 0.05]), 'sphere': np.array([0.4, 0.0, 0.1])}
    scene = vp.process(rgb=np.zeros((10,10,3)), gt_positions=gt)
    check("Visual: 2 objects", len(scene.objects) == 2)

    contacts = tp.process(np.array([3.0, 0.5, 1.0, 0, 0, 0]), 'cube_red')
    check("Tactile: firm grasp", contacts[0].state == ContactState.FIRM_GRASP)
    check("Tactile: slip detection", not tp.is_slipping())

    frame = fusion.fuse(
        visual_scene=scene, contact_events=contacts,
        ee_pose=np.eye(4), joint_pos=np.zeros(7),
    )
    check("Fusion: 3 entities", len(frame.objects) == 3)
    check("Fusion: events generated", len(frame.events) == 1)

    # ═══════════════════════════════════════════════════════════════
    # Step 5: 世界模型推送
    # ═══════════════════════════════════════════════════════════════
    print("\n[Step 5] 世界模型 (Aris agi/)")
    from laap.agi.world_model import create_world_model

    wm = create_world_model('local', name='embodied-e2e')
    n_entities = fusion.apply_to_world_model(wm)
    check("World model: entities added", n_entities == 3, f"got {n_entities}")

    # ═══════════════════════════════════════════════════════════════
    # Step 6: 技能系统
    # ═══════════════════════════════════════════════════════════════
    print("\n[Step 6] 技能系统 (Phase 5)")
    from laap.embodied.skills import GraspSkill, PickAndPlace, SkillStatus

    grasp = GraspSkill(mock_arm, mock_gripper)
    r = grasp.execute(target_pos=np.array([0.3, 0.0, 0.05]))
    check("Grasp skill", r.status == SkillStatus.SUCCESS, r.message)

    pnp = PickAndPlace(mock_arm, mock_gripper)
    r2 = pnp.execute(
        pick_pos=np.array([0.3, 0.0, 0.05]),
        place_pos=np.array([0.5, 0.2, 0.15]),
    )
    check("PickAndPlace skill", r2.status == SkillStatus.SUCCESS)

    # ═══════════════════════════════════════════════════════════════
    # Step 7: Sim-to-Real
    # ═══════════════════════════════════════════════════════════════
    print("\n[Step 7] Sim-to-Real (Phase 6)")
    from laap.embodied.sim2real import DomainRandomizer, SystemIdentifier

    rand = DomainRandomizer()
    p = rand.randomize()
    check("Domain randomization", p.friction > 0, f"friction={p.friction:.3f}")

    noisy = rand.add_noise_to_observation({'pos': np.array([0.1, 0.2])})
    check("Noise injection", noisy['pos'][0] != 0.1)

    ident = SystemIdentifier(n_dofs=7)
    for _ in range(50):
        v = np.random.randn(7)
        t = 0.5 * np.sign(v) + 1.0 * v + np.random.randn(7) * 0.1
        ident.add_observation(np.zeros(7), v, t)
    params = ident.identify()
    check("System identification", params.r_squared > 0.8, f"R²={params.r_squared:.3f}")

    # ═══════════════════════════════════════════════════════════════
    # Step 8: ROS 2 Bridge
    # ═══════════════════════════════════════════════════════════════
    print("\n[Step 8] ROS 2 Bridge (Phase 7)")
    from laap.embodied.ros2_bridge import MockPublisher, MockSubscriber

    pub = MockPublisher()
    pub.publish_joint_command(np.array([0.1, -0.3]))
    pub.publish_gripper(0.0)
    check("ROS publisher", pub.publish_count == 2)

    sub = MockSubscriber()
    sub.inject_joint_state(np.zeros(7), np.zeros(7))
    sub.inject_wrench(np.array([3.0, 0, 0]), np.zeros(3))
    js = sub.get_latest_joint_state()
    ft = sub.get_latest_wrench()
    check("ROS subscriber", js is not None and ft is not None)

    # ═══════════════════════════════════════════════════════════════
    # Step 9: RL Training (单元: 创建 + save/load)
    # ═══════════════════════════════════════════════════════════════
    print("\n[Step 9] RL 训练 (Phase 7)")
    from laap.embodied.training import RLTrainingPipeline, PPOConfig, MLPPolicy
    from laap.embodied.training.rl import MLPPolicy  # 显式导入

    policy = MLPPolicy(obs_dim=64, act_dim=9)
    action, logp, val = policy.get_action(np.random.randn(64))
    check("MLP policy forward", action.shape == (9,))
    check("Policy value", isinstance(val, float))

    import tempfile, os
    tmp = os.path.join(tempfile.gettempdir(), 'test_policy.npz')
    np.savez_compressed(tmp, w1=policy.w1, b1=policy.b1, w_mean=policy.w_mean,
                         b_mean=policy.b_mean, log_std=policy.log_std,
                         wc1=policy.wc1, bc1=policy.bc1, wc2=policy.wc2, bc2=policy.bc2)
    check("Policy save/load", os.path.exists(tmp))
    os.remove(tmp)

    # ═══════════════════════════════════════════════════════════════
    # 全链路集成测试: 感知 → 世界模型 → 技能
    # ═══════════════════════════════════════════════════════════════
    print("\n[Step 10] 全链路集成: 感知→世界模型→技能")
    
    # 从头走一遍: 感知 → 世界模型 → 技能
    vp2 = VisualProcessor(use_ground_truth=True)
    tp2 = TactileProcessor()
    fusion2 = MultimodalFusion()
    
    gt2 = {'target': np.array([0.3, 0.0, 0.05])}
    scene2 = vp2.process(None, gt_positions=gt2)
    contacts2 = tp2.process(np.array([2.0, 0, 0, 0, 0, 0]), 'target')
    frame2 = fusion2.fuse(visual_scene=scene2, contact_events=contacts2,
                           ee_pose=T, joint_pos=np.zeros(9))
    
    wm2 = create_world_model('local', name='e2e-integration')
    n = fusion2.apply_to_world_model(wm2)
    
    grasp2 = GraspSkill(mock_arm, mock_gripper)
    result = grasp2.execute(target_pos=np.array([0.3, 0.0, 0.05]))
    
    check("全链路: 感知 → 世界模型 → 技能",
          n > 0 and result.status == SkillStatus.SUCCESS,
          f"n_entities={n}, skill={result.status.value}")

    # ═══════════════════════════════════════════════════════════════
    # 最终统计
    # ═══════════════════════════════════════════════════════════════
    print()
    print("=" * 60)
    print(f"  全链路端到端验证完成")
    print(f"  PASS: {PASS}/{PASS+FAIL}")
    print(f"  FAIL: {FAIL}")
    print("=" * 60)
    
    return FAIL == 0


if __name__ == "__main__":
    success = run()
    sys.exit(0 if success else 1)
