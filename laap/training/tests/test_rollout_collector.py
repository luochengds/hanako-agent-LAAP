"""Phase 1 — RolloutCollector unit tests."""
import json
import os
import tempfile
import pytest
from laap.training.rollout_collector import (
    RolloutCollector,
    TurnSnapshot,
    ToolCallSnapshot,
    Trajectory,
    RewardSignal,
    create_collector,
)


class TestTurnSnapshot:
    def test_to_dict(self):
        ts = TurnSnapshot(turn_id=1, user_message="你好", assistant_response="嗨")
        d = ts.to_dict()
        assert d["turn_id"] == 1
        assert d["user_message"] == "你好"
        assert d["assistant_response"] == "嗨"

    def test_with_tool_calls(self):
        tc = ToolCallSnapshot(tool_name="search", arguments={"q": "test"}, result="result")
        ts = TurnSnapshot(turn_id=1, user_message="?", assistant_response="!",
                          tool_calls=[tc])
        d = ts.to_dict()
        assert len(d["tool_calls"]) == 1
        assert d["tool_calls"][0]["tool_name"] == "search"


class TestTrajectory:
    def test_empty(self):
        t = Trajectory(trajectory_id="test-1")
        assert len(t.turns) == 0
        assert t.total_tokens() == 0
        assert t.total_duration_ms() == 0.0

    def test_add_turn_and_reward(self):
        t = Trajectory(trajectory_id="test-1")
        t.add_turn(TurnSnapshot(turn_id=1, tokens_in=10, tokens_out=20))
        t.add_reward(RewardSignal(value=0.9, source="task_completion"))
        assert len(t.turns) == 1
        assert len(t.rewards) == 1
        assert t.total_tokens() == 30

    def test_compute_final_reward(self):
        t = Trajectory(trajectory_id="test-1")
        t.add_reward(RewardSignal(value=0.8, source="fitness"))
        t.add_reward(RewardSignal(value=1.0, source="task_completion"))
        assert t.compute_final_reward() == 0.9  # average
        assert t.final_reward == 0.9

    def test_latest_per_source(self):
        t = Trajectory(trajectory_id="test-1")
        t.add_reward(RewardSignal(value=0.5, source="fitness"))
        t.add_reward(RewardSignal(value=0.9, source="fitness"))  # newer
        t.add_reward(RewardSignal(value=1.0, source="task_completion"))
        assert t.compute_final_reward() == pytest.approx(0.95)  # (0.9 + 1.0) / 2

    def test_to_training_record(self):
        t = Trajectory(trajectory_id="test-1")
        t.add_turn(TurnSnapshot(turn_id=1, user_message="hi", assistant_response="hello",
                                tokens_in=5, tokens_out=10))
        t.add_reward(RewardSignal(value=0.75, source="task_completion"))
        record = t.to_training_record()
        assert record["trajectory_id"] == "test-1"
        assert len(record["conversations"]) == 2
        assert record["conversations"][0]["role"] == "user"
        assert record["conversations"][1]["role"] == "assistant"
        assert record["reward"] == 0.75
        assert record["metadata"]["num_turns"] == 1

    def test_to_training_record_with_tool_calls(self):
        tc = ToolCallSnapshot(tool_name="search", arguments={"q": "weather"}, result="sunny")
        turn = TurnSnapshot(turn_id=1, user_message="天气?", assistant_response="晴天",
                            tool_calls=[tc])
        t = Trajectory(trajectory_id="test-1")
        t.add_turn(turn)
        record = t.to_training_record()
        assert "tool_calls" in record["conversations"][1]
        assert record["conversations"][1]["tool_calls"][0]["name"] == "search"

    def test_to_training_record_with_error(self):
        turn = TurnSnapshot(turn_id=1, user_message="hi", assistant_response="",
                            error="API timeout")
        t = Trajectory(trajectory_id="test-1")
        t.add_turn(turn)
        record = t.to_training_record()
        assert len(record["conversations"]) == 3  # user, assistant (empty), error
        assert record["conversations"][2]["content"] == "[error] API timeout"

    def test_to_jsonl_line(self):
        t = Trajectory(trajectory_id="test-1")
        t.add_turn(TurnSnapshot(turn_id=1, user_message="hi", assistant_response="hello"))
        line = t.to_jsonl_line()
        parsed = json.loads(line)
        assert parsed["trajectory_id"] == "test-1"


class TestRolloutCollector:
    def test_create(self):
        c = RolloutCollector()
        assert c.enabled is True
        assert c.is_active() is False
        assert len(c.get_trajectories()) == 0

    def test_create_collector_factory(self):
        c = create_collector(enabled=False)
        assert c.enabled is False

        c = create_collector(auto_start=True)
        assert c.is_active() is True

    def test_set_enabled(self):
        c = RolloutCollector()
        c.set_enabled(False)
        assert c.enabled is False
        # disabled 时 record 不应构建轨迹
        c.start_episode()
        c.record_turn(TurnSnapshot(turn_id=1))
        c.record_reward(1.0, "test")
        c.end_episode()
        assert len(c.get_trajectories()) == 0

    def test_full_episode_lifecycle(self):
        c = RolloutCollector()
        eid = c.start_episode(metadata={"env": "test"})
        assert eid != ""
        assert c.is_active()

        for i in range(3):
            c.record_turn(TurnSnapshot(
                turn_id=i + 1,
                user_message=f"msg_{i}",
                assistant_response=f"resp_{i}",
                tokens_in=10, tokens_out=20,
                duration_ms=100.0,
            ))

        c.record_reward(0.8, source="fitness")
        c.record_reward(1.0, source="task_completion")
        tid = c.end_episode()

        assert tid == eid
        assert c.is_active() is False
        assert len(c.get_trajectories()) == 1

        traj = c.get_trajectories()[0]
        assert len(traj.turns) == 3
        assert traj.final_reward == 0.9  # avg of 0.8 and 1.0

    def test_discarded_episode(self):
        c = RolloutCollector()
        c.start_episode()
        c.record_turn(TurnSnapshot(turn_id=1))
        c.end_episode(status="failed")
        assert len(c.get_trajectories()) == 0  # discarded

    def test_export_jsonl(self):
        c = RolloutCollector()
        c.start_episode()
        c.record_turn(TurnSnapshot(turn_id=1, user_message="hi", assistant_response="hello"))
        c.record_reward(1.0, source="test")
        c.end_episode()

        with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False) as f:
            path = f.name

        try:
            count = c.export_jsonl(path)
            assert count == 1
            with open(path, 'r', encoding='utf-8') as f:
                line = f.readline().strip()
                parsed = json.loads(line)
                assert parsed["trajectory_id"] == c.get_trajectories()[0].trajectory_id
        finally:
            os.unlink(path)

    def test_export_empty_episode(self):
        """空轨迹不应导出。"""
        c = RolloutCollector()
        c.start_episode()
        c.end_episode()  # 没有任何 turn

        with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False) as f:
            path = f.name

        try:
            count = c.export_jsonl(path)
            assert count == 0  # 空轨迹被跳过
        finally:
            os.unlink(path)

    def test_summary(self):
        c = RolloutCollector()
        c.start_episode(metadata={"env": "test"})
        c.record_turn(TurnSnapshot(turn_id=1, tokens_in=10, tokens_out=20))
        c.end_episode()

        s = c.summary()
        assert s["enabled"] is True
        assert s["total_trajectories"] == 1
        assert s["by_status"]["completed"] == 1
        assert s["total_tokens_collected"] == 30

    def test_reset(self):
        c = RolloutCollector()
        c.start_episode()
        c.record_turn(TurnSnapshot(turn_id=1))
        c.end_episode()
        assert len(c.get_trajectories()) == 1
        c.reset()
        assert len(c.get_trajectories()) == 0

    def test_wrap(self):
        c = RolloutCollector()

        def fake_chat(msg: str) -> str:
            return f"echo: {msg}"

        wrapped = c.wrap(fake_chat)
        result = wrapped("hello")
        assert result == "echo: hello"

        # 应自动创建 episode
        assert c.is_active() is True
        assert len(c.get_trajectories()) == 0  # 还没结束

        # 结束
        c.end_episode()
        assert len(c.get_trajectories()) == 1

    def test_conversation_loop_callbacks(self):
        """验证 ConversationLoop 的回调签名兼容性。"""
        c = RolloutCollector()

        # turn_complete 回调接收一个类似 TurnRecord 的对象
        class FakeTurnRecord:
            turn_id = 1
            user_msg = "hello"
            assistant_msg = "hi"
            duration_ms = 500.0
            error = ""
            tokens_in = 10
            tokens_out = 20
            tool_calls = []

        c.start_episode()
        c.on_turn_complete(FakeTurnRecord())
        assert len(c.get_current_trajectory().turns) == 1

        # tool_call 回调
        class FakeToolData:
            tool_name = "search"

        c.on_tool_call({"tool": "search", "result": "found"})
        # 只是日志, 不修改状态
        assert len(c.get_current_trajectory().turns) == 1

        # episode_end
        c.on_episode_end({"status": "completed"})
        assert c.is_active() is False

    def test_multiple_episodes(self):
        c = RolloutCollector()
        for i in range(3):
            c.start_episode(metadata={"ep": i})
            for j in range(2):
                c.record_turn(TurnSnapshot(turn_id=j + 1, tokens_in=5))
            c.record_reward(float(i) / 2.0, source="test")
            c.end_episode()

        assert len(c.get_trajectories()) == 3
        assert c.summary()["total_tokens_collected"] == 3 * 2 * 5

    def test_double_start(self):
        """连续两次 start_episode 应给出警告并保留第一个。"""
        c = RolloutCollector()
        eid1 = c.start_episode()
        eid2 = c.start_episode()
        assert eid1 == eid2  # 第二次被拒绝, 返回第一个

    def test_end_without_start(self):
        c = RolloutCollector()
        tid = c.end_episode()
        assert tid is None
