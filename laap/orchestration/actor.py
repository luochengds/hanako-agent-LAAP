"""LAAP Aether — Actor runtime for orchestration."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set, Tuple

from laap.orchestration.distributed import (
    ActorRoutingError,
    AetherCodec,
    ClusterManager,
    DistributedRouter,
    RemoteActorRegistry,
    TCPTransport,
    Transport,
)
from laap.orchestration.primitives import AetherAddress, AetherMessage, MessageType

import numpy as np

logger = logging.getLogger("laap.orchestration.actor")


class ActorState(Enum):
    """Lifecycle states of an Aether actor."""

    SPAWNED = auto()
    IDLE = auto()
    PROCESSING = auto()
    SUSPENDED = auto()
    TERMINATED = auto()
    RECOVERING = auto()


@dataclass
class Capability:
    """A capability advertised by an actor."""

    name: str
    confidence: float = 1.0
    schema: Dict[str, Any] = field(default_factory=dict)
    cost_estimate: float = 0.0
    latency_estimate_ms: float = 0.0

    def can_handle(self, requirement: str, threshold: float = 0.7) -> bool:
        """Return True if this capability can handle *requirement*."""
        return (
            self.confidence >= threshold
            and self.name.lower() == requirement.lower()
        )


HandlerCallable = Callable[[AetherMessage], Awaitable[None]]


class AgentCell:
    """An asynchronous actor that processes AetherMessages."""

    def __init__(
        self,
        actor_id: str,
        host: str = "local",
        supervisor: Optional[AetherAddress] = None,
        max_retries: int = 3,
    ):
        self.actor_id: str = actor_id
        self.host: str = host
        self.address: AetherAddress = AetherAddress(host=host, actor_id=actor_id)
        self.state: ActorState = ActorState.SPAWNED
        self.mailbox: asyncio.Queue[AetherMessage] = asyncio.Queue(maxsize=1000)
        self.state_lock: asyncio.Lock = asyncio.Lock()

        self.core_memory: Dict[str, Any] = {}
        self.working_memory: Dict[str, Any] = {}
        self.archival_memory: Dict[str, Any] = {}
        self.capabilities: List[Capability] = []
        self.claimed_tasks: Set[str] = set()
        self.supervisor: Optional[AetherAddress] = supervisor
        self.children: Set[AetherAddress] = set()

        self.max_retries: int = max_retries
        self.current_retry: int = 0

        self.metrics: Dict[str, Any] = {
            "messages_processed": 0,
            "errors": 0,
            "avg_latency_ms": 0.0,
            "claims_accepted": 0,
        }

        # Direction: 方向向量 (与 laap.orchestration.direction 集成)
        self.direction_vector: Optional[np.ndarray] = None

        self._handlers: Dict[MessageType, HandlerCallable] = {}
        self._task: Optional[asyncio.Task[None]] = None
        self._system: Optional[ActorSystem] = None

    def register_capability(self, capability: Capability) -> None:
        """Advertise a capability on this actor."""
        self.capabilities.append(capability)
        if self._system is not None:
            self._system._register_capability(self.address, capability)

    def register_direction(self, direction_vector: np.ndarray) -> None:
        """
        注册方向向量，启用方向余弦匹配路由。

        Args:
            direction_vector: 3 维方向向量 (cognition, response, abstraction)
                              与 laap.orchestration.direction.DIRECTION_TEMPLATES 兼容。
        """
        from laap.orchestration.direction import cosine_similarity
        self.direction_vector = direction_vector.flatten()[:3]
        self._direction_similarity = cosine_similarity

    def can_handle_direction(self, task_vector: np.ndarray,
                             threshold: float = 0.3) -> float:
        """判断能否处理给定方向的任务。返回匹配分数 0~1。"""
        if self.direction_vector is None:
            return 0.0
        sim = self._direction_similarity(self.direction_vector, task_vector)
        return sim if sim >= threshold else 0.0

    def on(self, msg_type: MessageType, handler: HandlerCallable) -> None:
        """Register a handler for a specific message type."""
        self._handlers[msg_type] = handler

    async def send(self, message: AetherMessage) -> None:
        """Increment vector clock and enqueue a message."""
        message.increment_clock(self.actor_id)
        await self.mailbox.put(message)

    async def _process_message(self, message: AetherMessage) -> None:
        """Process a single message with retries and escalation."""
        handler = self._handlers.get(message.msg_type)
        if handler is None:
            logger.warning(f"[{self.actor_id}] No handler for {message.msg_type}")
            self.metrics["errors"] += 1
            await self._escalate(message, reason="no_handler")
            return

        async with self.state_lock:
            self.state = ActorState.PROCESSING

        start = time.monotonic()
        success = False
        for attempt in range(self.max_retries + 1):
            self.current_retry = attempt
            try:
                await handler(message)
                success = True
                break
            except Exception as exc:
                logger.warning(
                    f"[{self.actor_id}] Handler failed (attempt {attempt}): {exc}"
                )
                if attempt < self.max_retries:
                    backoff = 0.1 * (2 ** attempt)
                    await asyncio.sleep(backoff)

        elapsed_ms = (time.monotonic() - start) * 1000

        if success:
            self.metrics["messages_processed"] += 1
            self._update_avg_latency(elapsed_ms)
            async with self.state_lock:
                self.state = ActorState.IDLE
        else:
            self.metrics["errors"] += 1
            async with self.state_lock:
                self.state = ActorState.RECOVERING
            await self._escalate(message, reason="handler_failed")
            async with self.state_lock:
                self.state = ActorState.IDLE

    def _update_avg_latency(self, latency_ms: float) -> None:
        """Update rolling average latency."""
        n = self.metrics["messages_processed"]
        if n <= 1:
            self.metrics["avg_latency_ms"] = latency_ms
        else:
            prev = self.metrics["avg_latency_ms"]
            self.metrics["avg_latency_ms"] = prev + (latency_ms - prev) / n

    async def _escalate(self, message: AetherMessage, reason: str) -> None:
        """Forward a failed message to the supervisor via the actor system."""
        if self.supervisor is None or self._system is None:
            logger.error(
                f"[{self.actor_id}] Cannot escalate: supervisor={self.supervisor}, system={self._system}"
            )
            return

        escalation = AetherMessage(
            msg_type=MessageType.EMIT,
            sender=self.address,
            recipient=self.supervisor,
            payload={
                "event": "escalation",
                "reason": reason,
                "original": {
                    "msg_id": message.msg_id,
                    "msg_type": message.msg_type.value,
                    "payload": message.payload,
                },
            },
        )
        await self._system.send(escalation)

    async def run(self) -> None:
        """Main loop consuming messages from the mailbox."""
        async with self.state_lock:
            self.state = ActorState.IDLE

        while self.state != ActorState.TERMINATED:
            try:
                message = await asyncio.wait_for(self.mailbox.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue

            await self._process_message(message)

    def stop(self) -> None:
        """Cancel the actor task and mark it terminated."""
        self.state = ActorState.TERMINATED
        if self._task is not None and not self._task.done():
            self._task.cancel()


class ActorSystem:
    """Container that spawns and routes messages among actors."""

    def __init__(
        self,
        system_id: str,
        node_id: str = "local",
        host: str = "127.0.0.1",
        port: int = 7777,
        seed_nodes: Optional[List[str]] = None,
        enable_remote: bool = False,
    ):
        self.system_id: str = system_id
        self.node_id: str = node_id
        self.host: str = host
        self.port: int = port
        self.actors: Dict[str, AgentCell] = {}
        self.capability_registry: Dict[str, Set[AetherAddress]] = defaultdict(set)
        self.event_bus: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()
        self.subscribers: Dict[str, List[Callable[[Dict[str, Any]], None]]] = defaultdict(list)

        self._remote_registry: RemoteActorRegistry = RemoteActorRegistry()
        self._cluster: Optional[ClusterManager] = None
        self._transport: Optional[Transport] = None
        self._codec: AetherCodec = AetherCodec()
        self._router: DistributedRouter = DistributedRouter(
            self.node_id, self._remote_registry, TCPTransport()
        )

        self._seed_nodes: List[str] = seed_nodes or []
        self._auto_join: bool = bool(seed_nodes) or enable_remote
        self._cluster_task: Optional[asyncio.Task[None]] = None
        if self._auto_join:
            try:
                loop = asyncio.get_running_loop()
                self._cluster_task = loop.create_task(self.join_cluster(self._seed_nodes))
            except RuntimeError:
                # No running event loop yet; defer cluster join until one is available.
                pass

    def spawn(
        self,
        actor_id: str,
        host: str = "local",
        supervisor: Optional[AetherAddress] = None,
        capabilities: Optional[List[Capability]] = None,
        max_retries: int = 3,
    ) -> AgentCell:
        """Create and start a new actor."""
        if actor_id in self.actors:
            raise ValueError(f"Actor {actor_id} already exists in system {self.system_id}")

        actor = AgentCell(
            actor_id=actor_id, host=host, supervisor=supervisor, max_retries=max_retries
        )
        actor._system = self
        self.actors[actor_id] = actor

        for capability in capabilities or []:
            actor.register_capability(capability)

        try:
            loop = asyncio.get_running_loop()
            actor._task = loop.create_task(actor.run())
        except RuntimeError:
            # No running event loop yet; defer task creation until one is available.
            actor._task = None
        return actor

    def _ensure_running(self, actor: AgentCell) -> None:
        """Start the actor task if it was deferred."""
        if actor._task is None or actor._task.done():
            try:
                actor._task = asyncio.create_task(actor.run())
            except RuntimeError as exc:
                raise RuntimeError(
                    "Cannot start actor without a running event loop"
                ) from exc

    def is_local(self, address: AetherAddress) -> bool:
        """Return ``True`` if *address* belongs to this node."""
        host = getattr(address, "host", None)
        return host in (None, "local", self.node_id)

    def register_remote(self, address: AetherAddress, node_id: str) -> None:
        """Register a remote actor address with its owning node."""
        self._remote_registry.register_sync(address, node_id)

    async def join_cluster(
        self,
        seed_nodes: List[str],
        transport: Optional[Transport] = None,
    ) -> None:
        """Join a cluster and start listening for remote actor messages."""
        self._transport = transport or TCPTransport()
        self._router = DistributedRouter(
            self.node_id, self._remote_registry, self._transport
        )
        self._cluster = ClusterManager(
            self._transport,
            self._remote_registry,
            self.node_id,
            self.host,
            self.port,
        )
        await self._cluster.join(seed_nodes)
        await self._transport.listen(self.host, self.port, self._on_remote_message)

    async def send(
        self,
        address: AetherAddress | AetherMessage,
        msg: Optional[AetherMessage] = None,
    ) -> None:
        """Route a message to its recipient actor or to a remote node."""
        if isinstance(address, AetherMessage) and msg is None:
            message = address
            recipient = message.recipient
        else:
            message = msg
            recipient = address

        if recipient is None or message is None:
            logger.warning("Cannot send message with no recipient")
            return

        if not self.is_local(recipient):
            await self._remote_deliver(recipient, message)
            return

        actor = self.actors.get(recipient.actor_id)
        if actor is None:
            logger.warning(f"Unknown recipient actor: {recipient.actor_id}")
            return

        self._ensure_running(actor)
        await actor.send(message)

    async def _remote_deliver(self, address: AetherAddress, msg: AetherMessage) -> None:
        """Serialize and forward *msg* to the node that owns *address*."""
        node_location = await self._remote_registry.lookup_node(address)
        if node_location is None or self._transport is None:
            logger.error(f"No route to remote actor {address}")
            raise ActorRoutingError(f"no route to {address}")

        host, port_str = node_location.rsplit(":", 1)
        payload = self._codec.encode(msg)
        try:
            await self._transport.send(host, int(port_str), payload)
        except Exception as exc:
            logger.error(f"Failed to deliver message to {address}: {exc}")
            raise ActorRoutingError(f"failed to deliver to {address}") from exc

    async def _on_remote_message(self, payload: bytes) -> None:
        """Decode an incoming payload and dispatch it to a local actor."""
        try:
            msg = self._codec.decode(payload)
        except Exception as exc:
            logger.warning(f"Received undecodable remote payload: {exc}")
            return

        recipient = msg.recipient
        if recipient is None:
            logger.warning("Received remote message with no recipient")
            return

        await self.send(recipient, msg)

    async def broadcast(
        self,
        message: AetherMessage,
        capability_filter: Optional[str] = None,
    ) -> None:
        """Send copies of *message* to all matching actors."""
        targets = list(self.actors.values())
        if capability_filter is not None:
            capable = self.capability_registry.get(capability_filter, set())
            targets = [a for a in targets if a.address in capable]

        for actor in targets:
            self._ensure_running(actor)
            copy = AetherMessage(
                msg_id=message.msg_id,
                msg_type=message.msg_type,
                sender=message.sender,
                recipient=actor.address,
                payload=message.payload.copy(),
                vector_clock=message.vector_clock.copy(),
                timestamp=message.timestamp,
                priority=message.priority,
                ttl=message.ttl,
            )
            await actor.send(copy)

    def find_capable_agents(
        self,
        requirement: str,
        min_confidence: float = 0.7,
    ) -> List[Tuple[AgentCell, float]]:
        """Return actors that can handle *requirement*, sorted by confidence."""
        matches: List[Tuple[AgentCell, float]] = []
        seen: Set[AetherAddress] = set()
        for actor in self.actors.values():
            for capability in actor.capabilities:
                if capability.can_handle(requirement, threshold=min_confidence):
                    if actor.address not in seen:
                        matches.append((actor, capability.confidence))
                        seen.add(actor.address)
                    break
        matches.sort(key=lambda item: item[1], reverse=True)
        return matches

    def _register_capability(self, address: AetherAddress, capability: Capability) -> None:
        """Internal hook used by AgentCell.register_capability."""
        self.capability_registry[capability.name].add(address)

    async def shutdown(self) -> None:
        """Stop all actors in the system, close the transport, and await tasks."""
        if self._cluster_task is not None and not self._cluster_task.done():
            self._cluster_task.cancel()
            try:
                await self._cluster_task
            except asyncio.CancelledError:
                pass

        if self._transport is not None:
            await self._transport.close()

        for actor in list(self.actors.values()):
            actor.stop()
        pending = [
            actor._task
            for actor in self.actors.values()
            if actor._task is not None and not actor._task.done()
        ]
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
