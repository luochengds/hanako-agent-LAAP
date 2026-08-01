"""LAAP FinQuant Domain SDK — Financial Agent subpackage.

A truly powerful financial agent that lives *inside* the FinQuant SDK.
Unlike the 5 deterministic cognitive actors (MarketWatcher/Analyst/...),
this agent is LLM-driven and can:

1. **Provide extremely professional analysis** — combines zero-token
   harness functions (indicators, factors, risk, statistics, backtest)
   with an LLM reasoning loop (ReAct) to produce analyst-grade written
   research, the way a human quant would.
2. **Know the platform's internal state** — introspects the live SDK:
   which actors are spawned, which harness functions are registered,
   connector health & current positions/P&L, safety-policy limits,
   species templates, recent CognitiveBus events. It answers questions
   about "how is the platform doing right now" with ground truth.
3. **Be controlled by TTS/ASR dialogue** — a voice interface lets the
   user speak to the platform ("run a backtest on the dual-MA strategy
   over the last year", "what's my exposure to crypto?", "place a paper
   buy for 100 AAPL") and hear spoken responses, BaiLongma-style.

Architecture::

    ┌─────────────────────────────────────────────────────────┐
    │                   FinQuantAgent                         │
    │  ┌───────────────┐   ┌───────────────┐                  │
    │  │ VoiceInterface│◄──┤ Conversation  │ (ReAct loop)     │
    │  │  ASR ▶ TTS    │   │   Loop        │                  │
    │  └───────────────┘   └───────┬───────┘                  │
    │                              │                          │
    │              ┌───────────────▼───────────────┐          │
    │              │     ToolDispatcher (15 tools) │          │
    │              └───────┬───────────────┬───────┘          │
    │                      │               │                  │
    │   ┌──────────────────▼──┐  ┌─────────▼────────────┐     │
    │   │ PlatformIntrospection│  │ Harness / Actors /   │     │
    │   │ (live SDK snapshot)  │  │ Connector / Safety   │     │
    │   └──────────────────────┘  └──────────────────────┘     │
    └─────────────────────────────────────────────────────────┘

Public API::

    from laap.domain_sdks.finquant.agent import FinQuantAgent, AgentConfig

    agent = FinQuantAgent(
        llm_config={"provider": "openai", "model": "gpt-4o",
                    "api_key": "...", "base_url": "..."},
        harness_registry=runtime.harness_registry,
        actor_system=runtime.actor_system,
        connector=sdk.connector,
        safety_policy=sdk.get_safety_policy(),
        species_library=runtime.species_library,
    )
    await agent.start()

    # Text dialogue
    reply = await agent.chat("分析一下当前持仓的风险敞口")

    # Voice dialogue (blocks until user stops speaking)
    reply = await agent.voice_chat()
"""

from __future__ import annotations

from laap.domain_sdks.finquant.agent.config import AgentConfig, LLMConfig, VoiceConfig
from laap.domain_sdks.finquant.agent.finquant_agent import FinQuantAgent
from laap.domain_sdks.finquant.agent.platform_introspection import (
    PlatformIntrospector,
    PlatformSnapshot,
)
from laap.domain_sdks.finquant.agent.voice_interface import VoiceInterface

__all__ = [
    "FinQuantAgent",
    "AgentConfig",
    "LLMConfig",
    "VoiceConfig",
    "PlatformIntrospector",
    "PlatformSnapshot",
    "VoiceInterface",
]
