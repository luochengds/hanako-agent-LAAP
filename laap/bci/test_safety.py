"""Unit tests for the BCI neuro-safety layer."""

import json

import pytest

from laap.bci.primitives import CognitiveState
from laap.bci.safety import BCISecurityLayer


def _state(
    snr: float = 10.0,
    valence: float = 0.0,
    arousal: float = 0.0,
    load: float = 0.5,
    focus: str = "work",
) -> CognitiveState:
    return CognitiveState(
        attention_focus=focus,
        cognitive_load=load,
        emotion_vad={"valence": valence, "arousal": arousal, "dominance": 0.0},
        signal_quality={"overall_snr": snr},
        timestamp=0.0,
    )


def test_poor_snr_blocks(tmp_path):
    log = tmp_path / "audit.log"
    layer = BCISecurityLayer(audit_log_path=str(log))
    state = _state(snr=1.0)

    result = layer.scan_neuro_injection(state)

    assert result["action"] == "block"
    assert result["reason"] == "poor_signal_quality"
    assert result["attenuate"] == 0.0


def test_normal_snr_allows(tmp_path):
    log = tmp_path / "audit.log"
    layer = BCISecurityLayer(audit_log_path=str(log))
    state = _state(snr=10.0, valence=0.1, arousal=0.1, load=0.5)

    result = layer.scan_neuro_injection(state)

    assert result["action"] == "allow"
    assert result["reason"] == "ok"
    assert result["attenuate"] == 1.0


def test_extreme_valence_warns(tmp_path):
    log = tmp_path / "audit.log"
    layer = BCISecurityLayer(audit_log_path=str(log))
    state = _state(snr=10.0, valence=0.99)

    result = layer.scan_neuro_injection(state)

    assert result["action"] == "warn"
    assert result["reason"] == "extreme_emotional_state"
    assert result["attenuate"] == 0.5


def test_state_anomaly_warns(tmp_path):
    log = tmp_path / "audit.log"
    layer = BCISecurityLayer(audit_log_path=str(log))

    # Establish a stable baseline.
    for _ in range(3):
        layer.scan_neuro_injection(_state(snr=10.0, valence=0.1, arousal=0.1, load=0.5))

    # Inject a large outlier.
    outlier = _state(snr=10.0, valence=0.9, arousal=0.9, load=0.9)
    result = layer.scan_neuro_injection(outlier)

    assert result["action"] == "warn"
    assert result["reason"] == "state_anomaly_detected"
    assert result["attenuate"] == 0.5


def test_audit_log_file_is_written(tmp_path):
    log = tmp_path / "audit.log"
    layer = BCISecurityLayer(audit_log_path=str(log))
    state = _state(snr=1.0)

    layer.scan_neuro_injection(state)

    assert log.exists()
    lines = log.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) >= 1
    record = json.loads(lines[-1])
    assert "timestamp" in record
    assert record["action"] == "block"
    assert record["reason"] == "poor_signal_quality"
    assert "state" in record
