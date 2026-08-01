"""ActorSystem-level distributed tests.

These tests verify that ActorSystem instances can exchange messages across
nodes while keeping local messaging unchanged.
"""

from __future__ import annotations

import asyncio
import socket
from typing import List

import pytest

from laap.orchestration.actor import ActorState, ActorSystem
from laap.orchestration.primitives import AetherAddress, AetherMessage, MessageType


def _free_port() -> int:
    """Return an ephemeral TCP port on 127.0.0.1."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


async def _wait_for(condition, timeout: float = 2.0, interval: float = 0.01) -> None:
    """Wait until *condition* is truthy or *timeout* expires."""
    deadline = asyncio.get_event_loop().time() + timeout
    while not condition():
        if asyncio.get_event_loop().time() > deadline:
            raise AssertionError("Timeout waiting for condition")
        await asyncio.sleep(interval)


class TestActorSystemRemote:
    async def test_actor_system_remote_roundtrip(self) -> None:
        """Two ActorSystem instances exchange a message and reply over TCP."""
        port_a = _free_port()
        port_b = _free_port()

        system_a = ActorSystem(
            "sys-a", node_id="node-a", host="127.0.0.1", port=port_a
        )
        system_b = ActorSystem(
            "sys-b", node_id="node-b", host="127.0.0.1", port=port_b
        )

        try:
            echo_received: List[AetherMessage] = []

            async def echo_handler(msg: AetherMessage) -> None:
                echo_received.append(msg)
                content = msg.payload.get("content", "")
                reply = AetherMessage(
                    msg_type=MessageType.INVOKE,
                    sender=msg.recipient,
                    recipient=msg.sender,
                    payload={"content": f"echo:{content}"},
                )
                await system_a.send(reply)

            echoer = system_a.spawn("echoer")
            echoer.on(MessageType.INVOKE, echo_handler)

            sender_received: List[AetherMessage] = []

            async def sender_handler(msg: AetherMessage) -> None:
                sender_received.append(msg)

            sender = system_b.spawn("sender")
            sender.on(MessageType.INVOKE, sender_handler)

            await system_a.join_cluster([f"127.0.0.1:{port_b}"])
            await system_b.join_cluster([f"127.0.0.1:{port_a}"])

            # Give the handshake a moment to exchange node locations.
            await asyncio.sleep(0.2)

            # Register the remote actors so each node can route to the other.
            echo_addr = AetherAddress(host="127.0.0.1", actor_id="echoer")
            sender_addr = AetherAddress(host="127.0.0.1", actor_id="sender")
            system_b.register_remote(echo_addr, "node-a")
            system_a.register_remote(sender_addr, "node-b")

            msg = AetherMessage(
                msg_type=MessageType.INVOKE,
                sender=sender.address,
                recipient=echo_addr,
                payload={"content": "ping"},
            )
            await system_b.send(msg)

            await _wait_for(lambda: len(echo_received) == 1)
            await _wait_for(lambda: len(sender_received) == 1)

            assert echo_received[0].payload == {"content": "ping"}
            assert sender_received[0].payload == {"content": "echo:ping"}
        finally:
            await system_a.shutdown()
            await system_b.shutdown()


class TestActorSystemLocal:
    async def test_actor_system_local_unchanged(self) -> None:
        """Local actor messaging works without joining a cluster."""
        system = ActorSystem("local-system")
        processed: List[AetherMessage] = []

        async def handler(msg: AetherMessage) -> None:
            processed.append(msg)

        actor = system.spawn("local")
        actor.on(MessageType.INVOKE, handler)
        await _wait_for(lambda: actor.state == ActorState.IDLE)

        msg = AetherMessage(
            msg_type=MessageType.INVOKE,
            sender=AetherAddress(host="local", actor_id="root"),
            recipient=actor.address,
            payload={"value": 42},
        )
        await system.send(msg)

        await _wait_for(lambda: len(processed) == 1)
        assert processed[0].payload == {"value": 42}
        actor.stop()
        await system.shutdown()


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-v", "-p", "no:quadrants", "--no-cov"]))
