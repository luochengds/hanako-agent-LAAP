"""LAAP — 简化版 LLM Engine 抽象层。

为需要单一 `generate(prompt) -> (text, usage)` 接口的组件提供轻量封装，
屏蔽底层 provider 细节。可与 `laap.llm.provider` 共存，互为补充。
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal, Tuple

logger = logging.getLogger("laap.llm.engine")


def estimate_tokens(text: str) -> int:
    """粗略估算 token 数量：按字符数 / 4 计算。"""
    return len(text) // 4


@dataclass
class TokenUsage:
    """单次生成调用的 token 与成本统计。"""

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    source: Literal["local", "remote"]
    estimated_cost_usd: float


class LLMEngine(ABC):
    """LLM 生成引擎抽象基类。"""

    @property
    @abstractmethod
    def name(self) -> str:
        """引擎名称，用于日志与路由展示。"""
        ...

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        max_tokens: int = 512,
        temperature: float = 0.7,
    ) -> Tuple[str, TokenUsage]:
        """调用模型生成文本并返回 (text, usage)。"""
        ...


class OllamaEngine(LLMEngine):
    """通过 Ollama `/api/generate` 调用本地模型。"""

    def __init__(self, base_url: str = "http://localhost:11434", model: str = "llama3.2"):
        self.base_url = base_url.rstrip("/")
        self.model = model

    @property
    def name(self) -> str:
        return f"ollama:{self.model}"

    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        max_tokens: int = 512,
        temperature: float = 0.7,
    ) -> Tuple[str, TokenUsage]:
        import httpx

        full_prompt = f"{system_prompt}\n\n{prompt}" if system_prompt else prompt
        payload = {
            "model": self.model,
            "prompt": full_prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }

        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
                resp = await client.post(f"{self.base_url}/api/generate", json=payload)
                resp.raise_for_status()
                data = resp.json()
        except (httpx.ConnectError, httpx.NetworkError) as exc:
            raise ConnectionError(
                f"Ollama server unavailable at {self.base_url}: {exc}"
            ) from exc

        text = data.get("response", "") if isinstance(data, dict) else ""
        prompt_tokens = estimate_tokens(full_prompt)
        completion_tokens = estimate_tokens(text)
        usage = TokenUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            source="local",
            estimated_cost_usd=0.0,
        )
        return text, usage


class RemoteFallbackEngine(LLMEngine):
    """优先使用主引擎，失败时自动回退到备用引擎。"""

    def __init__(self, primary: LLMEngine, fallback: LLMEngine):
        self.primary = primary
        self.fallback = fallback

    @property
    def name(self) -> str:
        return f"fallback:{self.primary.name}->{self.fallback.name}"

    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        max_tokens: int = 512,
        temperature: float = 0.7,
    ) -> Tuple[str, TokenUsage]:
        try:
            return await self.primary.generate(
                prompt,
                system_prompt=system_prompt,
                max_tokens=max_tokens,
                temperature=temperature,
            )
        except Exception as exc:
            logger.warning(
                "Primary LLM engine %s failed (%s), falling back to %s",
                self.primary.name,
                exc,
                self.fallback.name,
            )
            return await self.fallback.generate(
                prompt,
                system_prompt=system_prompt,
                max_tokens=max_tokens,
                temperature=temperature,
            )


class MockLLMEngine(LLMEngine):
    """固定返回预设响应的测试用引擎。"""

    def __init__(self, response: str = "mock response", name: str = "mock"):
        self._response = response
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        max_tokens: int = 512,
        temperature: float = 0.7,
    ) -> Tuple[str, TokenUsage]:
        usage = TokenUsage(
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            source="local",
            estimated_cost_usd=0.0,
        )
        return self._response, usage
