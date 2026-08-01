"""Unit tests for ``laap.bci.bridge.BCICognitiveBridge``."""

from dataclasses import asdict

import numpy as np
import pytest

from laap.bci.bridge import BCICognitiveBridge
from laap.bci.primitives import CognitiveState, NeuroDataFrame
from laap.cognition.needs import NeedType


class MockHardware:
    def __init__(self):
        self.callbacks = []
        self.started = False
        self.stopped = False

    def register_stream_callback(self, cb):
        self.callbacks.append(cb)

    def start_stream(self):
        self.started = True

    def stop_stream(self):
        self.stopped = True


class MockPipeline:
    def __init__(self):
        self.calls = []

    def process_window(self, frame):
        self.calls.append(frame)
        return {"mock_features": True, "timestamp": frame.timestamp}


class MockDecoder:
    def __init__(self, focus="focused_executive", load=0.8):
        self.focus = focus
        self.load = load
        self.calls = []

    def decode(self, features):
        self.calls.append(features)
        return CognitiveState(
            attention_focus=self.focus,
            cognitive_load=self.load,
            emotion_vad={"valence": 0.2, "arousal": 0.6, "dominance": 0.5},
            timestamp=features.get("timestamp", 0.0),
        )


class MockSafety:
    def __init__(self, action="allow", reason="ok", attenuate=1.0):
        self.action = action
        self.reason = reason
        self.attenuate = attenuate
        self.calls = []

    def scan_neuro_injection(self, cog_state):
        self.calls.append(cog_state)
        return {
            "action": self.action,
            "reason": self.reason,
            "attenuate": self.attenuate,
        }


class MockAttentionEngine:
    def __init__(self):
        self.calls = []

    def boost_salience(self, **kwargs):
        self.calls.append(kwargs)


class MockNeedsSystem:
    def __init__(self):
        self.calls = []

    def update_external_estimate(self, need_type, deficit, confidence=0.5):
        self.calls.append(
            {"need_type": need_type, "deficit": deficit, "confidence": confidence}
        )


class MockEmotionSystem:
    def __init__(self):
        self.calls = []

    def set_external_vad(self, valence, arousal, dominance, source="external", confidence=0.5):
        self.calls.append(
            {
                "valence": valence,
                "arousal": arousal,
                "dominance": dominance,
                "source": source,
                "confidence": confidence,
            }
        )


class MockConsciousStream:
    def __init__(self):
        self.calls = []

    def experience_interoception(self, content, valence, intensity=0.6):
        self.calls.append(
            {"content": content, "valence": valence, "intensity": intensity}
        )


class MockWorldModel:
    def __init__(self):
        self.calls = []

    def update_entity(self, eid, properties=None, confidence=None, source=None):
        self.calls.append(
            {"eid": eid, "properties": properties, "confidence": confidence, "source": source}
        )


class MockEventBus:
    def __init__(self):
        self.events = []

    def publish_simple(self, event_type, data=None, source="system"):
        self.events.append({"type": event_type, "data": data, "source": source})


def _make_bridge(action="allow", attenuate=1.0, focus="focused_executive", load=0.8):
    hardware = MockHardware()
    pipeline = MockPipeline()
    decoder = MockDecoder(focus=focus, load=load)
    safety = MockSafety(action=action, attenuate=attenuate)
    attention = MockAttentionEngine()
    needs = MockNeedsSystem()
    emotion = MockEmotionSystem()
    conscious = MockConsciousStream()
    world_model = MockWorldModel()
    event_bus = MockEventBus()

    bridge = BCICognitiveBridge(
        hardware=hardware,
        pipeline=pipeline,
        decoder=decoder,
        safety=safety,
        attention_engine=attention,
        needs_system=needs,
        emotion_system=emotion,
        conscious_stream=conscious,
        world_model=world_model,
        event_bus=event_bus,
    )
    return bridge, {
        "hardware": hardware,
        "pipeline": pipeline,
        "decoder": decoder,
        "safety": safety,
        "attention": attention,
        "needs": needs,
        "emotion": emotion,
        "conscious": conscious,
        "world_model": world_model,
        "event_bus": event_bus,
    }


def _sample_frame():
    return NeuroDataFrame(
        timestamp=1234.5,
        eeg=np.zeros((16, 250), dtype=np.float64),
    )


def test_start_and_stop_wires_hardware():
    hardware = MockHardware()
    bridge = BCICognitiveBridge(
        hardware=hardware,
        pipeline=MockPipeline(),
        decoder=MockDecoder(),
        safety=MockSafety(),
    )

    bridge.start()
    assert hardware.started
    assert len(hardware.callbacks) == 1
    assert hardware.callbacks[0] == bridge._on_neuro_frame

    bridge.stop()
    assert hardware.stopped


def test_bridge_wires_pipeline_decoder_safety_and_injection():
    bridge, mocks = _make_bridge()
    frame = _sample_frame()

    bridge._on_neuro_frame(frame)

    assert len(mocks["pipeline"].calls) == 1
    assert mocks["pipeline"].calls[0] is frame

    assert len(mocks["decoder"].calls) == 1
    assert mocks["decoder"].calls[0] == {"mock_features": True, "timestamp": 1234.5}

    assert len(mocks["safety"].calls) == 1
    assert mocks["safety"].calls[0].attention_focus == "focused_executive"

    injected = [e for e in mocks["event_bus"].events if e["type"] == "bci_state_injected"]
    assert len(injected) == 1


def test_injection_happens_when_allowed():
    bridge, mocks = _make_bridge(action="allow")
    bridge._on_neuro_frame(_sample_frame())

    assert len(mocks["attention"].calls) == 1
    assert len(mocks["needs"].calls) == 1
    assert len(mocks["emotion"].calls) == 1
    assert len(mocks["conscious"].calls) == 1
    assert len(mocks["world_model"].calls) == 1

    injected = [e for e in mocks["event_bus"].events if e["type"] == "bci_state_injected"]
    assert len(injected) == 1

    blocked = [e for e in mocks["event_bus"].events if e["type"] == "bci_state_blocked"]
    assert len(blocked) == 0


def test_injection_skipped_when_blocked():
    bridge, mocks = _make_bridge(action="block")
    bridge._on_neuro_frame(_sample_frame())

    assert len(mocks["attention"].calls) == 0
    assert len(mocks["needs"].calls) == 0
    assert len(mocks["emotion"].calls) == 0
    assert len(mocks["conscious"].calls) == 0
    assert len(mocks["world_model"].calls) == 0

    injected = [e for e in mocks["event_bus"].events if e["type"] == "bci_state_injected"]
    assert len(injected) == 0

    blocked = [e for e in mocks["event_bus"].events if e["type"] == "bci_state_blocked"]
    assert len(blocked) == 1


def test_attention_engine_receives_boost():
    bridge, mocks = _make_bridge(focus="focused_executive")
    bridge._on_neuro_frame(_sample_frame())

    assert len(mocks["attention"].calls) == 1
    call = mocks["attention"].calls[0]
    assert call["target"] == "current_task"
    assert call["source"] == "bci_focus"
    assert call["weight"] == pytest.approx(0.8)


def test_needs_system_receives_energy_estimate():
    bridge, mocks = _make_bridge(load=0.8)
    bridge._on_neuro_frame(_sample_frame())

    assert len(mocks["needs"].calls) == 1
    call = mocks["needs"].calls[0]
    assert call["need_type"] is NeedType.ENERGY
    assert call["deficit"] == pytest.approx(min(0.8 * 0.5, 1.0))
    assert call["confidence"] == pytest.approx(0.75)


def test_emotion_system_receives_vad():
    bridge, mocks = _make_bridge()
    bridge._on_neuro_frame(_sample_frame())

    assert len(mocks["emotion"].calls) == 1
    call = mocks["emotion"].calls[0]
    assert call["valence"] == pytest.approx(0.2)
    assert call["arousal"] == pytest.approx(0.6)
    assert call["dominance"] == pytest.approx(0.5)
    assert call["source"] == "bci_neuro"
    assert call["confidence"] == pytest.approx(0.75)


def test_conscious_stream_receives_interoception():
    bridge, mocks = _make_bridge(focus="focused_executive", load=0.8)
    bridge._on_neuro_frame(_sample_frame())

    assert len(mocks["conscious"].calls) == 1
    call = mocks["conscious"].calls[0]
    assert "focused_executive" in call["content"]
    assert "0.80" in call["content"] or "0.8" in call["content"]
    assert call["valence"] == pytest.approx(0.2)
    assert call["intensity"] == pytest.approx(0.6)


def test_world_model_receives_user_cognitive_state():
    bridge, mocks = _make_bridge(load=0.8)
    bridge._on_neuro_frame(_sample_frame())

    assert len(mocks["world_model"].calls) == 1
    call = mocks["world_model"].calls[0]
    assert call["eid"] == "user_cognitive_state"
    props = call["properties"]
    assert props["attention_focus"] == "focused_executive"
    assert props["cognitive_load"] == pytest.approx(0.8)
    assert props["emotion_valence"] == pytest.approx(0.2)
    assert call["source"] == "bci_decoder"
    assert call["confidence"] == pytest.approx(0.7)


def test_event_bus_publishes_injected_state():
    bridge, mocks = _make_bridge()
    bridge._on_neuro_frame(_sample_frame())

    injected = [e for e in mocks["event_bus"].events if e["type"] == "bci_state_injected"]
    assert len(injected) == 1
    assert injected[0]["source"] == "bci_bridge"
    assert injected[0]["data"] == asdict(bridge.get_current_cognitive_state())


def test_get_current_cognitive_state_returns_last_state():
    bridge, mocks = _make_bridge()
    frame1 = NeuroDataFrame(timestamp=1.0, eeg=np.zeros((16, 250)))
    frame2 = NeuroDataFrame(timestamp=2.0, eeg=np.zeros((16, 250)))

    bridge._on_neuro_frame(frame1)
    first = bridge.get_current_cognitive_state()
    assert first is not None
    assert first.timestamp == 1.0

    bridge._on_neuro_frame(frame2)
    second = bridge.get_current_cognitive_state()
    assert second is not None
    assert second.timestamp == 2.0
    assert first is not second


def test_warn_proceeds_with_attenuation():
    bridge, mocks = _make_bridge(action="warn", attenuate=0.5)
    bridge._on_neuro_frame(_sample_frame())

    assert len(mocks["attention"].calls) == 1
    assert mocks["attention"].calls[0]["weight"] == pytest.approx(0.4)

    assert mocks["needs"].calls[0]["confidence"] == pytest.approx(0.375)
    assert mocks["emotion"].calls[0]["confidence"] == pytest.approx(0.375)
    assert mocks["conscious"].calls[0]["intensity"] == pytest.approx(0.3)
    assert mocks["world_model"].calls[0]["confidence"] == pytest.approx(0.35)


def test_optional_modules_are_skipped_when_none():
    hardware = MockHardware()
    pipeline = MockPipeline()
    decoder = MockDecoder()
    safety = MockSafety()
    event_bus = MockEventBus()

    bridge = BCICognitiveBridge(
        hardware=hardware,
        pipeline=pipeline,
        decoder=decoder,
        safety=safety,
        event_bus=event_bus,
    )

    # Should not raise even though attention/needs/emotion etc. are None.
    bridge._on_neuro_frame(_sample_frame())

    injected = [e for e in event_bus.events if e["type"] == "bci_state_injected"]
    assert len(injected) == 1
