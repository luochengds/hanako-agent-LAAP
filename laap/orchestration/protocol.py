"""
LAAP — Agent 间通信协议

DEPRECATED — 本模块已废弃
=========================
废弃原因：AgentMessage/MessageType/MessageRouter 语义已合并至 laap.orchestration.primitives 中的 AetherMessage/MessageType/MessageRouter
替代实现：laap/orchestration/primitives.py
废弃时间：2026-07-11
登记位置：legacy/INDEX.md

代码保留目的：保持向后兼容，所有历史导入与符号名继续可用。
"""
from __future__ import annotations
import warnings

from laap.orchestration.primitives import (
    AetherAddress,
    AetherMessage,
    MessageRouter,
    MessageType,
)

warnings.warn(
    "laap.orchestration.protocol is deprecated; "
    "use laap.orchestration.primitives (AetherMessage, MessageType, MessageRouter) instead.",
    DeprecationWarning,
    stacklevel=2,
)

# Backward-compatible aliases
AgentMessage = AetherMessage
AgentAddress = AetherAddress
