"""
StreamingMarkdown — Markdown streaming renderer for session search UI
"""
from __future__ import annotations
import re
from typing import List


class StreamingMarkdown:
    """Streaming Markdown renderer"""
    
    def __init__(self):
        self._buffer = ""
        self._segments: List[str] = []
    
    def render(self, text: str) -> str:
        if not text:
            return ""
        result = text
        result = re.sub(r'^### (.+)$', r'\033[1;36m\1\033[0m', result, flags=re.MULTILINE)
        result = re.sub(r'^## (.+)$', r'\033[1;34m\1\033[0m', result, flags=re.MULTILINE)
        result = re.sub(r'^# (.+)$', r'\033[1;33m\1\033[0m', result, flags=re.MULTILINE)
        result = re.sub(r'\*\*(.+?)\*\*', r'\033[1m\1\033[0m', result)
        result = re.sub(r'\*(.+?)\*', r'\033[3m\1\033[0m', result)
        result = re.sub(r'`(.+?)`', r'\033[7m\1\033[0m', result)
        return result
    
    def feed(self, token: str) -> str:
        self._buffer += token
        rendered = self.render(self._buffer)
        self._segments.append(rendered)
        return rendered
    
    def strip_markdown(self, text: str) -> str:
        result = text
        result = re.sub(r'^#+\s*', '', result, flags=re.MULTILINE)
        result = re.sub(r'\*\*(.+?)\*\*', r'\1', result)
        result = re.sub(r'\*(.+?)\*', r'\1', result)
        result = re.sub(r'`(.+?)`', r'\1', result)
        result = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', result)
        return result.strip()
    
    def reset(self):
        self._buffer = ""
        self._segments.clear()
