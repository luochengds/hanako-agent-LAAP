"""ARIS cognitive bus for the LAAP Aether orchestration layer."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Awaitable, Callable, Dict, List, Optional

import inspect
from laap.orchestration.actor import ActorSystem, AgentCell, Capability
from laap.orchestration.dsl import act, compile_workflow, seq
from laap.orchestration.kernel import OrchestrationKernel
from laap.orchestration.petri import (
    ColoredToken,
    PetriNet,
    PetriPlace,
    PetriTransition,
    TokenColor,
)
from laap.orchestration.primitives import AetherAddress, AetherMessage, MessageType
from laap.orchestration.psi import PSIAgent
from laap.tools.base import ToolResult
from laap.tools.tool_registry import ToolRegistry, get_tool

logger = logging.getLogger("laap.orchestration.cognitive_bus")

HandlerWithActor = Callable[[AetherMessage, AgentCell], Awaitable[None]]


class ArisCognitiveBus:
    """Cognitive orchestration bus bridging actors, PSI state, and Petri nets."""

    def __init__(
        self,
        system_id: str = "aris-brain",
        tool_registry: Optional[Any] = None,
        llm_transport: Optional[Any] = None,
        session_manager: Optional[Any] = None,
        mcp_clients: Optional[List[Any]] = None,
    ) -> None:
        self.system = ActorSystem(system_id)
        self.psi = PSIAgent("psi_core")
        self.tool_results: Dict[str, Any] = {}
        self._tool_emit_listener: Optional[AgentCell] = None
        self._running = False
        self.tool_registry = tool_registry
        self.llm_transport = llm_transport
        self.session_manager = session_manager
        self.mcp_clients = mcp_clients or []
        self._tool_registry = tool_registry

    async def initialize(self) -> None:
        """Spawn the six cognitive actors and start the bus."""
        if self._tool_registry is not None:
            from laap.tools.actors import (
                register_mcp_tools_as_capabilities,
                register_tool_actors as _register_tool_actors_fn,
            )

            _register_tool_actors_fn(self.system, self._tool_registry)
            for client in self.mcp_clients:
                await register_mcp_tools_as_capabilities(self.system, client)

        await self._spawn_cognitive_actors()
        await self._spawn_tool_emit_listener()
        await self.register_tool_actors()
        self._running = True
        logger.info("ArisCognitiveBus initialized")

    async def _spawn_cognitive_actors(self) -> None:
        """Create actors, register capabilities, and bind INVOKE handlers."""
        psi_actor = self.system.spawn(
            "psi_core",
            capabilities=[
                Capability(
                    name="psi_processing",
                    confidence=0.95,
                    schema={"stimulus": "dict", "state": "PSIState"},
                    cost_estimate=0.001,
                    latency_estimate_ms=10,
                )
            ],
        )
        psi_actor.on(
            MessageType.INVOKE,
            self._wrap_handler(psi_actor, self._handle_psi_invoke),
        )

        rules_actor = self.system.spawn(
            "rules_engine",
            capabilities=[
                Capability(
                    name="rule_matching",
                    confidence=0.92,
                    schema={"query": "string", "context": "dict"},
                    cost_estimate=0.005,
                    latency_estimate_ms=50,
                )
            ],
        )
        rules_actor.on(
            MessageType.INVOKE,
            self._wrap_handler(rules_actor, self._handle_rules_invoke),
        )

        memory_actor = self.system.spawn(
            "episodic_memory",
            capabilities=[
                Capability(
                    name="memory_retrieval",
                    confidence=0.88,
                    schema={"query": "string", "emotional_tag": "string"},
                    cost_estimate=0.01,
                    latency_estimate_ms=100,
                )
            ],
        )
        memory_actor.on(
            MessageType.INVOKE,
            self._wrap_handler(memory_actor, self._handle_memory_invoke),
        )

        qre_actor = self.system.spawn(
            "qre",
            capabilities=[
                Capability(
                    name="query_resolution",
                    confidence=0.90,
                    schema={"query": "string", "context": "dict"},
                    cost_estimate=0.02,
                    latency_estimate_ms=200,
                )
            ],
        )
        qre_actor.on(
            MessageType.INVOKE,
            self._wrap_handler(qre_actor, self._handle_qre_invoke),
        )

        longform_actor = self.system.spawn(
            "longform",
            capabilities=[
                Capability(
                    name="deep_generation",
                    confidence=0.85,
                    schema={"prompt": "string", "depth": "int"},
                    cost_estimate=0.05,
                    latency_estimate_ms=500,
                )
            ],
        )
        longform_actor.on(
            MessageType.INVOKE,
            self._wrap_handler(longform_actor, self._handle_longform_invoke),
        )

        fusion_actor = self.system.spawn(
            "fusion_engine",
            capabilities=[
                Capability(
                    name="response_fusion",
                    confidence=0.93,
                    schema={"inputs": "list", "psi_state": "dict"},
                    cost_estimate=0.01,
                    latency_estimate_ms=100,
                )
            ],
        )
        fusion_actor.on(
            MessageType.INVOKE,
            self._wrap_handler(fusion_actor, self._handle_fusion_invoke),
        )

        logger.info("All cognitive actors spawned")

    async def _spawn_tool_emit_listener(self) -> None:
        """Spawn a dedicated actor that receives EMIT messages from tool actors."""
        listener = self.system.spawn(
            "tool_emit_listener",
            capabilities=[
                Capability(
                    name="emit_listener",
                    confidence=1.0,
                    schema={"event": "dict"},
                    cost_estimate=0.0,
                    latency_estimate_ms=1,
                )
            ],
        )
        listener.on(
            MessageType.EMIT,
            self._wrap_handler(listener, self._handle_tool_emit),
        )
        self._tool_emit_listener = listener
        logger.info("Tool EMIT listener spawned")

    async def register_tool_actors(self) -> None:
        """Register all native tool actors in the actor system."""
        # Lazy import to avoid a circular import when laap.tools is loaded
        # before laap.orchestration.cognitive_bus.
        from laap.tools.actors import register_tool_actors as _register_tool_actors

        _register_tool_actors(self.system)
        logger.info("Tool actors registered")

    def _wrap_handler(
        self,
        actor: AgentCell,
        handler: HandlerWithActor,
    ) -> Callable[[AetherMessage], Awaitable[None]]:
        """Adapt a (msg, actor) handler to the AgentCell (msg) API."""

        async def _wrapped(msg: AetherMessage) -> None:
            await handler(msg, actor)

        return _wrapped

    async def _handle_psi_invoke(self, msg: AetherMessage, actor: AgentCell) -> None:
        stimulus = msg.payload.get("stimulus", {})
        new_state = await self.psi.process_perception(stimulus)
        state_msg = AetherMessage(
            msg_type=MessageType.STATE_DELTA,
            sender=actor.address,
            payload={"psi_state": new_state.to_dict(), "stimulus": stimulus},
        )
        await self.system.broadcast(state_msg)
        actor.working_memory["last_psi_state"] = new_state.to_dict()

    async def _handle_rules_invoke(self, msg: AetherMessage, actor: AgentCell) -> None:
        query = msg.payload.get("query", "")
        matched_rules: List[Dict[str, Any]] = []
        if "greeting" in query.lower():
            matched_rules.append(
                {"rule": "greeting", "action": "respond_warmly", "priority": 0.9}
            )
        if "code" in query.lower() or "file" in query.lower():
            matched_rules.append(
                {"rule": "technical", "action": "invoke_tools", "priority": 0.95}
            )
        if "?" in query:
            matched_rules.append(
                {"rule": "question", "action": "deep_search", "priority": 0.8}
            )
        actor.working_memory["matched_rules"] = matched_rules
        logger.info("RulesEngine matched %d rules", len(matched_rules))

    async def _handle_memory_invoke(self, msg: AetherMessage, actor: AgentCell) -> None:
        query = msg.payload.get("query", "")
        emotional_tag = msg.payload.get("emotional_tag", "neutral")
        memories: List[Dict[str, Any]] = []
        if "project" in query.lower():
            memories.append(
                {
                    "type": "episodic",
                    "content": "Previous project: LAAP architecture",
                    "relevance": 0.9,
                }
            )
        if emotional_tag == "distressed":
            memories.append(
                {
                    "type": "emotional",
                    "content": "User was stressed about deadlines",
                    "relevance": 0.8,
                }
            )
        actor.working_memory["retrieved_memories"] = memories
        logger.info("Memory retrieved %d items", len(memories))

    async def _handle_qre_invoke(self, msg: AetherMessage, actor: AgentCell) -> None:
        explicit_actions: List[Dict[str, Any]] = msg.payload.get("actions", [])
        if explicit_actions:
            results: List[Dict[str, Any]] = []
            for action in explicit_actions:
                tool_name = action.get("tool")
                params = action.get("params", {})
                if not tool_name:
                    continue
                tool_result = await self._handle_tool_invoke(tool_name, params)
                results.append(
                    {
                        "tool": tool_name,
                        "params": params,
                        "result": tool_result.to_dict(),
                    }
                )
            actor.working_memory["resolved_actions"] = explicit_actions
            actor.working_memory["resolved_action_results"] = results
            logger.info("QRE dispatched %d explicit tool actions", len(explicit_actions))
            return

        query = msg.payload.get("query", "")
        actions: List[Dict[str, Any]] = []
        if "search" in query.lower() or "find" in query.lower():
            actions.append({"tool": "search_files", "params": {"pattern": "*.py"}})
        if "read" in query.lower() or "show" in query.lower():
            actions.append({"tool": "read_file", "params": {"path": "default.py"}})
        if "write" in query.lower() or "create" in query.lower():
            actions.append(
                {
                    "tool": "write_file",
                    "params": {"path": "output.py", "content": "# generated"},
                }
            )
        actor.working_memory["resolved_actions"] = actions
        logger.info("QRE resolved %d actions", len(actions))

    async def _handle_longform_invoke(self, msg: AetherMessage, actor: AgentCell) -> None:
        prompt = msg.payload.get("prompt", "")
        depth = msg.payload.get("depth", 1)
        await asyncio.sleep(0.01 * depth)
        result = f"[Generated: {prompt[:50]}... (depth={depth})]"
        actor.working_memory["generation_result"] = result
        logger.info("LongForm generated %d chars", len(result))

    async def _handle_fusion_invoke(self, msg: AetherMessage, actor: AgentCell) -> None:
        inputs = msg.payload.get("inputs", [])
        psi_state = msg.payload.get("psi_state", {})
        dominant_feeling = psi_state.get("dominant_feeling", "neutral")
        tone = {
            "excited": "enthusiastic",
            "distressed": "supportive",
            "content": "warm",
        }.get(dominant_feeling, "neutral")
        parts = [inp.get("content", str(inp)) for inp in inputs if isinstance(inp, dict)]
        if not parts:
            parts = ["I understand. Let me help you with that."]
        response = f"[{tone.upper()}] " + " ".join(parts)
        actor.working_memory["fused_response"] = response
        logger.info("FusionEngine produced response (%d chars)", len(response))

    async def process_tool_action(
        self, tool_name: str, params: Dict[str, Any]
    ) -> ToolResult:
        """Dispatch a tool action to a capable actor and return its result."""
        matches = self.system.find_capable_agents(tool_name)
        if not matches:
            return ToolResult(
                success=False,
                output="",
                error=f"No actor found capable of '{tool_name}'",
            )

        actor, _confidence = matches[0]
        sender = (
            self._tool_emit_listener.address
            if self._tool_emit_listener is not None
            else None
        )
        invoke_msg = AetherMessage(
            msg_type=MessageType.INVOKE,
            sender=sender,
            recipient=AetherAddress(
                host=actor.address.host,
                actor_id=actor.actor_id,
                capability=tool_name,
            ),
            payload=params,
        )
        await self.system.send(invoke_msg)

        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            last_result = actor.working_memory.get("last_result")
            if last_result is not None:
                if isinstance(last_result, ToolResult):
                    return last_result
                return ToolResult(success=True, output=str(last_result))
            await asyncio.sleep(0.05)

        return ToolResult(
            success=False,
            output="",
            error=f"Timeout waiting for tool '{tool_name}'",
        )

    def _resolve_tool_handler(self, tool_name: str) -> Optional[Callable]:
        """Resolve a tool name to a callable using the configured registry."""
        registry = self.tool_registry
        if registry is not None:
            if hasattr(registry, "get_tool"):
                fn = registry.get_tool(tool_name)
                if fn is not None:
                    return fn
            if hasattr(registry, "get"):
                entry = registry.get(tool_name)
                if entry is not None:
                    if callable(entry):
                        return entry
                    if hasattr(entry, "handler"):
                        return entry.handler
                    if isinstance(entry, dict):
                        return entry.get("fn")
            if isinstance(registry, dict):
                entry = registry.get(tool_name)
                if callable(entry):
                    return entry
                if isinstance(entry, dict):
                    return entry.get("fn")
            return None
        return get_tool(tool_name)

    async def _handle_tool_invoke(
        self, tool_name: str, params: Dict[str, Any]
    ) -> ToolResult:
        """Execute a tool directly via the registry or fall back to an actor."""
        fn = self._resolve_tool_handler(tool_name)
        if fn is not None:
            try:
                if inspect.iscoroutinefunction(fn):
                    raw = await fn(**params)
                else:
                    raw = fn(**params)
                if isinstance(raw, ToolResult):
                    return raw
                return ToolResult(success=True, output=str(raw))
            except Exception as exc:
                return ToolResult(
                    success=False,
                    output="",
                    error=f"{type(exc).__name__}: {exc}",
                )
        return await self.process_tool_action(tool_name, params)

    async def _handle_infer(self, intent: Dict[str, Any]) -> Any:
        """Route an ambiguous intent to the configured LLM transport."""
        if self.llm_transport is None:
            raise RuntimeError("No LLM transport configured for inference")
        messages = intent.get("messages")
        if messages is None:
            text = intent.get("text", "")
            messages = [{"role": "user", "content": text}]
        return await self.llm_transport.generate(
            messages, **intent.get("kwargs", {})
        )

    def _match_deterministic_intent(
        self, text: str
    ) -> Optional[tuple[str, Dict[str, Any]]]:
        """Map simple user intents directly to tool names and parameters."""
        lowered = text.strip().lower()

        if lowered.startswith("read ") or lowered.startswith("show "):
            path = text.strip().split(None, 1)[1].strip().strip("\"'")
            return "read_file", {"path": path}

        if lowered.startswith("write ") or lowered.startswith("create "):
            rest = text.strip().split(None, 1)[1].strip().strip("\"'")
            parts = rest.split(" ", 1)
            path = parts[0]
            content = parts[1] if len(parts) > 1 else ""
            return "write_file", {"path": path, "content": content}

        if lowered.startswith("search ") or lowered.startswith("find "):
            pattern = text.strip().split(None, 1)[1].strip().strip("\"'")
            return "search_files", {"pattern": pattern}

        if lowered.startswith("navigate ") or lowered.startswith("open "):
            url = text.strip().split(None, 1)[1].strip().strip("\"'")
            return "browser_navigate", {"url": url}

        if lowered.startswith("run ") or lowered.startswith("execute "):
            cmd = text.strip().split(None, 1)[1].strip()
            return "run_command", {"cmd": cmd}

        return None

    async def process_user_intent(self, text: str) -> Dict[str, Any]:
        """Route a user intent through a Petri-net tool workflow or the LLM."""
        deterministic = self._match_deterministic_intent(text)
        if deterministic is not None:
            tool_name, params = deterministic
            workflow = seq(act(tool_name, params, output_key="result"))
            net, actor_bindings, output_places = compile_workflow(
                workflow,
                net_id=f"{self.system.system_id}_intent",
                actor_system=self.system,
                tool_registry=self.tool_registry,
            )
            kernel = OrchestrationKernel(
                self.system, net, kernel_id=f"{self.system.system_id}_kernel"
            )
            for transition_id, actor_ids in actor_bindings.items():
                for actor_id in actor_ids:
                    kernel.bind_transition(transition_id, actor_id)
            await kernel.run()

            result: Any = None
            out_place_id = output_places.get("result")
            if out_place_id is not None:
                tokens = list(net.places[out_place_id].tokens)
                if tokens:
                    value = tokens[-1].value
                    if isinstance(value, dict):
                        result = value.get("result", value)
                    else:
                        result = value
            return {
                "intent": text,
                "source": "petri_net",
                "tool": tool_name,
                "params": params,
                "result": result,
            }

        response = await self._handle_infer({"text": text})
        return {
            "intent": text,
            "source": "llm",
            "response": getattr(response, "content", str(response)),
        }

    async def _handle_tool_emit(
        self, msg: AetherMessage, actor: AgentCell
    ) -> None:
        """Store emitted tool results keyed by the EMIT message id."""
        self.tool_results[msg.msg_id] = msg.payload
        logger.debug("Stored tool EMIT result for msg_id=%s", msg.msg_id)

    def _build_cognitive_loop(self, stimulus: Dict[str, Any]) -> PetriNet:
        """Construct a colored Petri net that models the ARIS cognitive loop."""
        net = PetriNet("cognitive_loop")

        net.add_place(PetriPlace("perception", token_types={TokenColor.DATA}))
        net.add_place(PetriPlace("psi_state", token_types={TokenColor.PSI_STATE}))
        net.add_place(PetriPlace("memory_context", token_types={TokenColor.MEMORY}))
        net.add_place(PetriPlace("rule_matches", token_types={TokenColor.RULE_MATCH}))
        net.add_place(PetriPlace("resolution_ready", token_types={TokenColor.CONTROL}))
        net.add_place(PetriPlace("generation_ready", token_types={TokenColor.CONTROL}))
        net.add_place(PetriPlace("response", token_types={TokenColor.RESPONSE}))

        async def psi_action(consumed: Dict[str, Any]) -> List[ColoredToken]:
            perception_tokens = consumed.get("perception", [])
            data = perception_tokens[0].value if perception_tokens else {}
            new_state = await self.psi.process_perception(data)
            state_token = ColoredToken(TokenColor.PSI_STATE, new_state.to_dict())
            # Two copies so that both memory retrieval and rule matching can fire.
            return [state_token, state_token]

        net.add_transition(
            PetriTransition(
                transition_id="update_psi",
                input_places={"perception": 1},
                output_places={"psi_state": lambda tokens: tokens},
                action=psi_action,
            )
        )

        async def memory_action(consumed: Dict[str, Any]) -> List[ColoredToken]:
            psi_tokens = consumed.get("psi_state", [])
            psi_data = psi_tokens[0].value if psi_tokens else {}
            return [
                ColoredToken(
                    TokenColor.MEMORY,
                    {
                        "emotional_tag": psi_data.get("dominant_feeling", "neutral"),
                        "query": "user_context",
                    },
                )
            ]

        net.add_transition(
            PetriTransition(
                transition_id="retrieve_memory",
                input_places={"psi_state": 1},
                output_places={"memory_context": lambda tokens: tokens},
                action=memory_action,
            )
        )

        async def rules_action(consumed: Dict[str, Any]) -> List[ColoredToken]:
            psi_tokens = consumed.get("psi_state", [])
            psi_data = psi_tokens[0].value if psi_tokens else {}
            return [
                ColoredToken(
                    TokenColor.RULE_MATCH,
                    {"psi_state": psi_data, "matched": True},
                )
            ]

        net.add_transition(
            PetriTransition(
                transition_id="match_rules",
                input_places={"psi_state": 1},
                output_places={"rule_matches": lambda tokens: tokens},
                action=rules_action,
            )
        )

        net.add_transition(
            PetriTransition(
                transition_id="resolve_query",
                input_places={"memory_context": 1, "rule_matches": 1},
                output_places={
                    "resolution_ready": lambda _: [
                        ColoredToken(TokenColor.CONTROL, "ready")
                    ]
                },
            )
        )

        async def gen_action(_consumed: Dict[str, Any]) -> List[ColoredToken]:
            return [ColoredToken(TokenColor.CONTROL, "generate")]

        net.add_transition(
            PetriTransition(
                transition_id="trigger_generation",
                input_places={"resolution_ready": 1},
                output_places={"generation_ready": lambda tokens: tokens},
                action=gen_action,
            )
        )

        async def fusion_action(_consumed: Dict[str, Any]) -> List[ColoredToken]:
            response = f"[PSI:{self.psi.state.dominant_feeling}] Processing complete."
            return [ColoredToken(TokenColor.RESPONSE, response)]

        net.add_transition(
            PetriTransition(
                transition_id="fuse_response",
                input_places={"generation_ready": 1},
                output_places={"response": lambda tokens: tokens},
                action=fusion_action,
            )
        )

        return net

    async def process(
        self, user_input: str, context: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """Run the cognitive loop and return a fused response."""
        if not self._running:
            await self.initialize()

        logger.info("ArisCognitiveBus processing: %s", user_input[:100])

        stimulus: Dict[str, Any] = {
            "text": user_input,
            "type": "user_message",
            "certainty": 0.8,
            "context": context or {},
        }
        net = self._build_cognitive_loop(stimulus)
        net.places["perception"].deposit(ColoredToken(TokenColor.DATA, stimulus))

        cognitive_trace: List[Dict[str, Any]] = []
        max_steps = 20
        for step in range(max_steps):
            enabled = await net.get_enabled_transitions()
            if not enabled:
                break
            for transition in enabled:
                success = await net.fire_transition(transition.transition_id)
                if success:
                    cognitive_trace.append(
                        {
                            "step": step,
                            "transition": transition.transition_id,
                            "timestamp": time.time(),
                        }
                    )
            await asyncio.sleep(0)

        response_tokens = list(net.places["response"].tokens)
        if response_tokens:
            final_response = response_tokens[0].value
        else:
            final_response = "[Aris] I processed your input but need more context."

        return {
            "response": final_response,
            "psi_state": self.psi.state.to_dict(),
            "cognitive_trace": cognitive_trace,
            "steps_executed": len(cognitive_trace),
        }

    async def shutdown(self) -> None:
        """Stop the bus and all spawned actors."""
        self._running = False
        await self.system.shutdown()
