"""OpenClaw 适配器 — monkey-patch OpenClaw Agent 类的 5 个认知钩子。"""

from __future__ import annotations

import functools
import logging
from typing import Any, Optional

from laap.sdk.adapter import AgentAdapter

logger = logging.getLogger(__name__)


class OpenClawAdapter(AgentAdapter):
    """OpenClaw 框架适配器。

    通过 monkey-patch OpenClaw 的 Agent 类，注入 5 个认知钩子：
    1. ``__init__``: 注入 ``self.laap_brain``
    2. before tool execution: ``brain.after_tool(tool_name, "pending")``
    3. after tool execution: ``brain.after_tool(tool_name, result)``
    4. before conversation: ``brain.before_turn(messages, system_prompt)``
    5. after conversation: ``brain.after_turn(response)``

    钩子失败不阻断主流程（捕获异常 + log warning）。
    """

    def __init__(self, agent: Optional[Any] = None) -> None:
        self._agent = agent
        self._installed = False
        self._brain: Optional[Any] = None
        self._original_methods: dict = {}

    def name(self) -> str:
        return "openclaw"

    @staticmethod
    def detect() -> bool:
        """检测 OpenClaw 是否已安装。

        Returns:
            True 如果 openclaw 包可被导入。
        """
        try:
            import openclaw  # noqa: F401

            return True
        except ImportError:
            return False

    def install_hooks(self, brain: Any) -> None:
        """monkey-patch OpenClaw Agent 类注入 5 钩子。

        若 OpenClaw 未安装，抛出 ImportError。钩子失败不阻断主流程。

        Args:
            brain: LaapBrain 实例。

        Raises:
            ImportError: openclaw 包不可用时。
        """
        try:
            import openclaw
        except ImportError as e:
            raise ImportError(
                "OpenClaw not installed. Install with: pip install openclaw"
            ) from e

        self._brain = brain

        # 获取 Agent 类（兼容 Agent / AIAgent 两种命名）
        agent_cls = getattr(openclaw, "Agent", None) or getattr(
            openclaw, "AIAgent", None
        )
        if agent_cls is None:
            logger.warning("OpenClaw Agent class not found, skipping hooks")
            self._installed = True
            return

        # 保存原始方法
        self._original_methods = {
            "__init__": agent_cls.__init__,
            "run_conversation": getattr(agent_cls, "run_conversation", None),
            "execute_tool": getattr(agent_cls, "execute_tool", None),
        }

        # 钩子 1: __init__ — 注入 self.laap_brain
        original_init = agent_cls.__init__

        @functools.wraps(original_init)
        def patched_init(self_, *args, **kwargs):
            original_init(self_, *args, **kwargs)
            try:
                self_.laap_brain = brain
                logger.debug("OpenClaw Agent.laap_brain injected")
            except Exception as e:
                logger.warning(f"Failed to inject laap_brain: {e}")

        agent_cls.__init__ = patched_init

        # 钩子 2-3: execute_tool 前后
        if self._original_methods["execute_tool"] is not None:
            original_execute_tool = self._original_methods["execute_tool"]

            @functools.wraps(original_execute_tool)
            async def patched_execute_tool(self_, tool_name, *args, **kwargs):
                try:
                    if hasattr(self_, "laap_brain") and self_.laap_brain:
                        await self_.laap_brain.after_tool(tool_name, "pending")
                except Exception as e:
                    logger.warning(f"OpenClaw before_tool hook failed: {e}")

                result = await original_execute_tool(self_, tool_name, *args, **kwargs)

                try:
                    if hasattr(self_, "laap_brain") and self_.laap_brain:
                        await self_.laap_brain.after_tool(tool_name, str(result))
                except Exception as e:
                    logger.warning(f"OpenClaw after_tool hook failed: {e}")

                return result

            agent_cls.execute_tool = patched_execute_tool

        # 钩子 4-5: run_conversation 前后
        if self._original_methods["run_conversation"] is not None:
            original_run = self._original_methods["run_conversation"]

            @functools.wraps(original_run)
            async def patched_run(self_, message, *args, **kwargs):
                try:
                    if hasattr(self_, "laap_brain") and self_.laap_brain:
                        cognitive = self_.laap_brain.before_turn([message], "")
                        if cognitive and "system_message" in kwargs:
                            kwargs["system_message"] = (
                                (kwargs.get("system_message", "") or "")
                                + "\n\n"
                                + cognitive
                            )
                except Exception as e:
                    logger.warning(f"OpenClaw before_turn hook failed: {e}")

                response = await original_run(self_, message, *args, **kwargs)

                try:
                    if hasattr(self_, "laap_brain") and self_.laap_brain:
                        await self_.laap_brain.after_turn(str(response))
                except Exception as e:
                    logger.warning(f"OpenClaw after_turn hook failed: {e}")

                return response

            agent_cls.run_conversation = patched_run

        self._installed = True
        logger.info("OpenClaw LAAP hooks installed via OpenClawAdapter")

    def uninstall_hooks(self) -> None:
        """恢复 OpenClaw Agent 原方法。"""
        if not self._installed:
            return
        try:
            import openclaw

            agent_cls = getattr(openclaw, "Agent", None) or getattr(
                openclaw, "AIAgent", None
            )
            if agent_cls:
                for method_name, original in self._original_methods.items():
                    if original is not None:
                        setattr(agent_cls, method_name, original)
            self._installed = False
            logger.info("OpenClaw LAAP hooks uninstalled")
        except Exception as e:
            logger.warning(f"Failed to uninstall OpenClaw hooks: {e}")
