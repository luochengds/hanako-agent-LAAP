"""Fallback transport that retries and chains multiple transports."""
from __future__ import annotations

from typing import Any, Dict, List

from laap.llm.transports.base import LLMResponse, LLMTransport


class FallbackTransport(LLMTransport):
    """Try each wrapped transport up to ``retries`` times, returning the first success."""

    def __init__(self, transports: List[LLMTransport], retries: int = 2) -> None:
        self.transports = transports
        self.retries = retries

    async def generate(self, messages: List[Dict[str, str]], **kwargs: Any) -> LLMResponse:
        last_error: Exception | None = None
        for transport in self.transports:
            for attempt in range(self.retries):
                try:
                    return await transport.generate(messages, **kwargs)
                except Exception as exc:
                    last_error = exc
                    continue
        raise RuntimeError(
            f"All {len(self.transports)} transports failed after {self.retries} retries each."
        ) from last_error
