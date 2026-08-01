"""ChatCompletionHelpers — 聊天补全辅助"""
from __future__ import annotations
import json, logging, time
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("agent_core.chat_helpers")

class ChatCompletionHelpers:
    @staticmethod
    def format_messages(system: str, history: List[Dict], user_msg: str) -> List[Dict]:
        msgs = [{"role": "system", "content": system}]
        for h in history[-10:]:
            msgs.append(h)
        msgs.append({"role": "user", "content": user_msg})
        return msgs
    
    @staticmethod
    def count_tokens(messages: List[Dict]) -> int:
        total = 0
        for m in messages:
            total += len(m.get("content", "")) // 2 + 10
        return total
    
    @staticmethod
    def parse_tool_calls(response: Dict) -> List[Dict]:
        tools = []
        for choice in response.get("choices", []):
            msg = choice.get("message", {})
            for tc in msg.get("tool_calls", []):
                tools.append({
                    "id": tc.get("id", ""),
                    "type": tc.get("type", "function"),
                    "function": {
                        "name": tc.get("function", {}).get("name", ""),
                        "arguments": tc.get("function", {}).get("arguments", "{}")
                    }
                })
        return tools
    
    @staticmethod
    def parse_stream_chunk(chunk: bytes) -> Tuple[str, List[Dict]]:
        text = chunk.decode('utf-8', errors='replace')
        content = ""
        tool_calls = []
        if text.startswith("data: "):
            data = text[6:].strip()
            if data and data != "[DONE]":
                try:
                    parsed = json.loads(data)
                    delta = parsed.get("choices", [{}])[0].get("delta", {})
                    content = delta.get("content", "")
                    for tc in delta.get("tool_calls", []):
                        tool_calls.append({
                            "index": tc.get("index", 0),
                            "id": tc.get("id", ""),
                            "function": tc.get("function", {})
                        })
                except: pass
        return content, tool_calls
    
    @staticmethod
    def estimate_cost(tokens_in: int, tokens_out: int, model: str = "deepseek-v4-flash") -> float:
        pricing = {
            "deepseek-v4-flash": {"in": 0.0001, "out": 0.0004},
            "gpt-4": {"in": 0.003, "out": 0.006},
            "claude-3-sonnet": {"in": 0.003, "out": 0.015},
        }
        p = pricing.get(model, {"in": 0.001, "out": 0.002})
        return (tokens_in * p["in"] + tokens_out * p["out"]) / 1000
    
    @staticmethod
    def truncate_to_budget(messages: List[Dict], max_tokens: int) -> List[Dict]:
        while ChatCompletionHelpers.count_tokens(messages) > max_tokens and len(messages) > 3:
            messages.pop(1)
        return messages
