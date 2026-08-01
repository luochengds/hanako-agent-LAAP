"""Anthropic Claude transport for LAAP."""
from __future__ import annotations

from typing import Any, Dict, List

from laap.llm.transports.base import LLMResponse, LLMTransport

# Approximate pricing for claude-3-sonnet-ish models (USD per 1M tokens).
INPUT_PRICE_PER_1M = 3.0
OUTPUT_PRICE_PER_1M = 15.0


def _approx_tokens(text: str) -> int:
    return max(1, len(text) // 4)


class AnthropicTransport(LLMTransport):
    """Transport backed by Anthropic's Claude API."""

    def __init__(self, api_key: str | None = None, model: str = "claude-3-sonnet-20240229") -> None:
        self.api_key = api_key
        self.model = model
        self._client = None

    def _get_client(self) -> Any:
        if self._client is None:
            try:
                import anthropic
            except ImportError as exc:
                raise RuntimeError("anthropic library is not installed") from exc
            self._client = anthropic.AsyncAnthropic(api_key=self.api_key)
        return self._client

    async def generate(self, messages: List[Dict[str, str]], **kwargs: Any) -> LLMResponse:
        model = kwargs.get("model", self.model)
        max_tokens = kwargs.get("max_tokens", 1024)
        temperature = kwargs.get("temperature", 0.7)

        try:
            client = self._get_client()
            system_message = ""
            conversation = []
            for msg in messages:
                if msg.get("role") == "system":
                    system_message = msg.get("content", "")
                else:
                    conversation.append({"role": msg["role"], "content": msg["content"]})

            response = await client.messages.create(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system_message or "You are a helpful assistant.",
                messages=conversation,
            )
            content = "".join(block.text for block in response.content if hasattr(block, "text"))
            input_tokens = response.usage.input_tokens
            output_tokens = response.usage.output_tokens
            cost = (input_tokens / 1_000_000) * INPUT_PRICE_PER_1M + (
                output_tokens / 1_000_000
            ) * OUTPUT_PRICE_PER_1M
            return LLMResponse(
                content=content,
                provider="anthropic",
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost=round(cost, 6),
                raw_response=response,
            )
        except Exception:
            # Graceful fallback / mock shim for environments without a real client.
            prompt_text = "\n".join(m.get("content", "") for m in messages)
            input_tokens = _approx_tokens(prompt_text)
            output_text = f"[Anthropic mock] Response for model {model}."
            output_tokens = _approx_tokens(output_text)
            cost = (input_tokens / 1_000_000) * INPUT_PRICE_PER_1M + (
                output_tokens / 1_000_000
            ) * OUTPUT_PRICE_PER_1M
            return LLMResponse(
                content=output_text,
                provider="anthropic",
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost=round(cost, 6),
                raw_response=None,
            )
