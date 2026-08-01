"""Route AetherMessages to local actors or remote nodes."""

from __future__ import annotations

from laap.orchestration.distributed.codec import AetherCodec
from laap.orchestration.distributed.exceptions import ActorRoutingError
from laap.orchestration.distributed.registry import RemoteActorRegistry
from laap.orchestration.distributed.transport import Transport
from laap.orchestration.primitives import AetherAddress, AetherMessage


class DistributedRouter:
    """Decides whether a message is local or remote and forwards it accordingly."""

    def __init__(
        self,
        local_node_id: str,
        registry: RemoteActorRegistry,
        transport: Transport,
    ) -> None:
        self.local_node_id = local_node_id
        self.registry = registry
        self.transport = transport
        self.codec = AetherCodec()

    def is_local(self, address: AetherAddress) -> bool:
        """Return ``True`` if *address* belongs to the local node."""
        return self.registry.node_id_for(address) == self.local_node_id

    async def route(self, address: AetherAddress, msg: AetherMessage) -> None:
        """Deliver *msg* to *address*.

        Local addresses are handled in-place (the caller dispatches to the
        local actor system). Remote addresses are serialized and sent over the
        transport to the node that owns *address*.
        """
        if self.is_local(address):
            return
        node_location = await self.registry.lookup_node(address)
        if node_location is None:
            raise ActorRoutingError(f"no route to {address}")
        host, port_str = node_location.rsplit(":", 1)
        payload = self.codec.encode(msg)
        await self.transport.send(host, int(port_str), payload)
