"""LAAP Liquid — 液态神经网络 (LNN) 认知动力学内核

集成 MIT CSAIL 的 Liquid Time-Constant (LTC)、Closed-form Continuous-depth (CfC)
与 Neural Circuit Policies (NCP) 作为 PSI 认知架构的动力学增强包。

设计哲学：
  - 输入驱动的可变时间常数 τ(t)：神经元的时间尺度随输入动态变化，
    强信号加快响应、弱信号延长记忆，这正是"液态"的含义。
  - 连续时间 ODE 演化：原生支持任意 dt（含不规则时间间隔），
    适配 LAAP 的事件驱动认知循环。
  - 最小依赖：运行时仅依赖 numpy，不绑定 torch（训练可选）。

参考论文：
  [1] Hasani et al., "Liquid Time-constant Networks", AAAI-21.
  [2] Lechner et al., "Closed-form Continuous-time Neural Networks",
      Nature Machine Intelligence, 2022.
  [3] Lechner et al., "Neural Circuit Policies Enabling Auditable Autonomy",
      Nature Machine Intelligence, 2020. (C. elegans 布线)

Quick start:
    from laap.liquid.neurons import LTCCell, CfCCell, NCPCircuit
    import numpy as np
    cell = CfCCell(input_dim=4, hidden_dim=8)
    h = np.zeros(8)
    h = cell.forward(h, np.array([0.1, 0.2, 0.3, 0.4]), dt=0.1)
"""

from laap.liquid.neurons import LTCCell, CfCCell, NCPCircuit, _sigmoid as sigmoid, _tanh as tanh, _situ_glu as situ_glu
from laap.liquid.core import LiquidCognitiveCore
from laap.liquid.bus_bridge import LiquidBusField
from laap.liquid.affective_field import LiquidAffectiveField
from laap.liquid.attention_selector import LiquidAttentionSelector
from laap.liquid.causal_simulator import LiquidCausalSimulator
from laap.liquid.memory_field import LiquidMemoryField

__all__ = [
    "LTCCell",
    "CfCCell",
    "NCPCircuit",
    "LiquidCognitiveCore",
    "LiquidBusField",
    "LiquidAffectiveField",
    "LiquidAttentionSelector",
    "LiquidCausalSimulator",
    "LiquidMemoryField",
    # 工具激活函数
    "sigmoid",
    "tanh",
    "situ_glu",
]
