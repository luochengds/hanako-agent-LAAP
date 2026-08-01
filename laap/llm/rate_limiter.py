"""laap/llm/rate_limiter.py — LLM 限流器

移植自 laap/agent_core/llm_provider.py 的 TokenBucket, 并增加接入逻辑。
旧版 TokenBucket 定义了但从未被 chat/stream_chat 调用 (形同虚设)。
本模块提供接入逻辑, 可注入到 LLMProvider 基类。
"""
from __future__ import annotations
import threading
import time
import logging
from typing import Optional, Dict
from collections import defaultdict

logger = logging.getLogger("laap.llm.rate_limiter")


class TokenBucket:
    """令牌桶限流器 — 线程安全。

    Args:
        rate: 每秒补充的令牌数 (requests/sec)
        capacity: 桶容量 (允许突发)
    """

    def __init__(self, rate: float = 10.0, capacity: float = 20.0):
        self.rate = rate
        self.capacity = capacity
        self._tokens = capacity
        self._last_refill = time.monotonic()
        self._lock = threading.RLock()

    def acquire(self, tokens: float = 1.0, timeout: Optional[float] = None) -> bool:
        """获取令牌, 返回是否成功。

        Args:
            tokens: 需要的令牌数
            timeout: 最大等待时间 (秒), None 表示不等待
        """
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._lock:
            while True:
                self._refill()
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return True
                if deadline is None:
                    return False
                # 计算等待时间
                needed = tokens - self._tokens
                wait = needed / self.rate
                if time.monotonic() + wait > deadline:
                    return False
                # 释放锁等待
                pass  # 在锁内等待会阻塞其他线程, 这里选择不等待
                return False

    def _refill(self):
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self.capacity, self._tokens + elapsed * self.rate)
        self._last_refill = now

    def try_acquire(self, tokens: float = 1.0) -> bool:
        """非阻塞尝试获取令牌。"""
        with self._lock:
            self._refill()
            if self._tokens >= tokens:
                self._tokens -= tokens
                return True
            return False

    def wait_acquire(self, tokens: float = 1.0, max_wait: float = 60.0) -> bool:
        """阻塞等待获取令牌 (在锁外 sleep)。"""
        deadline = time.monotonic() + max_wait
        while time.monotonic() < deadline:
            if self.try_acquire(tokens):
                return True
            time.sleep(0.05)
        return False

    @property
    def available_tokens(self) -> float:
        with self._lock:
            self._refill()
            return self._tokens


# ── per-provider 限流管理 ────────────────────────────────────────

# 默认速率 (requests/sec) — 移植自 agent_core/llm_provider.py
DEFAULT_RATES: Dict[str, tuple] = {
    # provider: (rate, capacity)
    "deepseek": (10, 20),
    "openai": (20, 40),
    "anthropic": (15, 30),
    "google": (10, 20),
    "openrouter": (10, 20),
    "groq": (30, 60),
    "together": (10, 20),
    "mistral": (10, 20),
    "cohere": (10, 20),
    "perplexity": (5, 10),
    "alibaba": (10, 20),
    "baidu": (5, 10),
    "zhipu": (10, 20),
    "moonshot": (10, 20),
    # 默认
    "_default": (5, 10),
}


class RateLimiter:
    """Per-provider 限流管理器。"""

    def __init__(self):
        self._buckets: Dict[str, TokenBucket] = {}
        self._lock = threading.RLock()

    def get_bucket(self, provider: str) -> TokenBucket:
        """获取或创建 provider 的令牌桶。"""
        with self._lock:
            if provider not in self._buckets:
                rate, capacity = DEFAULT_RATES.get(
                    provider, DEFAULT_RATES["_default"])
                self._buckets[provider] = TokenBucket(rate=rate, capacity=capacity)
            return self._buckets[provider]

    def acquire(self, provider: str, timeout: Optional[float] = None) -> bool:
        """为 provider 获取 1 个令牌。"""
        bucket = self.get_bucket(provider)
        return bucket.try_acquire() if timeout is None else bucket.wait_acquire(max_wait=timeout)

    def set_rate(self, provider: str, rate: float, capacity: Optional[float] = None):
        """动态调整 provider 的速率。"""
        with self._lock:
            cap = capacity if capacity is not None else rate * 2
            self._buckets[provider] = TokenBucket(rate=rate, capacity=cap)

    def get_stats(self) -> Dict[str, dict]:
        return {p: {"available": b.available_tokens,
                    "rate": b.rate, "capacity": b.capacity}
                for p, b in self._buckets.items()}

    def reset(self):
        with self._lock:
            self._buckets.clear()


# ── 全局单例 ─────────────────────────────────────────────────────

_rate_limiter = RateLimiter()


def get_rate_limiter() -> RateLimiter:
    """获取全局 RateLimiter 单例。"""
    return _rate_limiter


def acquire_for_provider(provider: str, timeout: Optional[float] = None) -> bool:
    """便捷函数: 为 provider 获取令牌。"""
    return _rate_limiter.acquire(provider, timeout)


__all__ = [
    "TokenBucket", "RateLimiter", "DEFAULT_RATES",
    "get_rate_limiter", "acquire_for_provider",
]
