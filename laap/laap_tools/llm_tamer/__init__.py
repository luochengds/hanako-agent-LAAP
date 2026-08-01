"""
LLM Tamer — 认知驱动的 LLM 生成控制模块
=========================================

路径一：logit bias 控制 + 动态温度 + token 禁止

通过直接修改 LLM 生成概率分布，实现从 CognitiveBus 认知状态
到 LLM 输出特性的实时控制。

架构:
  tamer.py              — 主入口 LLMTamer 类
  bias_computers/       — 偏置计算器（注意力/情感/需求/元认知）
  integrators/          — LLM 接口集成（llama.cpp / DeepSeek API）
  config.yaml           — 偏置参数配置

使用:
  from laap_tools.llm_tamer import LLMTamer

  tamer = LLMTamer()
  bias = tamer.compute_bias(state, context)
  temp = tamer.compute_temperature(state)
  result = tamer.apply_to_local(prompt, state)
"""

from .tamer import LLMTamer

__version__ = "0.1.0"
__all__ = ["LLMTamer"]
