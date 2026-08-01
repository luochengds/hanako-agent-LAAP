"""
Integrators — LLM 接口集成

封装对不同 LLM providers 的 API 调用：
  - llama_cpp.py:   → llama.cpp server completion API
  - openai_api.py:  → OpenAI 兼容 API (DeepSeek 降级)
"""

from .llama_cpp import LlamaCppIntegrator
from .openai_api import OpenAIIntegrator

__all__ = ["LlamaCppIntegrator", "OpenAIIntegrator"]
