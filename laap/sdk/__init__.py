"""LAAP SDK — 生命计算范式的大脑接入层。

两种使用模式：

Client 模式（挂载到外部 Agent）::

    from laap import AetherClient

    client = AetherClient()
    async with client:
        response = await client.query("你好")
        print(response)

Framework 模式（独立运行 LAAP 框架）::

    from laap import LAAPRuntime, Capability, MessageType

    runtime = LAAPRuntime(enable_psi=True)
    actor = runtime.spawn("worker", capabilities=[
        Capability(name="code", confidence=0.9),
    ])
    actor.on(MessageType.INVOKE, my_handler)

    # 或者运行认知循环
    result = await runtime.cognize("Hello")
    await runtime.shutdown()
"""

from __future__ import annotations

from laap.sdk.client import AetherClient
from laap.sdk.runtime import LAAPRuntime

# 适配器基类（供 adapter 实现者使用）
from laap.sdk.adapter import AgentAdapter

# 大脑挂载统一入口（hermes / claude_code / openclaw / generic 四种适配器）
from laap.sdk.mount import mount_brain_to_agent

__all__ = [
    "AetherClient",
    "LAAPRuntime",
    "AgentAdapter",
    "mount_brain_to_agent",
]
