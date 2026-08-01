"""Unit tests for AGIBrain / Agent Aether Actor composition."""

from __future__ import annotations

import asyncio
from typing import Any, List

import pytest

from laap.agent.base import AGIBrain, Agent, AgentConfig
from laap.orchestration.actor import ActorState, ActorSystem, Capability
from laap.orchestration.primitives import AetherAddress, AetherMessage, MessageType


def _run(coro):
    """Run an async helper inside a synchronous pytest test."""
    return asyncio.run(coro)


async def _wait_for(condition, timeout: float = 1.0, interval: float = 0.01) -> None:
    """Wait until *condition* is truthy or *timeout* expires."""
    deadline = asyncio.get_event_loop().time() + timeout
    while not condition():
        if asyncio.get_event_loop().time() > deadline:
            raise AssertionError("Timeout waiting for condition")
        await asyncio.sleep(interval)


def _make_agent() -> AGIBrain:
    """Return a quiet AGIBrain instance for testing."""
    return AGIBrain(
        config=AgentConfig(
            verbose=False,
            enable_brain=False,
            enable_cortex=False,
            enable_first_principles=False,
        )
    )


def test_agent_has_actor_address():
    agent = _make_agent()
    addr = agent.actor_address
    assert isinstance(addr, AetherAddress)
    assert addr.actor_id == agent.id
    assert addr.host == "local"


def test_default_actor_capabilities_registered():
    agent = _make_agent()
    names = {c.name for c in agent._actor_cell.capabilities}
    expected = {"intent_parsing", "tool_execution", "reflection", "code_generation"}
    assert expected.issubset(names)
    for cap in agent._actor_cell.capabilities:
        if cap.name in expected:
            assert cap.confidence == pytest.approx(0.8)


def test_register_actor_capability():
    agent = _make_agent()
    cap = Capability(name="custom_skill", confidence=0.95)
    agent.register_actor_capability(cap)
    assert cap in agent._actor_cell.capabilities


def test_on_aether_message_and_handle():
    async def _test():
        agent = _make_agent()
        received: List[AetherMessage] = []

        def handler(msg: AetherMessage) -> None:
            received.append(msg)

        agent.on_aether_message(MessageType.INVOKE, handler)

        msg = AetherMessage(
            msg_type=MessageType.INVOKE,
            sender=AetherAddress(host="local", actor_id="root"),
            recipient=agent.actor_address,
            payload={"value": 42},
        )
        await agent.handle_aether_message(msg)
        assert len(received) == 1
        assert received[0].payload["value"] == 42

    _run(_test())


def test_aether_message_via_actor_system():
    async def _test():
        agent = _make_agent()
        received: List[AetherMessage] = []

        async def handler(msg: AetherMessage) -> None:
            received.append(msg)

        agent.on_aether_message(MessageType.INVOKE, handler)

        system = ActorSystem("test-agent-system")
        try:
            # Register the agent's composed cell into the system manually.
            agent._actor_cell._system = system
            system.actors[agent.id] = agent._actor_cell

            system._ensure_running(agent._actor_cell)
            await _wait_for(
                lambda: agent._actor_cell.state == ActorState.IDLE, timeout=0.5
            )

            msg = AetherMessage(
                msg_type=MessageType.INVOKE,
                sender=AetherAddress(host="local", actor_id="root"),
                recipient=agent.actor_address,
                payload={"value": 7},
            )
            await system.send(msg)
            await _wait_for(lambda: len(received) == 1, timeout=0.5)

            assert received[0].payload["value"] == 7
            assert agent._actor_cell.metrics["messages_processed"] >= 1
        finally:
            await system.shutdown()

    _run(_test())


def test_actor_status():
    agent = _make_agent()
    status = agent.actor_status()
    assert status["actor_id"] == agent.id
    assert "aether://local/" in status["address"]
    assert "capabilities" in status
    assert "metrics" in status


def test_status_backward_compatible():
    agent = _make_agent()
    s = agent.status()
    assert "id" in s
    assert "name" in s
    assert "alive" in s
    assert "steps" in s
    assert "age_s" in s
    assert "tools" in s


def test_die_stops_actor_cell():
    agent = _make_agent()
    agent.die("test")
    assert not agent.alive
    assert agent._actor_cell.state == ActorState.TERMINATED


def test_agent_alias_is_instance_of_agibrain():
    with pytest.warns(DeprecationWarning):
        agent = Agent(config=AgentConfig(verbose=False))
    assert isinstance(agent, AGIBrain)
    assert hasattr(agent, "_actor_cell")
    assert isinstance(agent.actor_address, AetherAddress)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-p", "no:quadrants", "--no-cov"])
