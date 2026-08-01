"""Base abstractions for the LAAP LLM transport layer."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class LLMResponse:
    """Standardized response returned by every transport."""

    content: str
    provider: str
    input_tokens: int
    output_tokens: int
    cost: float
    raw_response: Any
    logprobs: Optional[Dict[str, float]] = None


class LLMTransport(ABC):
    """Abstract async LLM transport."""

    @abstractmethod
    async def generate(self, messages: List[Dict[str, str]], **kwargs: Any) -> LLMResponse:
        """Generate a completion for the provided conversation messages."""
        ...
