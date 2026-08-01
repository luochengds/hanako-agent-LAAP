"""LAAP — Tool actors that expose native tools as Aether capabilities."""

from __future__ import annotations

from typing import Any, ClassVar, Dict, List, Optional

from laap.orchestration.actor import AgentCell, ActorSystem, Capability
from laap.orchestration.primitives import AetherAddress, AetherMessage, MessageType
from laap.tools.base import ToolResult
from laap.tools.bci_adapter import BCIAdapterTool
from laap.tools.code_runner import CodeRunnerTool
from laap.tools.filesystem import FileSystemTool
from laap.tools.search import SearchTool
from laap.tools.terminal import TerminalTool

import laap.tools.browser_auto as _browser_auto

from laap.mcp.client import MCPClient


def _normalize_result(result: Any) -> Dict[str, Any]:
    """Convert a native tool result into a plain dict payload."""
    if isinstance(result, ToolResult):
        return result.to_dict()
    if isinstance(result, dict):
        return dict(result)
    if isinstance(result, list):
        return {"results": list(result)}
    return {"result": result}


async def _store_and_emit(actor: AgentCell, message: AetherMessage, result: Any) -> None:
    """Store *result* in working memory and emit it back to the sender."""
    actor.working_memory["last_result"] = result
    if actor._system is None or message.sender is None:
        return

    payload = _normalize_result(result)
    payload["capability"] = message.recipient.capability if message.recipient else None

    await actor._system.send(
        AetherMessage(
            msg_type=MessageType.EMIT,
            sender=actor.address,
            recipient=message.sender,
            payload=payload,
        )
    )


class FileSystemActor(AgentCell):
    """Actor exposing filesystem capabilities."""

    CAPABILITIES: ClassVar[List[str]] = ["read_file", "write_file", "list_dir"]

    def __init__(
        self,
        actor_id: str,
        host: str = "local",
        supervisor: Optional[AetherAddress] = None,
        max_retries: int = 3,
    ) -> None:
        super().__init__(actor_id, host, supervisor, max_retries)
        self.on(MessageType.INVOKE, self._handle_invoke)

    async def _handle_invoke(self, message: AetherMessage) -> None:
        cap = (message.recipient.capability if message.recipient else "*").lower()
        payload = message.payload
        result: Any

        if cap == "read_file":
            result = FileSystemTool.read_file(payload.get("path", ""))
        elif cap == "write_file":
            result = FileSystemTool.write_file(
                payload.get("path", ""), payload.get("content", "")
            )
        elif cap == "list_dir":
            result = FileSystemTool.list_dir(payload.get("path", "."))
        else:
            result = ToolResult(
                success=False,
                output="",
                error=f"Capability '{cap}' not supported by {self.actor_id}",
            )

        await _store_and_emit(self, message, result)


class TerminalActor(AgentCell):
    """Actor exposing terminal/shell capabilities."""

    CAPABILITIES: ClassVar[List[str]] = ["run_command"]

    def __init__(
        self,
        actor_id: str,
        host: str = "local",
        supervisor: Optional[AetherAddress] = None,
        max_retries: int = 3,
    ) -> None:
        super().__init__(actor_id, host, supervisor, max_retries)
        self.on(MessageType.INVOKE, self._handle_invoke)

    async def _handle_invoke(self, message: AetherMessage) -> None:
        payload = message.payload
        result = TerminalTool.run_command(
            cmd=payload.get("cmd", ""),
            timeout=payload.get("timeout", 30),
            cwd=payload.get("cwd"),
            sandbox=payload.get("sandbox", True),
        )
        await _store_and_emit(self, message, result)


class SearchActor(AgentCell):
    """Actor exposing file-search capabilities."""

    CAPABILITIES: ClassVar[List[str]] = ["search_files"]

    def __init__(
        self,
        actor_id: str,
        host: str = "local",
        supervisor: Optional[AetherAddress] = None,
        max_retries: int = 3,
    ) -> None:
        super().__init__(actor_id, host, supervisor, max_retries)
        self.on(MessageType.INVOKE, self._handle_invoke)

    async def _handle_invoke(self, message: AetherMessage) -> None:
        payload = message.payload
        result = SearchTool.search_files(
            pattern=payload.get("pattern", ""),
            root=payload.get("root", "."),
            glob=payload.get("glob", "*.py"),
            max_results=payload.get("max_results", 20),
        )
        await _store_and_emit(self, message, result)


class CodeRunnerActor(AgentCell):
    """Actor exposing code execution capabilities."""

    CAPABILITIES: ClassVar[List[str]] = ["run_tests", "run_python"]

    def __init__(
        self,
        actor_id: str,
        host: str = "local",
        supervisor: Optional[AetherAddress] = None,
        max_retries: int = 3,
    ) -> None:
        super().__init__(actor_id, host, supervisor, max_retries)
        self.on(MessageType.INVOKE, self._handle_invoke)

    async def _handle_invoke(self, message: AetherMessage) -> None:
        cap = (message.recipient.capability if message.recipient else "*").lower()
        payload = message.payload
        result: Any

        if cap == "run_tests":
            result = CodeRunnerTool.run_tests(
                target=payload.get("target", "."),
                timeout=payload.get("timeout", 120),
            )
        elif cap == "run_python":
            result = CodeRunnerTool.run_python(
                code=payload.get("code", ""),
                timeout=payload.get("timeout", 10),
            )
        else:
            result = ToolResult(
                success=False,
                output="",
                error=f"Capability '{cap}' not supported by {self.actor_id}",
            )

        await _store_and_emit(self, message, result)


class BCIAdapterActor(AgentCell):
    """Actor exposing mock BCI input as orchestration messages."""

    CAPABILITIES: ClassVar[List[str]] = ["bci_input"]

    def __init__(
        self,
        actor_id: str,
        host: str = "local",
        supervisor: Optional[AetherAddress] = None,
        max_retries: int = 3,
    ) -> None:
        super().__init__(actor_id, host, supervisor, max_retries)
        self._tool = BCIAdapterTool()
        self.on(MessageType.INVOKE, self._handle_invoke)

    async def _handle_invoke(self, message: AetherMessage) -> None:
        frame = self._tool.next_frame()
        await _store_and_emit(self, message, frame)


class BrowserActor(AgentCell):
    """Actor exposing browser automation capabilities."""

    CAPABILITIES: ClassVar[List[str]] = [
        "browser_navigate",
        "browser_click",
        "browser_type",
        "browser_get_text",
        "browser_get_html",
        "browser_title",
        "browser_screenshot",
        "browser_evaluate",
        "browser_scroll",
        "browser_get_links",
        "browser_get_visible_text",
        "browser_list_tabs",
        "browser_new_tab",
        "browser_switch_tab",
        "browser_close",
        "browser_snapshot",
        "browser_vision",
        "browser_wait_for_selector",
        "set_browser_stealth",
    ]

    def __init__(
        self,
        actor_id: str,
        host: str = "local",
        supervisor: Optional[AetherAddress] = None,
        max_retries: int = 3,
    ) -> None:
        super().__init__(actor_id, host, supervisor, max_retries)
        self.on(MessageType.INVOKE, self._handle_invoke)

    async def _handle_invoke(self, message: AetherMessage) -> None:
        cap = (message.recipient.capability if message.recipient else None) or message.payload.get("capability", "*")
        cap = cap.lower()
        payload = dict(message.payload)
        payload.pop("capability", None)
        result: Any

        if cap in self.CAPABILITIES and hasattr(_browser_auto, cap):
            try:
                result = getattr(_browser_auto, cap)(**payload)
            except Exception as exc:
                result = ToolResult(success=False, output="", error=str(exc))
        else:
            result = ToolResult(
                success=False,
                output="",
                error=f"Capability '{cap}' not supported by {self.actor_id}",
            )

        await _store_and_emit(self, message, result)


class MCPActor(AgentCell):
    """Actor that proxies INVOKE messages to an MCP server tool."""

    CAPABILITIES: ClassVar[List[str]] = []

    def __init__(
        self,
        actor_id: str,
        client: MCPClient,
        tool_name: str,
        host: str = "local",
        supervisor: Optional[AetherAddress] = None,
        max_retries: int = 3,
    ) -> None:
        super().__init__(actor_id, host, supervisor, max_retries)
        self._client = client
        self._tool_name = tool_name
        self.on(MessageType.INVOKE, self._handle_invoke)

    async def _handle_invoke(self, message: AetherMessage) -> None:
        payload = dict(message.payload)
        # Dispatch by recipient capability; fall back to the bound tool name.
        tool_name = (
            message.recipient.capability
            if message.recipient and message.recipient.capability
            else self._tool_name
        )
        try:
            result = await self._client.call_tool(tool_name, payload)
        except Exception as exc:
            result = {"success": False, "output": "", "error": str(exc)}
        await _store_and_emit(self, message, result)


async def register_mcp_tools_as_capabilities(
    system: ActorSystem,
    client: MCPClient,
    actor_id: str = "mcp_actor",
) -> List[AgentCell]:
    """List tools from *client* and register each as an actor capability.

    A single :class:`MCPActor` is spawned for the whole MCP server; each tool
    is advertised as a capability pointing back to that actor.  The actor
    dispatches INVOKE messages to the appropriate tool name.
    """
    try:
        tools = await client.list_tools()
    except Exception:
        return []

    actor = MCPActor(actor_id, client, tool_name="")
    system.actors[actor_id] = actor
    actor._system = system

    for tool in tools:
        name = tool.get("name", "")
        if not name:
            continue
        actor.register_capability(
            Capability(
                name=name,
                schema=tool.get("inputSchema", {}),
                confidence=1.0,
            )
        )
    system._ensure_running(actor)
    return [actor]


def register_tool_actors(
    system: ActorSystem, registry: Optional[Any] = None
) -> List[AgentCell]:
    """Spawn all native tool actors in *system* and register their capabilities.

    An optional *registry* may be supplied for future registry-aware actor
    registration; native tool actors are always spawned regardless.

    Returns the list of spawned actors.
    """
    definitions: List[tuple[str, type[AgentCell], List[str]]] = [
        ("filesystem_actor", FileSystemActor, FileSystemActor.CAPABILITIES),
        ("terminal_actor", TerminalActor, TerminalActor.CAPABILITIES),
        ("search_actor", SearchActor, SearchActor.CAPABILITIES),
        ("code_runner_actor", CodeRunnerActor, CodeRunnerActor.CAPABILITIES),
        ("bci_actor", BCIAdapterActor, BCIAdapterActor.CAPABILITIES),
        ("browser_actor", BrowserActor, BrowserActor.CAPABILITIES),
    ]

    spawned: List[AgentCell] = []
    for actor_id, cls, capabilities in definitions:
        actor = cls(actor_id)
        system.actors[actor_id] = actor
        actor._system = system
        for cap in capabilities:
            actor.register_capability(Capability(cap))
        system._ensure_running(actor)
        spawned.append(actor)
    return spawned
