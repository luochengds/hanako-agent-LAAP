"""TitleGenerator — 标题生成"""
from typing import Optional

class TitleGenerator:
    @staticmethod
    def generate(text: str, max_len: int = 50) -> str:
        if len(text) <= max_len:
            return text
        words = text.split()
        title = ""
        for w in words:
            if len(title) + len(w) + 1 > max_len:
                break
            title += " " + w if title else w
        return title + "..." if title != text[:max_len] else title
    @staticmethod
    def from_first_line(text: str) -> str:
        first = text.split("\n")[0].strip()
        return first[:50] + "..." if len(first) > 50 else first
