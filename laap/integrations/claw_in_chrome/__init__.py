# -*- coding: utf-8 -*-
"""LAAP × Claw in Chrome 集成适配器.

Claw in Chrome 是一个 Chrome 扩展，把 AI 助手放进浏览器侧边栏，
支持自定义模型供应商（Anthropic / OpenAI Chat / OpenAI Responses 三种协议格式），
并通过 claw-in-chrome-mcp 提供 stdio MCP server，让 AI IDE 可以控制真实浏览器。

本适配器：
    - 注册 claw-in-chrome MCP server 为 LAAP 的一个 stdio 后端
    - 预置国产模型供应商配置（通义/文心/智谱/DeepSeek/Kimi/百川/零一/MiniMax 等）
    - 提供 ChromeRealBrowser 工具集，走 MCP 调用真实浏览器（保留登录态/Cookie）
    - 与现有 Playwright browser_auto.py 互补：Playwright = 隔离沙箱，Claw = 真实浏览器

Usage:
    from laap.integrations.claw_in_chrome import register_all, ClawBridge

    register_all(registry)              # 自动注册工具
    bridge = ClawBridge()               # 编程式访问
    report = bridge.doctor_report()
"""

from __future__ import annotations

from laap.integrations.claw_in_chrome.adapter import ClawBridge
from laap.integrations.claw_in_chrome.tools import register_all

__all__ = ["ClawBridge", "register_all"]
__version__ = "1.0.66.8"  # 对齐 claw-in-chrome 扩展版本
