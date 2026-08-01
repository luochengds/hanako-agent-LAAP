# -*- coding: utf-8 -*-
"""LAAP tool registrations for Agent-Reach.

Follows the LAAP convention `register_all(registry)` used by
`laap/tools/*.py`. Each registration is idempotent so re-import is safe.

Registry compatibility:
    The adapter supports BOTH LAAP tool registries:
      - laap.tools.tool_registry.ToolRegistry  (used by laap.agent.base.Agent)
      - laap.tools.registry.AoRegistry          (the `ao` singleton)
    ToolRegistry.tool() decorator uses `category=...`
    AoRegistry.register_fn()    uses `toolset=...`
    The helper `_register_fn()` below dispatches to whichever interface
    the host registry exposes.

Registered tools:
    agent_reach_doctor      — full health report (text)
    agent_reach_status      — compact JSON summary for metacognitive monitor
    agent_reach_channels    — list all channels with tier/backend info
    agent_reach_read_url    — read any URL via Jina Reader
    agent_reach_search      — Exa semantic search via mcporter
    agent_reach_transcribe  — Whisper transcription (Groq → OpenAI)
    agent_reach_install     — run installer non-interactively
"""

from __future__ import annotations

import json
import logging
from typing import Callable, Optional

logger = logging.getLogger("laap.integrations.agent_reach.tools")


def _register_fn(registry, fn: Callable, *, name: str, category: str,
                 description: str) -> None:
    """Register `fn` under `name`, supporting both LAAP registry interfaces."""
    # ToolRegistry.register_fn signature: (fn, name, category, description)
    # AoRegistry.register_fn signature:   (fn, name, toolset, description)
    try:
        # Try ToolRegistry-style first (category kwarg)
        registry.register_fn(fn, name=name, category=category,
                             description=description)
        return
    except TypeError:
        pass
    except Exception as e:
        logger.debug("register_fn(category) failed for %s: %s", name, e)
    # Fallback: AoRegistry-style (toolset kwarg)
    try:
        registry.register_fn(fn, name=name, toolset=category,
                             description=description)
        return
    except TypeError:
        pass
    except Exception as e:
        logger.debug("register_fn(toolset) failed for %s: %s", name, e)
    # Last resort: use register() with a constructed entry (AoRegistry)
    try:
        registry.register(name, schema={}, handler=fn, toolset=category,
                          description=description)
    except Exception as e:
        logger.warning("Could not register tool %s: %s", name, e)


def register_all(registry) -> None:
    """Register all Agent-Reach tools with the LAAP tool registry.

    Idempotent — re-calls are no-ops (guarded by a marker flag).
    Supports both ToolRegistry (Agent) and AoRegistry (singleton).
    """
    if getattr(registry, "_agent_reach_tools_registered", False):
        return
    registry._agent_reach_tools_registered = True

    from laap.integrations.agent_reach.adapter import get_bridge
    bridge = get_bridge()

    _CATEGORY = "reach"

    # ── agent_reach_doctor ──────────────────────────────────────────
    def agent_reach_doctor() -> str:
        """获取 Agent-Reach 完整健康报告。

        检查 Agent-Reach 所有互联网渠道的健康状态（YouTube/Twitter/
        Reddit/GitHub/B站/小红书等 15+ 平台）。返回完整文本报告，
        包含每个渠道的当前后端、状态、配置建议。

        Returns:
            文本格式的渠道状态报告
        """
        return bridge.doctor_report()

    _register_fn(registry, agent_reach_doctor,
                 name="agent_reach_doctor",
                 category=_CATEGORY,
                 description=(
                     "检查 Agent-Reach 所有互联网渠道的健康状态"
                     "（YouTube/Twitter/Reddit/GitHub/B站/小红书等 15+ 平台）。"
                     "返回完整文本报告。"
                 ))

    # ── agent_reach_status ──────────────────────────────────────────
    def agent_reach_status() -> str:
        """获取 Agent-Reach 紧凑摘要（JSON）。

        返回可用渠道数、警告数、未安装数、每个渠道的当前后端。
        适合 PSI/Harness 元认知监控。

        Returns:
            JSON 字符串，包含 available/version/ok/warn/off/channels 字段
        """
        return json.dumps(bridge.summary(), ensure_ascii=False, indent=2)

    _register_fn(registry, agent_reach_status,
                 name="agent_reach_status",
                 category=_CATEGORY,
                 description=(
                     "获取 Agent-Reach 的紧凑 JSON 摘要：可用渠道数、"
                     "警告数、未安装数、每个渠道的当前后端。"
                     "适合 PSI/Harness 元认知监控。"
                 ))

    # ── agent_reach_channels ────────────────────────────────────────
    def agent_reach_channels() -> str:
        """列出所有 Agent-Reach 渠道（JSON）。

        Returns:
            JSON 字符串，渠道元信息数组（name/description/backends/tier/active_backend）
        """
        return json.dumps(bridge.channels(), ensure_ascii=False, indent=2)

    _register_fn(registry, agent_reach_channels,
                 name="agent_reach_channels",
                 category=_CATEGORY,
                 description=(
                     "列出 Agent-Reach 所有已注册的互联网渠道，含名称、"
                     "描述、候选后端列表、tier（0=零配置, 1=需免费 Key, "
                     "2=需登录态）和当前活跃后端。"
                 ))

    # ── agent_reach_read_url ────────────────────────────────────────
    def agent_reach_read_url(url: str, timeout: int = 30) -> str:
        """读取任意 URL 内容（Jina Reader）。

        通过 Agent-Reach 的 Jina Reader 后端读取任意网页，返回
        Markdown 文本。支持文档、文章、博客等。这是 web_fetch 的
        增强版本，覆盖更多平台。

        Args:
            url: 目标网页 URL
            timeout: 超时秒数（默认 30）

        Returns:
            Markdown 格式的网页内容
        """
        return bridge.read_url(url, timeout=timeout)

    _register_fn(registry, agent_reach_read_url,
                 name="agent_reach_read_url",
                 category=_CATEGORY,
                 description=(
                     "通过 Agent-Reach 的 Jina Reader 后端读取任意网页，"
                     "返回 Markdown 文本。支持文档、文章、博客等。"
                     "这是 web_fetch 的增强版本，覆盖更多平台。"
                 ))

    # ── agent_reach_search ──────────────────────────────────────────
    def agent_reach_search(query: str, max_results: int = 5) -> str:
        """全网语义搜索（Exa via mcporter）。

        Args:
            query: 搜索关键词
            max_results: 最大结果数（默认 5）

        Returns:
            搜索结果文本
        """
        return bridge.search(query, max_results=max_results)

    _register_fn(registry, agent_reach_search,
                 name="agent_reach_search",
                 category=_CATEGORY,
                 description=(
                     "通过 Agent-Reach 的 Exa 后端执行全网语义搜索"
                     "（需 mcporter + Exa MCP 配置，免费无需 API Key）。"
                 ))

    # ── agent_reach_transcribe ──────────────────────────────────────
    def agent_reach_transcribe(source: str, provider: str = "auto") -> str:
        """转录音频/视频。

        通过 Agent-Reach 转录音频/视频 URL 或本地文件（Whisper via
        Groq → OpenAI fallback）。用于 YouTube 字幕提取、播客转录等。

        Args:
            source: 音频/视频 URL 或本地文件路径
            provider: 转录服务（auto/groq/openai，默认 auto）

        Returns:
            转录文本
        """
        return bridge.transcribe(source, provider=provider)

    _register_fn(registry, agent_reach_transcribe,
                 name="agent_reach_transcribe",
                 category=_CATEGORY,
                 description=(
                     "通过 Agent-Reach 转录音频/视频 URL 或本地文件"
                     "（Whisper via Groq → OpenAI fallback）。"
                     "用于 YouTube 字幕提取、播客转录等。"
                 ))

    # ── agent_reach_install ─────────────────────────────────────────
    def agent_reach_install(channels: str = "", env: str = "auto",
                            safe: bool = False, dry_run: bool = False) -> str:
        """运行 Agent-Reach 安装器。

        可指定 channels（逗号分隔，如 twitter,xiaohongshu,reddit）、
        环境（auto/local/server）、安全模式、dry-run。

        Args:
            channels: 逗号分隔的可选渠道名（空字符串表示仅装零配置渠道）
            env: 环境（auto/local/server）
            safe: 安全模式（不自动修改系统）
            dry_run: 仅预览不实际执行

        Returns:
            安装日志文本
        """
        return bridge.install(
            channels=channels, env=env, safe=safe, dry_run=dry_run,
        )

    _register_fn(registry, agent_reach_install,
                 name="agent_reach_install",
                 category=_CATEGORY,
                 description=(
                     "运行 Agent-Reach 安装器。可指定 channels（逗号分隔，"
                     "如 twitter,xiaohongshu,reddit）、环境（auto/local/server）、"
                     "安全模式、dry-run。返回安装日志。"
                 ))

    logger.info(
        "Agent-Reach tools registered: doctor, status, channels, "
        "read_url, search, transcribe, install"
    )
