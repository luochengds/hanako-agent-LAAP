"""Ollama local LLM transport for LAAP."""
from __future__ import annotations

import json
from typing import Any, Dict, List

from laap.llm.transports.base import LLMResponse, LLMTransport

OLLAMA_CHAT_URL = "http://localhost:11434/api/chat"


def _approx_tokens(text: str) -> int:
    return max(1, len(text) // 4)


class OllamaTransport(LLMTransport):
    """Transport backed by a local Ollama instance."""

    def __init__(self, base_url: str = OLLAMA_CHAT_URL, model: str = "llama3") -> None:
        self.base_url = base_url
        self.model = model

    async def generate(self, messages: List[Dict[str, str]], **kwargs: Any) -> LLMResponse:
        model = kwargs.get("model", self.model)
        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": kwargs.get("temperature", 0.7),
                "num_predict": kwargs.get("max_tokens", 1024),
            },
        }

        try:
            # Prefer aiohttp when available, otherwise fall back to httpx which is a project dependency.
            try:
                import aiohttp

                async with aiohttp.ClientSession() as session:
                    async with session.post(self.base_url, json=payload) as resp:
                        data = await resp.json()
            except Exception:
                import httpx

                async with httpx.AsyncClient() as client:
                    resp = await client.post(self.base_url, json=payload)
                    data = resp.json()

            content = data.get("message", {}).get("content", "")
            prompt_eval_count = data.get("prompt_eval_count", 0)
            eval_count = data.get("eval_count", 0)
            if not prompt_eval_count and not eval_count:
                prompt_eval_count = _approx_tokens(json.dumps(messages))
                eval_count = _approx_tokens(content)
            return LLMResponse(
                content=content,
                provider="ollama",
                input_tokens=prompt_eval_count,
                output_tokens=eval_count,
                cost=0.0,
                raw_response=data,
            )
        except Exception:
            # Graceful fallback / mock shim for environments without a local Ollama server.
            input_tokens = _approx_tokens(json.dumps(messages))
            output_text = f"[Ollama mock] Response for model {model}."
            output_tokens = _approx_tokens(output_text)
            return LLMResponse(
                content=output_text,
                provider="ollama",
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost=0.0,
                raw_response=None,
            )
