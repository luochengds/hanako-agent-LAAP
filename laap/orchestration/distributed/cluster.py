"""Cluster membership and peer message handling."""

from __future__ import annotations

import msgpack

from laap.orchestration.distributed.registry import RemoteActorRegistry
from laap.orchestration.distributed.transport import Transport
from laap.orchestration.primitives import AetherAddress


class ClusterManager:
    """Manages a small cluster of LAAP nodes over a :class:`Transport`."""

    def __init__(
        self,
        transport: Transport,
        registry: RemoteActorRegistry,
        node_id: str,
        host: str,
        port: int,
    ) -> None:
        self.transport = transport
        self.registry = registry
        self.node_id = node_id
        self.host = host
        self.port = port
        self._peers: set[str] = set()

    @property
    def address(self) -> str:
        return f"{self.host}:{self.port}"

    async def listen(self) -> None:
        """Start listening for peer messages on this node's transport endpoint."""
        await self.transport.listen(self.host, self.port, self.on_peer_message)

    async def join(self, seed_nodes: list[str]) -> None:
        """Send a handshake to each seed node and exchange membership info."""
        envelope = {
            "kind": "handshake",
            "node_id": self.node_id,
            "host": self.host,
            "port": self.port,
            "peers": list(self._peers),
            "actors": [],
        }
        payload = msgpack.packb(envelope, use_bin_type=True)
        for seed in seed_nodes:
            if seed == self.address or seed == self.node_id:
                continue
            host, port_str = seed.rsplit(":", 1)
            await self.transport.send(host, int(port_str), payload)

    async def heartbeat(self) -> None:
        """Send a single heartbeat to all known peers."""
        envelope = {
            "kind": "heartbeat",
            "node_id": self.node_id,
            "host": self.host,
            "port": self.port,
        }
        payload = msgpack.packb(envelope, use_bin_type=True)
        for peer_addr in list(self._peers):
            host, port_str = peer_addr.rsplit(":", 1)
            await self.transport.send(host, int(port_str), payload)

    def peers(self) -> list[str]:
        """Return the list of known peer ``host:port`` addresses."""
        return list(self._peers)

    async def on_peer_message(self, payload: bytes) -> None:
        """Dispatch incoming cluster messages."""
        try:
            envelope = msgpack.unpackb(payload, raw=False)
        except Exception:
            return

        kind = envelope.get("kind")
        node_id = envelope.get("node_id")
        host = envelope.get("host")
        port = envelope.get("port")
        if not isinstance(host, str) or not isinstance(port, int):
            return
        peer_addr = f"{host}:{port}"

        if kind == "handshake":
            self._peers.add(peer_addr)
            self.registry._register_node_location(node_id, peer_addr)
            reply = {
                "kind": "handshake_reply",
                "node_id": self.node_id,
                "host": self.host,
                "port": self.port,
            }
            await self.transport.send(host, port, msgpack.packb(reply, use_bin_type=True))
            for actor_dict in envelope.get("actors", []):
                address = AetherAddress.from_dict(actor_dict)
                await self.registry.register(address, node_id)
        elif kind == "handshake_reply":
            self._peers.add(peer_addr)
            self.registry._register_node_location(node_id, peer_addr)
        elif kind == "heartbeat":
            self._peers.add(peer_addr)
        elif kind == "actor_register":
            for actor_dict in envelope.get("actors", []):
                address = AetherAddress.from_dict(actor_dict)
                await self.registry.register(address, node_id)
