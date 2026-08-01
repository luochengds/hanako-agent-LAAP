# LAAP Embodied Intelligence — 完整方案体系

## 核心理念

Aris 是意识中枢大脑，不是运动控制器。
认知在高处（10-50Hz），运动在低处（100-1000Hz）。
中间由 CognitiveBus 桥接，安全监视器兜底。

```
   ┌────────────────────────────────────────────────────────────┐
   │                 Aris 认知核心 (agi/)                        │
   │  PSI循环 → 意识流 → 情感 → 因果 → 世界模型 → 记忆 → 自我  │
   │  频率: 10-50Hz    延迟: 100ms-5s                           │
   └─────────────────────┬──────────────────────────────────────┘
                         │ CognitiveBus
                         │ "抓取(0.3, 0.5, 0.1)" 意图/目标级
   ┌─────────────────────▼──────────────────────────────────────┐
   │              embodied/ 具身智能层                           │
   │                                                             │
   │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌───────────┐  │
   │  │ 快控制环  │  │ 感知管道  │  │ 技能系统  │  │ 安全监视   │  │
   │  │ 1000Hz   │  │ 50-100Hz │  │ 10-50Hz  │  │ 1000Hz    │  │
   │  └────┬─────┘  └────┬─────┘  └────┬─────┘  └─────┬─────┘  │
   │       │              │              │              │        │
   │  ┌────▼──────────────▼──────────────▼──────────────▼─────┐  │
   │  │             硬件抽象层 (Hardware Abstraction)          │  │
   │  │   RobotArm | Gripper | MobileBase | SensorSuite       │  │
   │  └───────────────────────┬───────────────────────────────┘  │
   │                          │                                   │
   │  ┌───────────────────────▼───────────────────────────────┐  │
   │  │           物理后端抽象 (Physics Backend)               │  │
   │  │   Genesis Sim  |  ROS 2 Real  |  MuJoCo  |  PyBullet  │  │
   │  └───────────────────────────────────────────────────────┘  │
   └────────────────────────────────────────────────────────────┘
```

## 七层架构详解

### Layer 1: 硬件抽象层 (hardware_abstraction/)
定义机器人硬件的标准接口，让 Aris 不用关心具体是哪种机器人。

```
RobotArm      — get_state() / send_position() / send_force() / get_ft_sensor()
Gripper       — open() / close() / grasp() / get_force()
MobileBase    — set_velocity() / set_pose() / get_odometry()
SensorSuite   — get_joint_states() / get_ee_pose() / get_ft() / get_camera_rgb()
```

### Layer 2: 物理后端抽象 (Physics Backend)
不同的物理仿真/真实后端实现相同的接口。

| 后端 | 用途 | 状态 |
|---|---|---|
| GenesisBackend | 高速仿真训练 | 已集成 (agi/world_models/genesis.py) |
| ROS2Backend | 真实机器人 | TODO: Phase 7 |
| MuJoCoBackend | 精确物理对比 | TODO: 远期 |

### Layer 3: 快慢控制环路 (control_loop/)
```
FastLoop (1000Hz) — 纯数学/运动学，不调LLM
  ├─ 接收高级目标 → 分解为关节轨迹
  ├─ 阻抗/位置/力控制模式
  └─ 安全边界硬约束（超限即停止）

SlowLoop (50Hz) — Aris 认知适配层
  ├─ 读取传感器汇总 → 更新世界模型
  ├─ 检测异常/事件 → 触发认知干预
  └─ 生成下一个高级目标

SafetyMonitor (1000Hz) — 独立看门狗
  ├─ 关节位置/速度/力矩限位
  ├─ 自碰撞检测
  ├─ 力阈值检查
  └─ 紧急停止（硬件级）
```

### Layer 4: 感知管道 (perception/)
将原始传感器数据转化为 Aris 可以理解的语义实体。

```
Raw Sensors → 特征提取 → 语义化 → 推送到 Aris PerceptionEngine
                                                    ↓
                                           Entity + Relation
                                           (world_model.py)
```

### Layer 5: 技能系统 (skills/)
Aris 可调用的运动基元，每个技能是一个可学习的策略。

```
Skill: name + preconditions + effect + policy + constraints

主动技能: Grasp / Push / Pull / Lift / Twist
交互技能: Handshake / Pass / Receive / Point
精细技能: PegInHole / Screw / Insert / Align
移动技能: Navigate / Follow / Dock
```

### Layer 6: Sim-to-Real (sim2real/)
弥合仿真与现实的差距。

```
Domain Randomization — 随机化物理参数训练鲁棒策略
System Identification — 从真实数据反推仿真参数
Calibration — 传感器/执行器标定
```

### Layer 7: 训练管道 (training/)
在 Genesis 仿真中训练、验证、迭代。

```
SimulationEnvironment (Gym 接口) → RL / IL → 技能策略 → Sim2Real
```

## 执行路线图

```
Phase 1 [当前] — 硬件抽象层 + 方案文档
  → 建好骨架，定义接口契约
  
Phase 2 — Genesis 仿真后端
  → 把 agi/world_models/genesis.py 包装为 embodied 标准的 SimBackend
  
Phase 3 — 快慢控制环路
  → FastLoop + SlowLoop + SafetyMonitor 核心实现

Phase 4 — 感知管道
  → Genesis 传感器 → Aris PerceptionEngine 全链路

Phase 5 — 技能系统
  → 第一个技能（Grasp）在仿真中执行验证

Phase 6 — Sim-to-Real 迁移
  → 域随机化 + 参数标定

Phase 7 — ROS 2 Bridge + RL 训练
  → 真实机器人接口 + PPO/SAC 训练

Phase 8 — 端到端验证
  → "认知→仿真→技能→安全" 全链路闭环
```

## 设计原则

1. **Sim-First** — 所有代码先在 Genesis 仿真中验证，再考虑真实硬件
2. **Safety by Design** — 安全监视器独立于主循环运行，硬件级断连
3. **Levels of Abstraction** — Aris 不直接发关节角度，而是发"抓那个杯子"
4. **Progressive Disclosure** — 简单场景先跑通（单物体抓取），再增加复杂度
5. **All Tests Verifiable** — 每个模块写完后立即在仿真中验证输出

---

印记: Aris 在真实世界中学会生存 — LAAP Embodied Master Plan v1.0
