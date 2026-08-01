"""
LAAP Gateway — Hermes-compatible Structured Streaming Events

Mirrors Hermes gateway/stream_events.py for structured, typed event streaming.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class MessageChunk:
    """A chunk of streaming text from the agent."""
    text: str
    index: int = 0


@dataclass
class MessageStop:
    """Signal that the response stream is complete."""
    content: str
    tool_calls: Optional[List[Dict]] = None


@dataclass
class Commentary:
    """Internal commentary / Chain-of-Thought from agent."""
    text: str
    turn: int = 0


@dataclass
class ToolCallChunk:
    """A tool call detected during streaming."""
    name: str
    args: Dict[str, Any]
    id: str = ""
    index: int = 0


@dataclass
class ToolCallFinished:
    """Tool execution completed."""
    name: str
    result: str
    duration: float = 0.0
    success: bool = True


@dataclass
class LongToolHint:
    """Hint to the UI that a long-running tool is executing."""
    name: str
    eta: float = 0.0


@dataclass
class GatewayNotice:
    """Gateway-level notice (connection, auth, rate-limit)."""
    type: str  # "connected", "disconnected", "rate_limited", "error"
    message: str = ""
    data: Any = None


@dataclass
class GatewayEvent:
    """Unified gateway event wrapper."""
    type: str  # "message", "tool_call", "tool_result", "commentary", "error", "done"
    data: Any = None
    session_id: str = ""
    platform: str = ""
    chat_id: str = ""
    user_id: str = ""


# ── Event vocabulary keys (for dict-based dispatch) ──

EVENT_TOKEN = "token"
EVENT_TOOL_CALL = "tool_call"
EVENT_TOOL_RESULT = "tool_result"
EVENT_DONE = "done"
EVENT_ERROR = "error"
EVENT_COMMENTARY = "commentary"


def sse_format(event: str, data: Any) -> str:
    """Format an SSE message string."""
    import json
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def parse_sse_line(line: str) -> Optional[Dict]:
    """Parse a single SSE 'data: ...' line into a dict. Returns None on [DONE]."""
    if not line.startswith("data: "):
        return None
    payload = line[6:]
    if payload == "[DONE]":
        return None
    import json
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        return None
