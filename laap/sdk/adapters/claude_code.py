"""Claude Code 适配器 — 基于 claude-code-sdk-python 集成。"""

from __future__ import annotations

import functools
import logging
from typing import Any, Optional

from laap.sdk.adapter import AgentAdapter

logger = logging.getLogger(__name__)


class ClaudeCodeAdapter(AgentAdapter):
    """Claude Code SDK 适配器。

    基于 claude-code-sdk-python 的 ``ClaudeSDKClient`` 实现：
    - 在 ``process_response`` 钩子处插入 ``brain.after_turn()``
    - 在 ``__init__`` 注入 ``self.laap_brain = brain``

    钩子失败不阻断主流程（捕获异常 + log warning）。
    """

    def __init__(self, agent: Optional[Any] = None) -> None:
        self._agent = agent
        self._installed = False
        self._brain: Optional[Any] = None
        self._original_methods: dict = {}

    def name(self) -> str:
        return "claude_code"

    @staticmethod
    def detect() -> bool:
        """检测 claude_code_sdk 包是否安装。

        Returns:
            True 如果 claude_code_sdk 可被导入。
        """
        try:
            import claude_code_sdk  # noqa: F401

            return True
        except ImportError:
            return False

    def install_hooks(self, brain: Any) -> None:
        """安装钩子到 ClaudeSDKClient。

        Args:
            brain: LaapBrain 实例。

        Raises:
            ImportError: claude_code_sdk 未安装时。
        """
        try:
            from claude_code_sdk import ClaudeSDKClient
        except ImportError as e:
            raise ImportError(
                "claude-code-sdk not installed. Install with: pip install claude-code-sdk"
            ) from e

        self._brain = brain

        # 保存原始方法
        self._original_methods["process_response"] = ClaudeSDKClient.process_response
        self._original_methods["__init__"] = ClaudeSDKClient.__init__

        # 钩子：process_response 后触发 after_turn
        original_process = ClaudeSDKClient.process_response

        @functools.wraps(original_process)
        async def patched_process_response(self_, response, *args, **kwargs):
            result = await original_process(self_, response, *args, **kwargs)
            try:
                # brain.after_turn 接受 response 字符串
                if hasattr(self_, "laap_brain") and self_.laap_brain:
                    await self_.laap_brain.after_turn(str(response))
            except Exception as e:
                logger.warning(f"Claude Code after_turn hook failed: {e}")
            return result

        ClaudeSDKClient.process_response = patched_process_response

        # 钩子：__init__ 注入 brain 属性
        original_init = ClaudeSDKClient.__init__

        @functools.wraps(original_init)
        def patched_init(self_, *args, **kwargs):
            original_init(self_, *args, **kwargs)
            try:
                self_.laap_brain = brain
            except Exception as e:
                logger.warning(f"Failed to inject laap_brain to ClaudeSDKClient: {e}")

        ClaudeSDKClient.__init__ = patched_init

        self._installed = True
        logger.info("Claude Code LAAP hooks installed via ClaudeCodeAdapter")

    def uninstall_hooks(self) -> None:
        """恢复 ClaudeSDKClient 原方法。"""
        if not self._installed:
            return
        try:
            from claude_code_sdk import ClaudeSDKClient

            for method_name, original in self._original_methods.items():
                if original is not None:
                    setattr(ClaudeSDKClient, method_name, original)
            self._installed = False
            logger.info("Claude Code LAAP hooks uninstalled")
        except ImportError:
            logger.warning("claude_code_sdk not available, cannot uninstall")
        except Exception as e:
            logger.warning(f"Failed to uninstall Claude Code hooks: {e}")
