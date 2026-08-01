"""LAAP FinQuant Domain SDK — Agent configuration dataclasses."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class LLMConfig:
    """Configuration for the LLM that drives the agent.

    Uses an OpenAI-compatible Chat Completions API so any compliant
    provider works (OpenAI, DeepSeek, Zhipu, MiniMax, local vLLM/ollama
    via laap.llm.transports). Keep it simple — no provider-specific
    branching here; the LAAP llm layer handles that if you swap in
    ``llm.factory``.
    """

    provider: str = "openai"
    model: str = "gpt-4o"
    api_key: str = ""
    base_url: str = "https://api.openai.com/v1"
    temperature: float = 0.3
    max_tokens: int = 2048
    # Streaming keeps voice mode latency low (first-byte TTS fires early).
    stream: bool = True
    # Optional system-prompt persona suffix injected after the auto-built
    # platform-aware prompt. Lets the user style the agent ("中文量化分析师").
    persona: str = ""
    # Reasoning effort hint for providers that support it (e.g. deepseek-reasoner).
    thinking: bool = False
    request_timeout: float = 90.0


@dataclass
class VoiceConfig:
    """Configuration for the TTS/ASR voice interface.

    ASR: a callable that records + transcribes (pluggable; defaults to a
         no-op that the host UI overrides). LAAP's ``voicetools`` and
         ``audio.providers`` provide ready implementations.
    TTS: provider name served by ``laap.audio.service`` (aliyun/doubao/
         minimax/openai/microsoft/tencent/xunfei/elevenlabs/local).
    """

    tts_provider: str = "local"
    tts_voice: str = ""
    tts_speed: float = 1.0
    # ASR is intentionally a swappable callable: (async) -> str of transcript.
    # Host wires up whisper / cloud ASR / laap voicetools.
    asr_callable: Optional[object] = None
    # Auto-speak the agent's text replies (voice mode). When False, the
    # agent is text-only and VoiceInterface is inert.
    auto_speak: bool = True
    # Sample rate for TTS audio (matched to provider capabilities).
    sample_rate: int = 24000
    # Wake-word / push-to-talk: "ptt" waits for an explicit start signal,
    # "wake" runs a detector in the background. PTT is simpler & safer.
    mode: str = "ptt"


@dataclass
class AgentConfig:
    """Top-level configuration for :class:`FinQuantAgent`."""

    llm: LLMConfig = field(default_factory=LLMConfig)
    voice: VoiceConfig = field(default_factory=VoiceConfig)
    # Max ReAct rounds per turn before forcing a final reply.
    max_tool_rounds: int = 12
    # Max consecutive tool failures before bailing out.
    max_consecutive_failures: int = 3
    # Inject the live platform snapshot into every system prompt (costs
    # tokens but keeps the agent grounded in reality). Recommended on.
    inject_platform_state: bool = True
    # Verbose logging of tool calls / LLM rounds.
    verbose: bool = False
    # Optional override for the agent's displayed name.
    agent_name: str = "FinQuant Agent"


__all__ = ["AgentConfig", "LLMConfig", "VoiceConfig"]
