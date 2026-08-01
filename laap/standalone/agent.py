"""LAAP standalone agent — lightweight CLI/session wrapper around ARIS."""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Dict, List, Optional

from laap.llm.engine import LLMEngine, MockLLMEngine, TokenUsage
from laap.orchestration.cognitive_bus import ArisCognitiveBus
from laap.orchestration.dsl import LAAPExpr, act, compile_workflow, infer, seq
from laap.orchestration.petri import ColoredToken, TokenColor
from laap.tools.base import ToolResult
import laap.tools

logger = logging.getLogger("laap.standalone.agent")


class StandaloneAgent:
    """A self-contained LAAP agent that routes simple intents to DSL workflows."""

    def __init__(
        self,
        cognitive_bus: Optional[ArisCognitiveBus] = None,
        llm_engine: Optional[LLMEngine] = None,
    ) -> None:
        self.cognitive_bus = cognitive_bus or ArisCognitiveBus()
        self.llm_engine = llm_engine or MockLLMEngine()
        self.token_usage: List[TokenUsage] = []
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize the cognitive bus and tool actors if needed."""
        if self._initialized:
            return
        if not self.cognitive_bus._running:
            await self.cognitive_bus.initialize()
        self._initialized = True
        logger.info("StandaloneAgent initialized")

    async def shutdown(self) -> None:
        """Stop the cognitive bus."""
        await self.cognitive_bus.shutdown()
        self._initialized = False

    async def process(
        self,
        user_input: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Process a user input, using intent routing when possible."""
        await self.initialize()

        routed = self.route_intent(user_input)
        if routed is None:
            return await self.cognitive_bus.process(user_input, context=context)

        return await self._execute_workflow(routed, user_input, context=context)

    @staticmethod
    def route_intent(user_input: str) -> Optional[LAAPExpr]:
        """Map a simple natural-language intent to a LAAP-DSL expression."""
        text = user_input.strip()
        lower = text.lower()

        # Read a file and summarize it.
        if "read" in lower:
            match = re.search(r"\b(\S+\.\w+)\b", text)
            if match:
                path = match.group(1)
                return seq(
                    act("read_file", {"path": path}, output_key="file_contents"),
                    infer(
                        "summarize",
                        "Summarize the following file:\n{file_contents}",
                        output_key="summary",
                    ),
                )

        # Search for a pattern in the codebase.
        if "search" in lower:
            match = re.search(r"search\s+['\"]?([^'\"\s]+)['\"]?", text, re.IGNORECASE)
            if match:
                pattern = match.group(1)
                return act(
                    "search_files",
                    {"pattern": pattern, "glob": "*.py", "max_results": 20},
                    output_key="search_results",
                )

        # Run the test suite.
        if re.search(r"\brun tests?\b|\btest\b", text, re.IGNORECASE):
            return act("run_tests", {"target": "."}, output_key="test_results")

        # Execute a shell command.
        match = re.search(r"(?:execute|run)\s+(.+)", text, re.IGNORECASE)
        if match:
            cmd = match.group(1).strip()
            return act(
                "run_command",
                {"cmd": cmd, "sandbox": True},
                output_key="command_output",
            )

        return None

    async def _execute_workflow(
        self,
        expr: LAAPExpr,
        user_input: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Compile and run a routed DSL workflow."""
        net, _actor_bindings, output_places = compile_workflow(
            expr,
            net_id="standalone_intent",
            actor_system=self.cognitive_bus.system,
            tool_registry=self.cognitive_bus.tool_registry or laap.tools,
        )

        workspace: Dict[str, Any] = {
            "user_input": user_input,
            "context": context or {},
        }

        max_steps = 100
        for _ in range(max_steps):
            enabled = await net.get_enabled_transitions()
            if not enabled:
                break
            for transition in enabled:
                success = await net.fire_transition(transition.transition_id)
                if not success:
                    continue
                if net.execution_log:
                    entry = net.execution_log[-1]
                    produced = entry.get("produced", {})
                    await self._route_produced_tokens(produced, workspace)
                await asyncio.sleep(0)

        outputs: Dict[str, List[Any]] = {
            key: [t.value for t in net.places[place_id].tokens]
            for key, place_id in output_places.items()
        }
        response = self._format_response(outputs, workspace)

        return {
            "response": response,
            "outputs": outputs,
            "workspace": workspace,
            "token_usage": self.session_summary(),
        }

    async def _route_produced_tokens(
        self,
        produced: Dict[str, List[ColoredToken]],
        workspace: Dict[str, Any],
    ) -> None:
        """Dispatch DATA tokens to tools or the LLM engine."""
        for _place_id, tokens in produced.items():
            for token in tokens:
                if token.color != TokenColor.DATA:
                    continue
                value = token.value
                if not isinstance(value, dict):
                    continue

                output_key = value.get("output_key")
                if "tool" in value:
                    if "result" in value:
                        # Direct tool execution via the DSL registry.
                        result = value["result"]
                        workspace[output_key] = result
                        logger.info(
                            "Tool '%s' completed via registry: success=%s",
                            value["tool"],
                            getattr(result, "success", True),
                        )
                    else:
                        # Actor-based execution path: reconstruct params and dispatch.
                        tool_name = value["tool"]
                        params = {
                            k: v for k, v in value.items() if k not in ("tool", "output_key")
                        }
                        result = await self.cognitive_bus.process_tool_action(tool_name, params)
                        workspace[output_key] = result
                        logger.info("Tool '%s' completed: success=%s", tool_name, result.success)
                elif "skill" in value:
                    skill_name = value["skill"]
                    params = {
                        k: v for k, v in value.items() if k not in ("skill", "output_key")
                    }
                    result = await self.cognitive_bus.process_tool_action(skill_name, params)
                    workspace[output_key] = result
                elif "model" in value and "prompt" in value:
                    prompt = value["prompt"]
                    try:
                        formatted_prompt = prompt.format(**workspace)
                    except (KeyError, ValueError):
                        formatted_prompt = prompt
                    text, usage = await self.llm_engine.generate(formatted_prompt)
                    self.token_usage.append(usage)
                    workspace[output_key] = text
                    logger.info("Inference '%s' completed (%d tokens)", value.get("model"), usage.total_tokens)

    def _format_response(
        self,
        outputs: Dict[str, List[Any]],
        workspace: Dict[str, Any],
    ) -> str:
        """Build a human-readable response from the workflow workspace."""
        # Prefer the last output key produced by the workflow.
        last_key: Optional[str] = None
        for key in outputs:
            last_key = key

        if last_key is not None and last_key in workspace:
            value = workspace[last_key]
            if isinstance(value, ToolResult):
                return value.output or value.error or "Done."
            return str(value)

        return "Done."

    def session_summary(self) -> Dict[str, Any]:
        """Return aggregated token usage and cost for the session."""
        total_tokens = sum(u.total_tokens for u in self.token_usage)
        local_tokens = sum(
            u.total_tokens for u in self.token_usage if u.source == "local"
        )
        remote_tokens = sum(
            u.total_tokens for u in self.token_usage if u.source == "remote"
        )
        estimated_cost = sum(u.estimated_cost_usd for u in self.token_usage)

        return {
            "total_tokens": total_tokens,
            "local_tokens": local_tokens,
            "remote_tokens": remote_tokens,
            "estimated_cost_usd": estimated_cost,
        }
