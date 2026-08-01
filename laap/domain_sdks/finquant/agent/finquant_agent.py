"""LAAP FinQuant Domain SDK — The Financial Agent (main orchestrator).

:cla FinQuantAgent` is the LLM-driven financial agent that lives inside
the FinQuant SDK. It wires together:

- a **platform introspector** (live SDK state),
- a **tool dispatcher** (15 tools bridging harness/actors/connector),
- a **voice interface** (TTS/ASR),
- an **LLM client** (OpenAI-compatible),
- a **ReAct conversation loop**,

and exposes a tiny public API: ``chat(text)`` and ``voice_chat()``.

Quick start::

    from laap.domain_sdks.finquant.agent import FinQuantAgent, AgentConfig, LLMConfig

    agent = FinQuantAgent(
        config=AgentConfig(llm=LLMConfig(api_key="sk-...", model="gpt-4o")),
        harness_registry=runtime.harness_registry,
        actor_system=runtime.actor_system,
        cognitive_bus=runtime.cognitive_bus,
        connector=sdk.connector,
        safety_policy=sdk.get_safety_policy(),
        species_library=runtime.species_library,
    )
    await agent.start()

    reply = await agent.chat("分析一下当前持仓的风险敞口，并给出对冲建议")
    print(reply)

    # Voice dialogue
    reply = await agent.voice_chat()
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Dict, List, Optional

from laap.domain_sdks.finquant.agent.config import AgentConfig, LLMConfig
from laap.domain_sdks.finquant.agent.conversation import ConversationLoop, TurnResult
from laap.domain_sdks.finquant.agent.platform_introspection import (
    PlatformIntrospector,
)
from laap.domain_sdks.finquant.agent.system_prompt import build_system_prompt_async
from laap.domain_sdks.finquant.agent.tools import ToolDispatcher
from laap.domain_sdks.finquant.agent.voice_interface import VoiceInterface

logger = logging.getLogger("laap.domain_sdks.finquant.agent")


# ── LLM client (OpenAI-compatible, swappable) ──────────────────────

class LLMClient:
    """Minimal OpenAI-compatible Chat Completions client.

    Uses the ``openai`` Python SDK if available (same as BaiLongma).
    Falls back to a raw ``httpx`` POST if the SDK is missing. Either way
    the interface presented to :class:`ConversationLoop` is::

        async def chat(system_prompt, messages, tools, temperature,
                       max_tokens, stream, on_stream, signal) -> dict
            returns {"content": str, "tool_calls": [...]}

    For richer provider support (DeepSeek thinking, Zhipu, MiniMax XML
    tools, Anthropic), swap this class out for ``laap.llm.factory``'s
    adapter — the protocol is identical.
    """

    def __init__(self, config: LLMConfig) -> None:
        self.config = config
        self._client = None
        self._init_client()

    def _init_client(self) -> None:
        if not self.config.api_key:
            logger.info("LLMClient: no api_key — agent will run in degraded mode")
            return
        try:
            from openai import AsyncOpenAI  # type: ignore

            self._client = AsyncOpenAI(
                api_key=self.config.api_key,
                base_url=self.config.base_url,
                timeout=self.config.request_timeout,
            )
        except ImportError:
            logger.warning(
                "openai SDK not installed; install `openai` or wire a custom LLM client"
            )

    async def chat(
        self,
        *,
        system_prompt: str,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        temperature: float = 0.3,
        max_tokens: int = 2048,
        stream: bool = True,
        on_stream: Optional[Any] = None,
        signal: Optional[asyncio.Event] = None,
    ) -> Dict[str, Any]:
        """One LLM round. Returns {"content": str, "tool_calls": [...]}."""
        if self._client is None:
            return {
                "content": "（LLM 未配置，无法生成回复。请在 AgentConfig.llm.api_key 设置 API Key。）",
                "tool_calls": [],
            }

        # Build the message list: system + the conversation tail.
        full_messages: List[Dict[str, Any]] = [
            {"role": "system", "content": system_prompt}
        ] + messages

        request_kwargs: Dict[str, Any] = {
            "model": self.config.model,
            "messages": full_messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            request_kwargs["tools"] = tools
            request_kwargs["tool_choice"] = "auto"

        # Provider-specific thinking flag (deepseek-reasoner etc.)
        if self.config.thinking and self.config.provider == "deepseek":
            request_kwargs["reasoning_effort"] = "high"

        try:
            if stream:
                return await self._chat_streamed(
                    request_kwargs, on_stream=on_stream, signal=signal
                )
            return await self._chat_unstreamed(request_kwargs, signal=signal)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("LLM chat failed: %s: %s", type(exc).__name__, exc)
            raise

    async def _chat_unstreamed(
        self, request_kwargs: Dict[str, Any], signal: Optional[asyncio.Event] = None
    ) -> Dict[str, Any]:
        resp = await self._client.chat.completions.create(**request_kwargs, stream=False)
        choice = resp.choices[0]
        content = choice.message.content or ""
        tool_calls = []
        if choice.message.tool_calls:
            for tc in choice.message.tool_calls:
                tool_calls.append(
                    {
                        "id": tc.id,
                        "name": tc.function.name,
                        "arguments": tc.function.arguments or "{}",
                    }
                )
        return {"content": content, "tool_calls": tool_calls}

    async def _chat_streamed(
        self,
        request_kwargs: Dict[str, Any],
        on_stream: Optional[Any] = None,
        signal: Optional[asyncio.Event] = None,
    ) -> Dict[str, Any]:
        content_parts: List[str] = []
        tool_calls_map: Dict[int, Dict[str, str]] = {}
        stream = await self._client.chat.completions.create(
            **request_kwargs, stream=True
        )
        async for chunk in stream:
            if signal is not None and signal.is_set():
                break
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta and delta.content:
                content_parts.append(delta.content)
                if on_stream is not None:
                    try:
                        await on_stream(delta.content)
                    except Exception:
                        pass
            if delta and delta.tool_calls:
                for tc in delta.tool_calls:
                    idx = tc.index if tc.index is not None else 0
                    if idx not in tool_calls_map:
                        tool_calls_map[idx] = {
                            "id": tc.id or "",
                            "name": "",
                            "arguments": "",
                        }
                    if tc.id:
                        tool_calls_map[idx]["id"] = tc.id
                    if tc.function and tc.function.name:
                        tool_calls_map[idx]["name"] += tc.function.name
                    if tc.function and tc.function.arguments:
                        tool_calls_map[idx]["arguments"] += tc.function.arguments
        tool_calls = list(tool_calls_map.values())
        return {"content": "".join(content_parts), "tool_calls": tool_calls}


# ── Main agent ────────────────────────────────────────────────────


class FinQuantAgent:
    """The in-platform financial agent.

    Owns the conversation history, the tool dispatcher, the introspector,
    the voice interface, and the LLM client. Provides ``chat`` (text)
    and ``voice_chat`` (full voice turn) plus lifecycle (``start`` /
    ``stop``) and introspection (``describe``).
    """

    def __init__(
        self,
        config: Optional[AgentConfig] = None,
        *,
        harness_registry: Any = None,
        actor_system: Any = None,
        cognitive_bus: Any = None,
        connector: Any = None,
        safety_policy: Any = None,
        species_library: Any = None,
        connector_registry: Any = None,
        llm_client: Optional[LLMClient] = None,
        voice_interface: Optional[VoiceInterface] = None,
        asr_callable: Optional[Any] = None,
    ) -> None:
        self.config = config or AgentConfig()

        # Introspector (live SDK state reader).
        self.introspector = PlatformIntrospector(
            harness_registry=harness_registry,
            actor_system=actor_system,
            connector=connector,
            safety_policy=safety_policy,
            species_library=species_library,
            cognitive_bus=cognitive_bus,
            connector_registry=connector_registry,
        )

        # Voice interface (TTS/ASR).
        self.voice = voice_interface or VoiceInterface(
            self.config.voice, asr_callable=asr_callable
        )

        # Tool dispatcher (wired to harness/actors/connector + voice).
        self.tools = ToolDispatcher(
            harness_registry=harness_registry,
            actor_system=actor_system,
            cognitive_bus=cognitive_bus,
            connector=connector,
            safety_policy=safety_policy,
            species_library=species_library,
            introspector=self.introspector,
            voice_interface=self.voice,
        )

        # LLM client.
        self.llm = llm_client or LLMClient(self.config.llm)

        # Conversation loop.
        self.loop = ConversationLoop(self.config, self.llm, self.tools)

        # Conversation history (persists across turns).
        self._messages: List[Dict[str, Any]] = []
        # Per-turn abort signal (set by interrupt()).
        self._current_signal: Optional[asyncio.Event] = None
        # Stats.
        self._stats: Dict[str, Any] = {
            "turns": 0,
            "tool_calls": 0,
            "voice_turns": 0,
            "started_at": None,
        }
        self._started = False

    # ── Lifecycle ─────────────────────────────────────────────────

    async def start(self) -> None:
        """Initialize the agent: voice engine + bus subscription."""
        if self._started:
            return
        self._started = True
        self._stats["started_at"] = time.time()
        try:
            await self.voice.start()
        except Exception as exc:
            logger.info("voice start failed (text-mode fallback): %s", exc)
        try:
            await self.introspector.attach_to_bus()
        except Exception as exc:
            logger.debug("bus attach failed: %s", exc)
        logger.info(
            "FinQuantAgent started (llm=%s, voice=%s)",
            self.config.llm.model,
            self.voice.status(),
        )

    async def stop(self) -> None:
        """Stop the agent, cancelling any in-flight turn."""
        await self.interrupt()
        try:
            await self.voice.stop_speaking()
        except Exception:
            pass
        self._started = False
        logger.info("FinQuantAgent stopped")

    # ── Text dialogue ─────────────────────────────────────────────

    async def chat(
        self,
        user_text: str,
        *,
        is_voice: bool = False,
        on_stream: Optional[Any] = None,
        on_tool_event: Optional[Any] = None,
    ) -> str:
        """Run one text turn. Returns the agent's final reply text.

        Args:
            user_text: The user's input.
            is_voice: If True, voice-mode prompt guidance applies and the
                final reply is spoken via TTS.
            on_stream: Async callback ``(chunk: str) -> None`` for
                streamed text (so the UI can render incrementally, and
                voice mode can fire TTS sentence-by-sentence).
            on_tool_event: Async callback ``(name, args, result)`` fired
                after each tool execution (for UI tool-call display).
        """
        await self._ensure_started()

        # Build a fresh system prompt with the live platform snapshot.
        system_prompt = await build_system_prompt_async(
            self.config,
            self.introspector,
            is_voice=is_voice,
            agent_stats=self._stats,
        )

        # Per-turn abort signal.
        signal = asyncio.Event()
        self._current_signal = signal

        # Wrap the user's stream callback so we can also feed TTS in voice mode.
        tts_buffer: List[str] = []

        async def _stream_handler(chunk: str) -> None:
            if on_stream is not None:
                try:
                    await on_stream(chunk)
                except Exception:
                    pass
            if is_voice and self.config.voice.auto_speak:
                tts_buffer.append(chunk)

        try:
            result: TurnResult = await self.loop.run_turn(
                messages=self._messages,
                system_prompt=system_prompt,
                user_text=user_text,
                is_voice=is_voice,
                signal=signal,
                on_stream=_stream_handler,
                on_tool_event=on_tool_event,
            )
        finally:
            self._current_signal = None

        # Update stats.
        self._stats["turns"] += 1
        self._stats["tool_calls"] += len(result.tool_calls)
        if is_voice:
            self._stats["voice_turns"] += 1

        # Record into agent memory (for the recall tool).
        self.tools.remember("user", user_text)
        if result.content:
            self.tools.remember("assistant", result.content)

        reply = result.content.strip()
        if not reply:
            reply = "（我没有生成回复。请重试或检查 LLM 配置。）"

        # Voice mode: speak the final reply (streamed chunks already
        # went to TTS via _stream_handler; here we only speak if nothing
        # was streamed, e.g. when stream=False or the model returned one
        # block). To avoid double-speak, we only TTS the remainder when
        # nothing was streamed.
        if is_voice and self.config.voice.auto_speak and not tts_buffer:
            try:
                await self.voice.speak(reply)
            except Exception as exc:
                logger.debug("final TTS failed: %s", exc)

        if self.config.verbose:
            logger.info(
                "turn done: rounds=%d tools=%d elapsed=%.0fms",
                result.rounds,
                len(result.tool_calls),
                result.elapsed_ms,
            )

        return reply

    # ── Voice dialogue ────────────────────────────────────────────

    async def voice_chat(
        self,
        *,
        on_stream: Optional[Any] = None,
        on_tool_event: Optional[Any] = None,
    ) -> str:
        """One full voice turn: ASR → chat (voice mode) → TTS.

        Returns the agent's final reply text (also spoken aloud). If
        ASR is not wired, falls back to an empty turn.
        """
        await self._ensure_started()
        # Stop any in-flight speech before listening.
        await self.voice.stop_speaking()
        user_text = await self.voice.listen()
        if not user_text:
            return ""
        return await self.chat(
            user_text, is_voice=True, on_stream=on_stream, on_tool_event=on_tool_event
        )

    # ── Control ───────────────────────────────────────────────────

    async def interrupt(self) -> None:
        """Interrupt the current turn (and stop speech)."""
        if self._current_signal is not None:
            self._current_signal.set()
        try:
            await self.voice.stop_speaking()
        except Exception:
            pass

    def reset_history(self) -> None:
        """Clear conversation history (keeps agent memory for recall tool)."""
        self._messages.clear()

    # ── Introspection ─────────────────────────────────────────────

    def describe(self) -> Dict[str, Any]:
        """Return a description of the agent's current configuration."""
        return {
            "agent_name": self.config.agent_name,
            "llm": {
                "provider": self.config.llm.provider,
                "model": self.config.llm.model,
                "configured": bool(self.config.llm.api_key),
            },
            "voice": self.voice.status(),
            "stats": self._stats,
            "history_length": len(self._messages),
            "introspector": {
                "has_harness": self.introspector.harness_registry is not None,
                "has_actor_system": self.introspector.actor_system is not None,
                "has_connector": self.introspector.connector is not None,
                "has_safety_policy": self.introspector.safety_policy is not None,
                "has_species_library": self.introspector.species_library is not None,
            },
        }

    async def platform_snapshot(self):
        """Convenience: get a live platform snapshot (for UI / debugging)."""
        portfolio, positions = await self.introspector.read_portfolio_async()
        snap = self.introspector.snapshot(agent_stats=self._stats)
        snap.portfolio = portfolio
        snap.positions = positions
        return snap

    # ── Internals ─────────────────────────────────────────────────

    async def _ensure_started(self) -> None:
        if not self._started:
            await self.start()


__all__ = ["FinQuantAgent", "LLMClient"]
