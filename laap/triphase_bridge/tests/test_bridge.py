"""Triphase Bridge 单元测试。"""

from __future__ import annotations

import pytest
import numpy as np

from laap.events.bus import EventBus
from laap.agi.cognitive_bus import CognitiveBus
from laap.triphase_bridge import (
    TextEncoder,
    TriphaseMemoryService,
    TriphaseGroundingService,
    TriphaseBridgeService,
    triphase_to_dict,
    dict_to_triphase,
    TritJSONCodec,
    PhaseStateJSONCodec,
    TriphaseTopic,
)
from triphase.core import Trit, PhaseState


# ---------------------------------------------------------------------- codec

class TestCodec:
    def test_trit_roundtrip(self):
        for trit in Trit:
            assert TritJSONCodec.decode(TritJSONCodec.encode(trit)) is trit

    def test_phase_state_roundtrip(self):
        state = PhaseState(magnitude=0.8, phase=1.2)
        encoded = PhaseStateJSONCodec.encode(state)
        decoded = PhaseStateJSONCodec.decode(encoded)
        assert decoded.magnitude == pytest.approx(state.magnitude)
        assert decoded.phase == pytest.approx(state.phase)

    def test_dict_to_triphase(self):
        assert dict_to_triphase("POS", Trit) is Trit.POS
        data = {"magnitude": 0.5, "phase": 0.7}
        s = dict_to_triphase(data, PhaseState)
        assert s.magnitude == pytest.approx(0.5)


# ---------------------------------------------------------------------- encoder

class TestTextEncoder:
    def test_deterministic(self):
        enc = TextEncoder(dim=64)
        v1 = enc.encode("hello world")
        v2 = enc.encode("hello world")
        assert np.allclose(v1, v2)

    def test_normalization(self):
        enc = TextEncoder(dim=64)
        v = enc.encode("LAAP triphase bridge")
        assert abs(np.linalg.norm(v) - 1.0) < 1e-5

    def test_empty_text(self):
        enc = TextEncoder(dim=64)
        v = enc.encode("")
        assert np.linalg.norm(v) == 0.0

    def test_similarity_consistency(self):
        enc = TextEncoder(dim=64)
        a = enc.encode("machine learning")
        b = enc.encode("machine learning")
        assert enc.cosine_similarity(a, b) > 0.99


# ---------------------------------------------------------------------- memory service

class TestMemoryService:
    def test_store_and_retrieve(self):
        events = []
        svc = TriphaseMemoryService(
            encoder=TextEncoder(dim=32),
            on_event=lambda topic, payload: events.append((topic, payload)),
        )
        svc.store(
            "用户喜欢深色主题",
            key="pref-theme",
            initial_evidence=0.5,
            payload={"category": "ui_preference"},
        )
        results = svc.retrieve("用户偏好主题")
        assert len(results) > 0
        assert results[0]["item"]["payload"]["text"] == "用户喜欢深色主题"

    def test_negative_memory_warns(self):
        svc = TriphaseMemoryService(encoder=TextEncoder(dim=32))
        svc.store(
            "方案 X 已被证伪",
            key="bad-x",
            initial_evidence=-0.9,
        )
        warns = svc.warnings("我们要试试方案 X")
        assert len(warns) > 0
        assert "方案 X" in warns[0]

    def test_consolidation_event(self):
        events = []
        svc = TriphaseMemoryService(
            encoder=TextEncoder(dim=32),
            on_event=lambda topic, payload: events.append((topic, payload)),
        )
        svc.store("某事实", key="fact-1", initial_evidence=0.1)
        svc.consolidate("fact-1", 0.9)
        assert any(t == TriphaseTopic.MEMORY_CONSOLIDATED for t, _ in events)


# ---------------------------------------------------------------------- grounding service

class TestGroundingService:
    def test_biomedical_dose_pass(self):
        mem = TriphaseMemoryService(encoder=TextEncoder(dim=32))
        grd = TriphaseGroundingService(memory_service=mem, default_domain="biomedical")
        report = grd.verify(
            "华法林 5mg 剂量安全",
            kind="numeric",
            slots={"drug": "华法林", "dose_mg": 5.0, "unit": "mg"},
        )
        assert report["action"] == "pass"

    def test_biomedical_dose_reject(self):
        mem = TriphaseMemoryService(encoder=TextEncoder(dim=32))
        grd = TriphaseGroundingService(memory_service=mem, default_domain="biomedical")
        report = grd.verify(
            "华法林 50mg 剂量安全",
            kind="numeric",
            slots={"drug": "华法林", "dose_mg": 50.0, "unit": "mg"},
        )
        assert report["action"] == "reject"
        assert any(v["trit"] == "NEG" for v in report["verdicts"])

    def test_antibody_fastpath(self):
        mem = TriphaseMemoryService(encoder=TextEncoder(dim=32))
        grd = TriphaseGroundingService(memory_service=mem, default_domain="biomedical")
        # 先沉淀一个幻觉抗体（PoC 用 hash 向量，精确键命中需要文本相同）
        hallucination_text = "阿司匹林可以和华法林安全联用"
        grd.record_hallucination(
            hallucination_text,
            kind="fact",
            slots={"drugs": ["阿司匹林", "华法林"]},
        )
        # 再验证同文本声明，触发精确键抗体快路径
        report = grd.verify(
            hallucination_text,
            kind="fact",
            slots={"drugs": ["阿司匹林", "华法林"], "asserts": "no_interaction"},
        )
        assert report["action"] == "reject"
        assert len(report["antibody_hits"]) > 0


# ---------------------------------------------------------------------- bridge service

class TestBridgeService:
    def test_start_stop(self):
        bus = EventBus()
        cog = CognitiveBus(agent_name="test")
        svc = TriphaseBridgeService(event_bus=bus, cognitive_bus=cog)
        svc.start()
        assert svc.status()["started"] is True
        assert "triphase_bridge" in cog.get_online_modules()
        svc.stop()
        assert svc.status()["started"] is False

    def test_user_input_emits_memory_retrieved(self):
        bus = EventBus()
        cog = CognitiveBus(agent_name="test")
        svc = TriphaseBridgeService(event_bus=bus, cognitive_bus=cog)
        svc.start()
        svc.store_memory("LAAP 使用 WebSocket 事件总线", tags=["architecture"])

        received = []
        bus.subscribe(TriphaseTopic.MEMORY_RETRIEVED, lambda e: received.append(e))
        bus.publish_simple("user.input", {"text": "LAAP 怎么通信"})

        assert any(e.type == TriphaseTopic.MEMORY_RETRIEVED for e in received)

    def test_grounding_verify_event(self):
        bus = EventBus()
        cog = CognitiveBus(agent_name="test")
        svc = TriphaseBridgeService(event_bus=bus, cognitive_bus=cog)
        svc.start()

        received = []
        bus.subscribe(TriphaseTopic.GROUNDING_REPORT, lambda e: received.append(e))
        bus.publish_simple(
            "triphase.grounding.verify",
            {
                "text": "华法林 50mg 安全",
                "domain": "biomedical",
                "kind": "numeric",
                "slots": {"drug": "华法林", "dose_mg": 50.0, "unit": "mg"},
            },
        )

        assert len(received) == 1
        assert received[0].data["action"] == "reject"

    def test_status(self):
        svc = TriphaseBridgeService(
            event_bus=EventBus(),
            cognitive_bus=CognitiveBus(agent_name="test"),
        )
        status = svc.status()
        assert "memory" in status
        assert "grounding" in status
        assert "data_dir" in status
