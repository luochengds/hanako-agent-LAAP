"""LAAP FinQuant Domain SDK — ReAct conversation loop.

The agentic loop that drives the financial agent. Mirrors BaiLongma's
``callLLM`` pattern: stream the LLM, execute tool calls as they arrive,
feed results back, repeat until the model produces a final reply with no
tool calls.

Key properties (hard-won lessons from BaiLongma, applied here):
- **Streaming** keeps voice latency low: first text chunk triggers TTS
  immediately, the user hears the start of the answer while the model
  is still generating the end.
- **Tool loop safety**: max rounds, max consecutive failures, same-call
  loop detection — never let the agent spin forever on a failing tool.
- **Final-reply detection**: a round with no tool calls = done. A nudge
  is injected if the model called tools but forgot to reply.
- **Abortable**: every round checks the abort signal so a new user
  message can interrupt a long-running turn (preemption).
- **No fake tool claims**: we only treat a tool as "called" when we
  actually executed it (BaiLongma deleted its keyword-scan fake-tool
  detector because it misfired; we sidestep by trusting the runtime log
  as the single source of truth).

The loop is transport-agnostic: it takes an ``LLMClient`` protocol
object (see :mod:`finquant_agent`) so any OpenAI-compatible backend
works.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional

from laap.domain_sdks.finquant.agent.config import AgentConfig
from laap.domain_sdks.finquant.agent.tool_schemas import get_schemas
from laap.domain_sdks.finquant.agent.tools import ToolDispatcher

logger = logging.getLogger("laap.domain_sdks.finquant.agent.conversation")

# Callback types
StreamCallback = Callable[[str], Awaitable[None]]
ToolEventCallback = Callable[[str, Dict[str, Any], str], Awaitable[None]]


@dataclass
class TurnResult:
    """Outcome of a single agent turn."""

    content: str = ""
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    rounds: int = 0
    aborted: bool = False
    elapsed_ms: float = 0.0
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error is None and not self.aborted


# ── Loop limits (tuned for financial analysis depth without runaway) ──
MAX_ROUNDS_DEFAULT = 12
MAX_CONSECUTIVE_FAILURES = 3
MAX_SAME_FINGERPRINT = 2
LOOP_WINDOW = 6
LOOP_UNIQUE_THRESHOLD = 2
UNCERTAINTY_CHECKPOINT = 10  # inject a "step back, re-plan" nudge past this


class ConversationLoop:
    """Runs the ReAct loop for a single user turn.

    Stateless across turns except for the conversation ``messages`` list
    which the owning :class:`FinQuantAgent` passes in (so history
    persists across turns).
    """

    def __init__(
        self,
        config: AgentConfig,
        llm_client: Any,
        tool_dispatcher: ToolDispatcher,
    ) -> None:
        self.config = config
        self.llm = llm_client
        self.tools = tool_dispatcher

    async def run_turn(
        self,
        messages: List[Dict[str, Any]],
        system_prompt: str,
        user_text: str,
        *,
        is_voice: bool = False,
        signal: Optional[asyncio.Event] = None,
        on_stream: Optional[StreamCallback] = None,
        on_tool_event: Optional[ToolEventCallback] = None,
    ) -> TurnResult:
        """Execute one full ReAct turn.

        Args:
            messages: Mutable conversation history (we append assistant
                + tool messages here). Caller owns persistence.
            system_prompt: The fully-built system prompt (with platform
                state already injected).
            user_text: The user's input for this turn.
            is_voice: Whether voice-mode guidance applies.
            signal: Optional abort event — set it to interrupt the turn.
            on_stream: Optional callback for streamed text chunks.
            on_tool_event: Optional callback ``(name, args, result)``
                fired after each tool execution.
        """
        start = time.time()
        result = TurnResult()
        max_rounds = self.config.max_tool_rounds or MAX_ROUNDS_DEFAULT
        tool_schemas = get_schemas(
            [
                "get_market_data", "get_quote",
                "compute_indicators", "detect_regime",
                "compute_var", "stress_test", "kelly_criterion",
                "compute_statistics",
                "run_backtest", "list_strategies",
                "get_portfolio", "place_order",
                "get_platform_state",
                "speak",
                "recall",
            ]
        )

        # Append the user message for this turn.
        messages.append({"role": "user", "content": user_text})

        consecutive_failures = 0
        recent_fingerprints: List[str] = []
        total_calls = 0
        uncertainty_nudge_used = False
        saw_tool_call = False
        final_nudge_used = False

        try:
            for round_idx in range(max_rounds):
                if signal is not None and signal.is_set():
                    result.aborted = True
                    return result
                result.rounds = round_idx + 1

                # Call the LLM (streaming).
                try:
                    llm_out = await self.llm.chat(
                        system_prompt=system_prompt,
                        messages=messages,
                        tools=tool_schemas,
                        temperature=self.config.llm.temperature,
                        max_tokens=self.config.llm.max_tokens,
                        stream=self.config.llm.stream,
                        on_stream=on_stream,
                        signal=signal,
                    )
                except asyncio.CancelledError:
                    result.aborted = True
                    return result
                except Exception as exc:
                    result.error = f"llm_error:{exc}"
                    return result

                content = llm_out.get("content", "") or ""
                tool_calls = llm_out.get("tool_calls", []) or []

                if content:
                    result.content += ("\n" if result.content else "") + content

                # No tool calls → turn is done (or needs a nudge).
                if not tool_calls:
                    if saw_tool_call and not content.strip() and not final_nudge_used:
                        # Model called tools but ended with empty reply — nudge once.
                        messages.append({"role": "assistant", "content": content or ""})
                        messages.append(
                            {
                                "role": "user",
                                "content": (
                                    "Tool results have returned. Based on them, give the user "
                                    "a final reply now. Do not end silently. "
                                    "(Internal runtime instruction — do not quote it.)"
                                ),
                            }
                        )
                        final_nudge_used = True
                        continue
                    break

                saw_tool_call = True
                # Append the assistant message with tool_calls.
                messages.append(
                    {
                        "role": "assistant",
                        "content": content,
                        "tool_calls": [
                            {
                                "id": tc.get("id", f"call_{total_calls}_{i}"),
                                "type": "function",
                                "function": {
                                    "name": tc["name"],
                                    "arguments": tc.get("arguments", "{}"),
                                },
                            }
                            for i, tc in enumerate(tool_calls)
                        ],
                    }
                )

                # Execute each tool call.
                for i, tc in enumerate(tool_calls):
                    if signal is not None and signal.is_set():
                        result.aborted = True
                        return result
                    name = tc["name"]
                    try:
                        args = json.loads(tc.get("arguments", "{}") or "{}")
                    except Exception:
                        args = {}
                    fingerprint = f"{name}:{json.dumps(args, sort_keys=True, default=str)}"

                    # Loop safety checks.
                    stop_reason = self._should_stop(
                        consecutive_failures, recent_fingerprints, fingerprint
                    )
                    if stop_reason:
                        tool_result_str = json.dumps(
                            {
                                "ok": False,
                                "error": "tool_loop_stopped",
                                "reason": stop_reason,
                                "hint": "Stop retrying. Choose a different approach or reply to the user.",
                            },
                            ensure_ascii=False,
                        )
                    else:
                        tool_result_str = await self.tools.dispatch(name, args)
                        total_calls += 1
                        recent_fingerprints.append(fingerprint)
                        if len(recent_fingerprints) > LOOP_WINDOW:
                            recent_fingerprints = recent_fingerprints[-LOOP_WINDOW:]
                        if self._is_failure(tool_result_str):
                            consecutive_failures += 1
                        else:
                            consecutive_failures = 0

                    # Record tool result in messages.
                    call_id = tc.get("id", f"call_{total_calls}_{i}")
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call_id,
                            "name": name,
                            "content": tool_result_str,
                        }
                    )
                    result.tool_calls.append(
                        {"name": name, "args": args, "result": tool_result_str}
                    )
                    if on_tool_event is not None:
                        try:
                            await on_tool_event(name, args, tool_result_str)
                        except Exception:
                            pass

                    if stop_reason:
                        # Inject a nudge and let the model react.
                        messages.append(
                            {
                                "role": "user",
                                "content": (
                                    f"Tool loop stopped: {stop_reason}. Stop retrying this action. "
                                    "Choose a different approach, or give the user a final reply "
                                    "explaining what you tried and what failed. Do not end silently."
                                ),
                            }
                        )
                        break

                # Uncertainty checkpoint: many calls, no reply yet.
                if (
                    total_calls >= UNCERTAINTY_CHECKPOINT
                    and not uncertainty_nudge_used
                ):
                    uncertainty_nudge_used = True
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                f"You have run {total_calls} tool calls this turn without a final reply. "
                                "Step back: is the plan converging? If not, re-plan or tell the user "
                                "what you have so far. Do not keep grinding silently. "
                                "(Internal runtime instruction — do not quote it.)"
                            ),
                        }
                    )

                # Continue the loop — the LLM will see the tool results.
            else:
                # Loop exhausted without break — force a wrap-up.
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "You have reached the maximum number of reasoning rounds. "
                            "Give the user a final reply now based on everything you have. "
                            "Do not call more tools."
                        ),
                    }
                )
                # One final LLM call with no tools to force a reply.
                try:
                    llm_out = await self.llm.chat(
                        system_prompt=system_prompt,
                        messages=messages,
                        tools=[],
                        temperature=self.config.llm.temperature,
                        max_tokens=self.config.llm.max_tokens,
                        stream=self.config.llm.stream,
                        on_stream=on_stream,
                        signal=signal,
                    )
                    final_content = (llm_out.get("content", "") or "").strip()
                    if final_content:
                        result.content += ("\n" if result.content else "") + final_content
                except Exception as exc:
                    logger.warning("final forced reply failed: %s", exc)

        finally:
            result.elapsed_ms = (time.time() - start) * 1000.0

        return result

    # ── Helpers ───────────────────────────────────────────────────

    @staticmethod
    def _is_failure(result_str: str) -> bool:
        try:
            d = json.loads(result_str)
            return d.get("ok") is False
        except Exception:
            return False

    @staticmethod
    def _should_stop(
        consecutive_failures: int,
        recent_fingerprints: List[str],
        fingerprint: str,
    ) -> Optional[str]:
        if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
            return f"too many consecutive failures ({MAX_CONSECUTIVE_FAILURES})"
        # Same exact failing call repeated.
        same_count = sum(1 for f in recent_fingerprints if f == fingerprint)
        if same_count >= MAX_SAME_FINGERPRINT:
            return f"same action repeated {same_count} times"
        # Stuck in a tight loop.
        window = recent_fingerprints[-LOOP_WINDOW:]
        if len(window) >= LOOP_WINDOW:
            unique = len(set(window))
            if unique <= LOOP_UNIQUE_THRESHOLD:
                return f"stuck in loop (only {unique} unique actions in last {LOOP_WINDOW})"
        return None


__all__ = ["ConversationLoop", "TurnResult"]
