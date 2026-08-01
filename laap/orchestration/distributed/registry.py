"""Registry mapping actor addresses to remote nodes."""

from __future__ import annotations

import asyncio

from laap.orchestration.primitives import AetherAddress


class RemoteActorRegistry:
    """Thread-safe (asyncio-aware) registry of actor addresses and node locations."""

    def __init__(self) -> None:
        self._actors: dict[AetherAddress, str] = {}
        self._nodes: dict[str, str] = {}
        self._lock = asyncio.Lock()

    async def register(self, address: AetherAddress, node_id: str) -> None:
        async with self._lock:
            self.register_sync(address, node_id)

    def register_sync(self, address: AetherAddress, node_id: str) -> None:
        """Synchronous variant used when the caller is already on the event loop."""
        self._actors[address] = node_id
        if node_id not in self._nodes:
            self._nodes[node_id] = node_id

    async def lookup_node(self, address: AetherAddress) -> str | None:
        """Return the ``host:port`` location for *address*, if known."""
        async with self._lock:
            node_id = self._actors.get(address)
            return self._nodes.get(node_id) if node_id is not None else None

    def node_id_for(self, address: AetherAddress) -> str | None:
        """Return the raw node id that owns *address*, if known."""
        return self._actors.get(address)

    async def remove_node(self, node_id: str) -> None:
        async with self._lock:
            self._nodes.pop(node_id, None)
            self._actors = {addr: nid for addr, nid in self._actors.items() if nid != node_id}

    async def actors_on_node(self, node_id: str) -> list[AetherAddress]:
        async with self._lock:
            return [addr for addr, nid in self._actors.items() if nid == node_id]

    def _register_node_location(self, node_id: str, location: str) -> None:
        """Internal helper for cluster managers to set a node's ``host:port``."""
        self._nodes[node_id] = location
