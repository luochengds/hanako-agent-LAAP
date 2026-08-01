"""Phase 4 — Hanako integration (TrainingIntegration) unit tests."""
import json
import os
import tempfile
import pytest
from laap.training.integration import (
    TrainingConfig,
    TrainingIntegration,
    integrate_training,
    enable_training_config,
)


# Mock Agent for tests
class MockAgent:
    def __init__(self):
        self._agent_id = "mock-agent-1"
        self.config = type("Config", (), {
            "name": "MockAgent",
            "mode": type("Mode", (), {"value": "kernel"}),
        })()
        self.training_config = {}


class TestTrainingConfig:
    def test_defaults(self):
        cfg = TrainingConfig()
        assert cfg.enabled is False
        assert cfg.rollout_collector is True
        assert cfg.max_concurrent == 4
        assert cfg.reward_weights is not None
        assert cfg.reward_weights["fitness"] == 0.30

    def test_enabled(self):
        cfg = TrainingConfig(enabled=True)
        assert cfg.enabled is True

    def test_custom_weights(self):
        cfg = TrainingConfig(reward_weights={"fitness": 0.5, "task_completion": 0.5})
        assert cfg.reward_weights["fitness"] == 0.5

    def test_post_init_weights(self):
        cfg = TrainingConfig(reward_weights=None)
        assert cfg.reward_weights is not None


class TestTrainingIntegration:
    def test_create_disabled(self):
        agent = MockAgent()
        integration = TrainingIntegration(
            config=TrainingConfig(enabled=False),
            agent=agent,
        )
        assert integration.enabled is False
        assert integration.collector is None
        assert integration.builder is None

    def test_create_enabled(self):
        agent = MockAgent()
        integration = TrainingIntegration(
            config=TrainingConfig(enabled=True),
            agent=agent,
        )
        assert integration.enabled is True
        assert integration.collector is not None
        assert integration.builder is not None

    def test_start_episode(self):
        agent = MockAgent()
        integration = TrainingIntegration(
            config=TrainingConfig(enabled=True),
            agent=agent,
        )
        eid = integration.start_episode()
        assert eid != ""
        assert integration._episode_count == 1

    def test_end_episode(self):
        agent = MockAgent()
        integration = TrainingIntegration(
            config=TrainingConfig(enabled=True),
            agent=agent,
        )
        integration.start_episode()
        tid = integration.end_episode()
        assert tid is not None

    def test_record_reward(self):
        agent = MockAgent()
        integration = TrainingIntegration(
            config=TrainingConfig(enabled=True),
            agent=agent,
        )
        integration.start_episode()
        integration.record_reward(0.8, source="task_completion")
        integration.end_episode()

        status = integration.status()
        assert status["rollout_collector"]["total_trajectories"] == 1

    def test_set_enabled(self):
        agent = MockAgent()
        integration = TrainingIntegration(
            config=TrainingConfig(enabled=True),
            agent=agent,
        )
        assert integration.enabled is True
        integration.set_enabled(False)
        assert integration.enabled is False
        integration.set_enabled(True)
        assert integration.enabled is True

    def test_reset(self):
        agent = MockAgent()
        integration = TrainingIntegration(
            config=TrainingConfig(enabled=True),
            agent=agent,
        )
        integration.start_episode()
        integration.end_episode()
        assert integration._episode_count == 1

        integration.reset()
        assert integration._episode_count == 0
        assert integration._export_count == 0

    def test_status_structure(self):
        agent = MockAgent()
        integration = TrainingIntegration(
            config=TrainingConfig(enabled=True),
            agent=agent,
        )
        status = integration.status()
        assert "rollout_collector" in status
        assert "training_orchestrator" in status
        assert "trajectory_builder" in status
        assert "export" in status
        assert "episodes" in status

    def test_export_trajectories(self):
        agent = MockAgent()
        integration = TrainingIntegration(
            config=TrainingConfig(enabled=True),
            agent=agent,
        )

        integration.start_episode()
        from laap.training.rollout_collector import TurnSnapshot
        integration.collector.record_turn(TurnSnapshot(
            turn_id=1, user_message="hi", assistant_response="hello",
            tokens_in=5, tokens_out=10, duration_ms=100.0,
        ))
        integration.record_reward(0.8, source="task_completion")
        integration.end_episode()

        with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl',
                                         delete=False) as f:
            path = f.name

        try:
            count = integration.export_trajectories(path)
            assert count >= 1

            # Verify output file exists and is valid JSONL
            with open(path, 'r', encoding='utf-8') as f:
                line = f.readline().strip()
                record = json.loads(line)
                assert "trajectory_id" in record
                assert "reward" in record
        finally:
            os.unlink(path)

    def test_auto_export(self):
        agent = MockAgent()
        integration = TrainingIntegration(
            config=TrainingConfig(enabled=True, auto_export=True),
            agent=agent,
            data_dir=tempfile.mkdtemp(),
        )

        # Start and end episode should trigger auto export
        integration.start_episode()
        from laap.training.rollout_collector import TurnSnapshot
        integration.collector.record_turn(TurnSnapshot(
            turn_id=1, user_message="hi", assistant_response="hello",
            tokens_in=5, tokens_out=10, duration_ms=100.0,
        ))
        integration.record_reward(1.0, source="task_completion")
        integration.end_episode()

        # Check that export count increased
        status = integration.status()
        # auto export worked
        assert integration._export_count >= 1

    def test_get_orchestrator(self):
        agent = MockAgent()
        integration = TrainingIntegration(
            config=TrainingConfig(enabled=True),
            agent=agent,
        )
        orch = integration.get_orchestrator()
        assert orch is not None
        assert integration._orchestrator_initialized is True


class TestIntegrateFunction:
    def test_integrate_enabled(self):
        agent = MockAgent()
        integration = integrate_training(agent, config_dict={
            "enabled": True,
        })
        assert integration is not None
        assert hasattr(agent, 'training')
        assert agent.training is integration

    def test_integrate_disabled(self):
        agent = MockAgent()
        integration = integrate_training(agent, config_dict={
            "enabled": False,
        })
        assert integration is None

    def test_integrate_from_agent_config(self):
        agent = MockAgent()
        agent.training_config = {"enabled": True}
        integration = integrate_training(agent)
        assert integration is not None
        assert integration.enabled is True

    def test_enable_training_config(self):
        # Simulate an AgentConfig-like object
        class FakeConfig:
            pass

        config = FakeConfig()
        enable_training_config(config, enabled=True, max_concurrent=8)

        assert hasattr(config, 'training')
        assert config.training.enabled is True
        assert config.training.max_concurrent == 8
