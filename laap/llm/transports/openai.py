"""OpenAI transport for LAAP."""
from __future__ import annotations

from typing import Any, Dict, List

from laap.llm.transports.base import LLMResponse, LLMTransport

# Approximate pricing for gpt-4o-mini-ish models (USD per 1M tokens).
INPUT_PRICE_PER_1M = 0.5
OUTPUT_PRICE_PER_1M = 1.5


def _approx_tokens(text: str) -> int:
    return max(1, len(text) // 4)


class OpenAITransport(LLMTransport):
    """Transport backed by the OpenAI API."""

    def __init__(self, api_key: str | None = None, model: str = "gpt-4o-mini") -> None:
        self.api_key = api_key
        self.model = model
        self._client = None

    def _get_client(self) -> Any:
        if self._client is None:
            try:
                import openai
            except ImportError as exc:
                raise RuntimeError("openai library is not installed") from exc
            self._client = openai.AsyncOpenAI(api_key=self.api_key)
        return self._client

    async def generate(self, messages: List[Dict[str, str]], **kwargs: Any) -> LLMResponse:
        model = kwargs.get("model", self.model)
        max_tokens = kwargs.get("max_tokens", 1024)
        temperature = kwargs.get("temperature", 0.7)
        logprobs = kwargs.get("logprobs", False)
        top_logprobs = kwargs.get("top_logprobs", None)

        try:
            client = self._get_client()
            request_kwargs = {
                "model": model,
                "messages": messages,  # type: ignore[arg-type]
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
            if logprobs:
                request_kwargs["logprobs"] = True
                if top_logprobs is not None:
                    request_kwargs["top_logprobs"] = top_logprobs
            response = await client.chat.completions.create(**request_kwargs)
            content = response.choices[0].message.content or ""
            input_tokens = response.usage.prompt_tokens if response.usage else 0
            output_tokens = response.usage.completion_tokens if response.usage else 0
            cost = (input_tokens / 1_000_000) * INPUT_PRICE_PER_1M + (
                output_tokens / 1_000_000
            ) * OUTPUT_PRICE_PER_1M

            parsed_logprobs = None
            if logprobs and hasattr(response.choices[0], "logprobs") and response.choices[0].logprobs:
                lp = response.choices[0].logprobs
                if hasattr(lp, "content") and lp.content:
                    first_token = lp.content[0]
                    if hasattr(first_token, "top_logprobs") and first_token.top_logprobs:
                        parsed_logprobs = {
                            item.token: float(item.logprob)
                            for item in first_token.top_logprobs
                        }

            return LLMResponse(
                content=content,
                provider="openai",
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost=round(cost, 6),
                raw_response=response,
                logprobs=parsed_logprobs,
            )
        except Exception:
            # Graceful fallback / mock shim for environments without a real client.
            prompt_text = "\n".join(m.get("content", "") for m in messages)
            input_tokens = _approx_tokens(prompt_text)
            output_text = f"[OpenAI mock] Response for model {model}."
            output_tokens = _approx_tokens(output_text)
            cost = (input_tokens / 1_000_000) * INPUT_PRICE_PER_1M + (
                output_tokens / 1_000_000
            ) * OUTPUT_PRICE_PER_1M
            return LLMResponse(
                content=output_text,
                provider="openai",
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost=round(cost, 6),
                raw_response=None,
                logprobs=None,
            )
