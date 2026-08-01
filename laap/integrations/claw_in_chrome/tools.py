# -*- coding: utf-8 -*-
"""Claw in Chrome 工具注册.

将 claw-in-chrome 的能力注册为 LAAP 工具：
    - claw_doctor: 环境诊断
    - claw_presets: 列出国产模型预设
    - claw_build_config: 生成供应商配置
    - claw_navigate: 通过真实 Chrome 导航 URL
    - claw_screenshot: 通过真实 Chrome 截图
    - claw_click: 点击元素
    - claw_type: 输入文本
    - claw_get_text: 获取页面文本
    - claw_evaluate: 执行 JS
"""

from __future__ import annotations

import json
import logging
from typing import Any

from laap.tools.base import Tool
from laap.tools.tool_registry import ToolRegistry
from laap.integrations.claw_in_chrome.adapter import ClawBridge

logger = logging.getLogger("laap.integrations.claw_in_chrome.tools")

_bridge: ClawBridge | None = None


def _get_bridge() -> ClawBridge:
    global _bridge
    if _bridge is None:
        _bridge = ClawBridge()
    return _bridge


# ── 同步工具（诊断 / 配置）──────────────────────────────────

def claw_doctor(**kw) -> str:
    """运行 claw-in-chrome 环境诊断."""
    bridge = _get_bridge()
    return bridge.doctor_report()


def claw_doctor_json(**kw) -> str:
    """运行 claw-in-chrome 环境诊断（JSON 格式）."""
    bridge = _get_bridge()
    return json.dumps(bridge.doctor(), ensure_ascii=False)


def claw_presets(**kw) -> str:
    """列出所有国产模型预设."""
    bridge = _get_bridge()
    presets = bridge.list_presets()
    models = bridge.list_all_models()
    lines = [f"国产模型供应商预设 ({len(presets)} 个):", "=" * 50]
    for name in presets:
        model_list = models.get(name, [])
        lines.append(f"\n  {name}")
        for m in model_list[:5]:
            lines.append(f"    - {m}")
        if len(model_list) > 5:
            lines.append(f"    ... 共 {len(model_list)} 个模型")
    lines.append(f"\n使用 claw_build_config(preset_name, api_key) 生成配置")
    return "\n".join(lines)


def claw_build_config(preset_name: str = "", api_key: str = "", **kw) -> str:
    """根据预设和 API Key 生成可导入扩展的配置 JSON.

    Args:
        preset_name: 预设名称（如 "DeepSeek", "通义千问 (Qwen)" 等）
        api_key: 供应商的 API Key
    """
    if not preset_name or not api_key:
        return json.dumps({
            "error": "需要 preset_name 和 api_key 参数",
            "available_presets": _get_bridge().list_presets(),
        }, ensure_ascii=False)
    bridge = _get_bridge()
    try:
        storage_json = bridge.build_storage_json(preset_name, api_key)
        return storage_json
    except ValueError as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def claw_extension_path(**kw) -> str:
    """返回扩展目录路径（用于 Chrome 开发者模式加载）."""
    return json.dumps({
        "extension_path": ClawBridge.extension_path(),
        "native_host_installed": ClawBridge.native_host_installed(),
        "instructions": (
            "1. 打开 chrome://extensions/\n"
            "2. 开启右上角开发者模式\n"
            "3. 点击「加载已解压的扩展程序」\n"
            "4. 选择上述 extension_path 目录\n"
            "5. 固定 Claw 到工具栏并打开侧边栏"
        ),
    }, ensure_ascii=False)


# ── 异步浏览器工具（通过 MCP 调用真实 Chrome）────────────────

def claw_navigate(url: str = "", **kw) -> str:
    """通过真实 Chrome 导航到 URL（保留登录态）."""
    import asyncio
    bridge = _get_bridge()
    return asyncio.run(bridge.call_tool("navigate", {"url": url}))


def claw_screenshot(**kw) -> str:
    """通过真实 Chrome 截图."""
    import asyncio
    bridge = _get_bridge()
    return asyncio.run(bridge.call_tool("screenshot", {}))


def claw_click(selector: str = "", **kw) -> str:
    """通过真实 Chrome 点击元素."""
    import asyncio
    bridge = _get_bridge()
    return asyncio.run(bridge.call_tool("click", {"selector": selector}))


def claw_type(selector: str = "", text: str = "", **kw) -> str:
    """通过真实 Chrome 在输入框输入文本."""
    import asyncio
    bridge = _get_bridge()
    return asyncio.run(bridge.call_tool("type", {"selector": selector, "text": text}))


def claw_get_text(selector: str = "", **kw) -> str:
    """通过真实 Chrome 获取元素文本."""
    import asyncio
    bridge = _get_bridge()
    return asyncio.run(bridge.call_tool("get_text", {"selector": selector}))


def claw_evaluate(script: str = "", **kw) -> str:
    """通过真实 Chrome 执行 JavaScript."""
    import asyncio
    bridge = _get_bridge()
    return asyncio.run(bridge.call_tool("evaluate", {"script": script}))


# ── 注册函数 ────────────────────────────────────────────────

def register_all(registry: ToolRegistry):
    """注册所有 claw-in-chrome 工具到 LAAP 工具注册表."""
    tools = [
        # 诊断与配置
        ("claw_doctor", claw_doctor,
         "Claw in Chrome 环境诊断（人类可读报告）"),
        ("claw_doctor_json", claw_doctor_json,
         "Claw in Chrome 环境诊断（JSON 格式）"),
        ("claw_presets", claw_presets,
         "列出所有国产模型供应商预设"),
        ("claw_build_config", claw_build_config,
         "根据预设和 API Key 生成可导入扩展的配置 JSON"),
        ("claw_extension_path", claw_extension_path,
         "返回扩展目录路径和安装说明"),
        # 真实浏览器操作（通过 MCP）
        ("claw_navigate", claw_navigate,
         "通过真实 Chrome 导航到 URL（保留登录态/Cookie）"),
        ("claw_screenshot", claw_screenshot,
         "通过真实 Chrome 截图"),
        ("claw_click", claw_click,
         "通过真实 Chrome 点击元素（CSS 选择器）"),
        ("claw_type", claw_type,
         "通过真实 Chrome 在输入框输入文本"),
        ("claw_get_text", claw_get_text,
         "通过真实 Chrome 获取元素文本"),
        ("claw_evaluate", claw_evaluate,
         "通过真实 Chrome 执行 JavaScript"),
    ]
    for name, handler, desc in tools:
        registry.register(Tool(
            name=name, handler=handler,
            description=desc, category="browser.real_chrome",
        ))
    logger.info(f"Registered {len(tools)} Claw in Chrome tools")

    # 同时注册到 MCP 配置
    try:
        from laap.integrations.claw_in_chrome.adapter import register_mcp_server
        register_mcp_server()
    except Exception as e:
        logger.debug(f"MCP server registration deferred: {e}")
