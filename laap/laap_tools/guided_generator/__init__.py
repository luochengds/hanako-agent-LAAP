"""
guided_generator — Structured Output Generation for LLMs.

Enforces format constraints (grammar / JSON Schema) during LLM generation
via llama.cpp's completion API. Part of Aris cognitive control path 2.
"""

from .generator import GuidedGenerator, GenerationResult, ValidationResult

__all__ = [
    "GuidedGenerator",
    "GenerationResult",
    "ValidationResult",
]
