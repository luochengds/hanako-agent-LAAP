"""AetherClient — LAAP 大脑挂载到外部智能体的 Client 模式。

使用场景：
    已有外部 AI Agent（Hermes, Claude Code, 自定义 Agent），
    想要挂载 LAAP 的 PSI 认知层、Actor 运行时和 Petri 网工作流。

用法::

    from laap import AetherClient

    client = AetherClient()
    await client.mount()                          # 启动认知循环
    await client.process("用户输入")              # 经过 PSI + 认知总线
    response = await client.query("用户输入")     # 简写: process + 返回文本
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from laap.orchestration.cognitive_bus import ArisCognitiveBus

logger = logging.getLogger("laap.sdk.client")


class AetherClient:
    """LAAP 客户端 — 将数字生命体的认知层注入外部 Agent。

    AetherClient 是 LAAP 对外暴露的主要接口。它管理 ArisCognitiveBus
    的生命周期，处理用户意图路由（确定性工具 → Petri 网 → LLM），
    并维护 PSI 状态机的演化。

    Attributes:
        bus: 底层 ArisCognitiveBus 实例。
        mounted: 是否已启动并运行。
    """

    def __init__(
        self,
        system_id: str = "aether-client",
        tool_registry: Optional[Any] = None,
        llm_transport: Optional[Any] = None,
        session_manager: Optional[Any] = None,
        auto_initialize: bool = True,
    ):
        self.system_id = system_id
        self.bus = ArisCognitiveBus(
            system_id=system_id,
            tool_registry=tool_registry,
            llm_transport=llm_transport,
            session_manager=session_manager,
        )
        self.mounted = False
        self._pending_auto = auto_initialize

    # ── 生命周期 ──────────────────────────────────────────────────────

    async def mount(self, agent: Optional[Any] = None) -> None:
        """启动认知总线并挂载（可选地注入到外部 agent）。

        如果提供了 *agent*，会尝试调用其 install_hooks 方法。
        """
        if self.mounted:
            logger.warning("AetherClient already mounted")
            return

        await self.bus.initialize()
        self.mounted = True
        logger.info("AetherClient mounted (system_id=%s)", self.system_id)

        if agent is not None:
            adapter = getattr(agent, "install_hooks", None)
            if callable(adapter):
                adapter(self.bus)

    async def unmount(self) -> None:
        """停止认知总线并清理资源。"""
        if not self.mounted:
            return
        await self.bus.shutdown()
        self.mounted = False
        logger.info("AetherClient unmounted")

    # ── 认知接口 ──────────────────────────────────────────────────────

    async def process(
        self,
        user_input: str,
        context: Optional[dict] = None,
    ) -> dict[str, Any]:
        """运行完整的认知循环（PSI → 记忆 → 规则 → 工具 → 融合）。

        Args:
            user_input: 用户输入文本。
            context: 可选的上下文信息 dict。

        Returns:
            包含 ``response``, ``psi_state``, ``cognitive_trace`` 的 dict。
        """
        if not self.mounted and self._pending_auto:
            await self.mount()

        return await self.bus.process(user_input, context=context)

    async def query(self, user_input: str, context: Optional[dict] = None) -> str:
        """简写：process 后直接返回响应的文本内容。"""
        result = await self.process(user_input, context=context)
        response = result.get("response", "")
        if isinstance(response, dict):
            return response.get("content", str(response))
        return str(response)

    async def intent(
        self,
        text: str,
    ) -> dict[str, Any]:
        """将用户意图路由到确定性工具或 LLM。

        这是比完整认知循环更轻量的路径：适合明确的操作指令
        （读文件、搜索、打开网页等）。
        """
        if not self.mounted and self._pending_auto:
            await self.mount()

        return await self.bus.process_user_intent(text)

    # ── 上下文管理器 ──────────────────────────────────────────────────

    async def __aenter__(self) -> "AetherClient":
        await self.mount()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.unmount()

    def __repr__(self) -> str:
        return (
            f"<AetherClient system_id={self.system_id!r}"
            f" mounted={self.mounted}>"
        )
