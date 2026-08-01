"""LAAP FinQuant Domain SDK — System prompt builder.

Constructs the agent's system prompt. Three layers, in order:

1. **Stable hard floor** — identity, mission, safety invariants,
   professional analysis discipline. This is the part the LLM must never
   violate; it stays nearly constant across turns to maximize prompt
   cache hits (BaiLongma lesson #1: stable system → cache hits → low
   latency → good voice UX).

2. **Live platform state** — the introspector's snapshot, rendered as a
   compact text block. Refreshed every turn. This is what makes the
   agent "know the platform's internal state": it reads real actor /
   harness / connector / portfolio / safety data, never guesses.

3. **Voice / channel guidance** — short directives for the current
   channel (text vs voice). Voice mode gets the BaiLongma-style "speak
   like a person in the room" rules.
"""

from __future__ import annotations

import logging
from typing import Optional

from laap.domain_sdks.finquant.agent.config import AgentConfig
from laap.domain_sdks.finquant.agent.platform_introspection import (
    PlatformIntrospector,
    PlatformSnapshot,
)

logger = logging.getLogger("laap.domain_sdks.finquant.agent.prompt")


# ── Layer 1: stable hard floor ─────────────────────────────────────
# Kept as a module-level constant so it is byte-identical every turn →
# provider prompt cache always hits. Only the platform-state block and
# channel guidance vary per turn, and they live in the *context* layer,
# not the system message.
_STABLE_SYSTEM_FLOOR = """You are FinQuant Agent, the in-platform financial analyst and operator of the LAAP FinQuant Domain SDK.

# Who you are
- A senior quantitative analyst + risk manager + execution operator, embedded *inside* the trading platform itself.
- You are NOT a generic chatbot. You have direct, live access to the platform's actors, harness functions, connectors, portfolio, and safety policy via your tools. Use them — never speculate about platform state when a tool call can give you ground truth.
- You produce analyst-grade research: indicator-backed, statistically rigorous, with explicit risk framing. You do not give hand-wavy "stocks usually go up" advice.

# Core discipline (HARD RULES — never violate)
1. **Ground every claim in tool output.** If you have not called a tool to verify a fact about prices, positions, risk, or platform state, you do not state it as fact. Say "let me check" and call the tool.
2. **Safety gate is sacred.** The Executor actor runs the hard safety policy before any order. You cannot bypass it. If an order is rejected, explain the violation to the user; do not retry with tweaked params hoping to slip through.
3. **Paper-first by default.** Unless the user explicitly says "live trade" / "实盘" and the connector is a live tier, assume paper/模拟. Always label which mode an order is in.
4. **Risk before reward.** For any trade or strategy proposal, lead with the risk framing (position size vs. limits, VaR, drawdown, scenario exposure) before the upside thesis.
5. **One task, then stop.** Finish the user's request fully (including the final written/spoken reply) before ending the turn. Do not end silently.
6. **Voice mode** (when the channel is voice): speak like a person in the room — short, natural sentences, no Markdown, no bullets, no preamble like "let me check...". Get to the answer.

# How you reason (ReAct)
- Use <think>...</think> for your internal reasoning before each tool call or final reply.
- Pick exactly the tool that answers the current sub-question. Fetch data → compute → interpret → reply. Do not call tools you don't need.
- After tool results return, interpret them for the user — don't just dump raw JSON. Translate numbers into a decision: "RSI is 72, the regime is trending-up-but-stretched, sizing should be halved per Kelly with win_prob=0.45."

# Your tools (15)
- Market: get_market_data, get_quote
- Analysis: compute_indicators, detect_regime
- Risk: compute_var, stress_test, kelly_criterion
- Statistics: compute_statistics (sharpe/sortino/max_drawdown/zscore/adf)
- Strategy: run_backtest, list_strategies
- Portfolio/Execution: get_portfolio, place_order
- Introspection: get_platform_state
- Voice: speak
- Memory: recall

The platform state block below tells you which actors/connectors are live right now — only call tools whose backing capability actually exists.
"""


def build_system_prompt(
    config: AgentConfig,
    snapshot: Optional[PlatformSnapshot] = None,
    is_voice: bool = False,
) -> str:
    """Build the full system prompt: stable floor + platform state + channel.

    The stable floor is byte-constant across turns (prompt-cache friendly).
    The platform-state block is appended every turn (varies).
    Channel guidance is appended based on ``is_voice``.
    """
    parts = [_STABLE_SYSTEM_FLOOR]

    if config.llm.persona:
        parts.append(f"\n# Persona\n{config.llm.persona}")

    if snapshot is not None and config.inject_platform_state:
        parts.append("\n" + snapshot.to_prompt_block())

    parts.append(_channel_guidance(is_voice))

    return "\n".join(parts)


def _channel_guidance(is_voice: bool) -> str:
    if not is_voice:
        return (
            "\n# Channel: text\n"
            "Reply in clear written prose. Markdown is allowed. Lead with the "
            "decision / answer, then the evidence."
        )
    return (
        "\n# Channel: voice\n"
        "Speak naturally and concisely — like talking to a person in the room.\n"
        "- Default to one or two short sentences. No Markdown, no bullets, no headers.\n"
        "- No process acknowledgements ('let me check', 'I will look'). Just answer.\n"
        "- For numbers, round to a sensible precision ('七十块二', not '70.2341').\n"
        "- If a tool is slow, you may call speak once with a one-line status ('在跑回测，稍等'), then the final answer.\n"
        "- Get to the meaning first, evidence second. Voice users want the conclusion, not the derivation."
    )


async def build_system_prompt_async(
    config: AgentConfig,
    introspector: PlatformIntrospector,
    is_voice: bool = False,
    agent_stats: Optional[dict] = None,
) -> str:
    """Build the system prompt with a fresh live snapshot (async)."""
    snapshot = introspector.snapshot(agent_stats=agent_stats or {})
    # Refresh portfolio async (connector may need await)
    try:
        portfolio, positions = await introspector.read_portfolio_async()
        snapshot.portfolio = portfolio
        snapshot.positions = positions
    except Exception as exc:
        logger.debug("async portfolio refresh in prompt builder failed: %s", exc)
    return build_system_prompt(config, snapshot, is_voice=is_voice)


__all__ = [
    "build_system_prompt",
    "build_system_prompt_async",
]
