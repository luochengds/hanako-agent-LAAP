"""laap_agent.py — 薄 shim (已合并到 agent_core/agent.py Agent)

历史: 此文件原是 LAAPAgent 的独立实现 (Hermes AIAgent 全量集成入口)。
现在: LAAPAgent 已统一到 `laap.agent_core.agent.Agent` 类的 `mode="hermes"` 分支。

本文件保留以维持向后兼容:
    from laap.agent_core.laap_agent import LAAPAgent  # 仍然可用
    LAAPAgent(model="...", ...)                       # 等价于 Agent(mode="hermes", ...)

迁移指南:
    推荐: from laap.agent_core.agent import Agent
          agent = Agent(mode="hermes", model="...")

环境变量 (替代原硬编码路径):
    HERMES_HOME  — Hermes 工程根目录 (原硬编码 D:\\hermes-agent-main (1)\\hermes-agent-main)
    LAAP_HOME    — LAAP 工程根目录 (默认: 当前工作目录)
"""
from __future__ import annotations

import os
import sys
import logging
from typing import Any, Dict, List, Optional

from laap.config.paths import get_hermes_root, get_laap_root

logger = logging.getLogger("laap.agent_core.laap_agent")

# ── 路径辅助 (移除硬编码, 改用 laap.config.paths) ─────────────────

def _resolve_hermes_home() -> str:
    """通过 laap.config.paths 定位 Hermes 工程根目录。"""
    root = get_hermes_root()
    if root is not None:
        return str(root)
    logger.warning(
        "LAAPAgent: HERMES_ROOT not set and no Hermes installation found. "
        "Set HERMES_ROOT environment variable to enable Hermes mode."
    )
    return ""


def _resolve_laap_home() -> str:
    """定位 LAAP 工程根目录。"""
    return str(get_laap_root())


def ensure_hermes_paths() -> None:
    """确保 Hermes 和 LAAP 都在 sys.path 中 (兼容原 API)。"""
    hermes_home = _resolve_hermes_home()
    laap_home = _resolve_laap_home()
    for p in [hermes_home, laap_home]:
        if p and p not in sys.path:
            sys.path.insert(0, p)
    laap_brain_path = os.path.join(laap_home, "laap_brain")
    if os.path.isdir(laap_brain_path) and laap_brain_path not in sys.path:
        sys.path.insert(0, laap_brain_path)


# ── 统一导入 Agent (LAAPAgent = Agent 的 hermes 模式) ─────────────

from laap.agent_core.agent import Agent, AgentConfig

# 向后兼容别名: LAAPAgent 现在就是 Agent, 默认 mode="hermes"
class LAAPAgent(Agent):
    """LAAPAgent — 已合并到 `laap.agent_core.agent.Agent`。

    此子类仅为向后兼容, 构造时自动使用 mode="hermes"。

    推荐迁移:
        from laap.agent_core.agent import Agent
        agent = Agent(mode="hermes", model="...")
    """

    def __init__(self,
                 model: str = "",
                 provider: str = "",
                 enabled_toolsets: Optional[List[str]] = None,
                 disabled_toolsets: Optional[List[str]] = None,
                 quiet_mode: bool = True,
                 platform: str = "cli",
                 session_id: str = "",
                 **kwargs):
        # 兼容旧 LAAPAgent(model="...", ...) 调用方式
        # 透传所有参数给 Agent(mode="hermes", ...)
        super().__init__(
            mode="hermes",
            model=model,
            provider=provider,
            enabled_toolsets=enabled_toolsets,
            disabled_toolsets=disabled_toolsets,
            quiet_mode=quiet_mode,
            platform=platform,
            session_id=session_id,
            **kwargs,
        )

    # 保留原 LAAPAgent 的便捷方法 (现在委托给统一 Agent)
    def run_conversation(self, user_message: str, system_message: str = None,
                         conversation_history: list = None,
                         task_id: str = None) -> dict:
        """完整对话循环 — 委托给底层 Hermes AIAgent。"""
        return self.hermes_agent.run_conversation(
            user_message=user_message,
            system_message=system_message,
            conversation_history=conversation_history,
            task_id=task_id or f"laap_{int(__import__('time').time())}",
        )

    def handshake(self):
        """获取握手协议实例 (兼容旧 API)。"""
        return self._handshake

    def handshake_status(self) -> str:
        """握手状态摘要 (兼容旧 API)。"""
        if not self._handshake:
            return "Handshake: not connected"
        return self._handshake.get_status().summary()

    def share_info(self, key: str, value: Any):
        """共享信息到 Info Bus (兼容旧 API)。"""
        if self._handshake:
            self._handshake.share(key, value, "laap")

    def get_info(self, key: str, default: Any = None) -> Any:
        """从 Info Bus 读取共享信息 (兼容旧 API)。"""
        if self._handshake:
            return self._handshake.get(key, default)
        return default

    def stats(self) -> dict:
        """完整统计 (兼容旧 API)。"""
        return self.get_status()

    def __repr__(self):
        brain = "🧠" if self._brain else ""
        hs = "🤝" if (self._handshake and self._handshake.is_connected()) else ""
        model = getattr(self._hermes_agent, 'model', '') if self._hermes_agent else ''
        return f"<LAAPAgent {model} [{self.tool_count}tools]{brain}{hs}>"


# ── 便捷工厂函数 (保留原 API) ────────────────────────────────────

def create_agent(model: str = "",
                 provider: str = "",
                 enabled_toolsets: Optional[List[str]] = None,
                 **kwargs) -> LAAPAgent:
    """创建全量集成的 LAAPAgent (快捷方式)。

    推荐: 直接用 Agent(mode="hermes", ...)
    """
    return LAAPAgent(
        model=model,
        provider=provider,
        enabled_toolsets=enabled_toolsets,
        **kwargs,
    )


def quick_check() -> dict:
    """快速检查全量集成状态 (保留原 API)。

    验证:
      - Hermes 可导入
      - install_laap 可安装
      - 工具注册中心有工具
      - 握手协议可初始化
    """
    ensure_hermes_paths()
    results: Dict[str, Any] = {}

    # 1. Hermes 路径
    hermes_home = _resolve_hermes_home()
    laap_home = _resolve_laap_home()
    results["hermes_home"] = hermes_home if hermes_home else "NOT FOUND"
    results["laap_home"] = laap_home if os.path.isdir(laap_home) else "NOT FOUND"
    results["hermes_home_env"] = os.environ.get("HERMES_HOME", "(not set)")

    # 2. install_laap
    try:
        from laap_brain.integrate import install_laap, is_laap_enabled
        installed = install_laap()
        results["install_laap"] = installed
        results["is_enabled"] = is_laap_enabled()
    except Exception as e:
        results["install_laap"] = f"ERROR: {e}"

    # 3. Tool registry
    try:
        import model_tools  # noqa: F401
        from tools.registry import registry
        tool_names = registry.get_all_tool_names()
        results["tool_count"] = len(tool_names)
        results["sample_tools"] = tool_names[:10]
    except Exception as e:
        results["tool_count"] = f"ERROR: {e}"

    # 4. Handshake
    try:
        from laap.handshake import HandshakeProtocol  # noqa: F401
        hs = HandshakeProtocol.get_instance()
        results["handshake"] = hs.get_status().healthy()
        results["handshake_detail"] = hs.get_status().summary()
    except Exception as e:
        results["handshake"] = f"ERROR: {e}"

    return results


def show_integration_status() -> None:
    """显示全量集成状态面板 (保留原 API)。"""
    status = quick_check()

    print("=" * 60)
    print("  LAAP ↔ Hermes 全量集成状态")
    print("=" * 60)
    for k, v in status.items():
        if isinstance(v, bool):
            icon = "✅" if v else "❌"
            print(f"  {icon} {k}: {v}")
        elif isinstance(v, list):
            print(f"  📋 {k}: {len(v)} items")
            for item in v[:5]:
                print(f"     - {item}")
        elif isinstance(v, str) and ("NOT" in v or "ERROR" in v):
            print(f"  ❌ {k}: {v}")
        else:
            print(f"  ℹ️  {k}: {v}")
    print("=" * 60)


# ── 模块自检 ─────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    show_integration_status()
