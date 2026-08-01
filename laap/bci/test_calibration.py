"""Unit tests for ``laap.bci.calibration.BCICalibrationEngine``."""

from __future__ import annotations

import pytest

from laap.bci.calibration import BCICalibrationEngine
from laap.bci.decoder import CognitiveStateDecoder
from laap.bci.hardware import MockNeuroGenerator
from laap.bci.pipeline import RealtimeNeuroPipeline


@pytest.fixture
def pipeline() -> RealtimeNeuroPipeline:
    return RealtimeNeuroPipeline(sfreq=250.0, n_channels=16)


@pytest.fixture
def generator() -> MockNeuroGenerator:
    return MockNeuroGenerator(sfreq=250.0, n_channels=16, scenario="focused_coding")


def test_run_calibration_protocol_returns_profile_with_required_keys(
    pipeline: RealtimeNeuroPipeline,
    generator: MockNeuroGenerator,
    tmp_path,
):
    engine = BCICalibrationEngine(pipeline=pipeline, output_dir=str(tmp_path))
    profile = engine.run_calibration_protocol(user_id="test_user", mock_generator=generator)

    assert isinstance(profile, dict)
    assert profile["user_id"] == "test_user"
    assert "created_at" in profile
    assert "baseline_band_powers" in profile
    assert set(profile["baseline_band_powers"].keys()) == {"delta", "theta", "alpha", "beta", "gamma"}

    assert "attention_thresholds" in profile
    assert set(profile["attention_thresholds"].keys()) == {"high", "medium"}
    assert profile["attention_thresholds"]["high"] >= profile["attention_thresholds"]["medium"]

    assert "load_baseline" in profile
    assert isinstance(profile["load_baseline"], float)

    assert "valence_scale" in profile
    assert isinstance(profile["valence_scale"], float)

    metadata = profile.get("metadata", {})
    assert metadata.get("baseline_windows") == 120
    assert metadata.get("oddball_windows") == 120
    assert metadata.get("oddball_markers") == 12
    assert metadata.get("positive_windows") == 30
    assert metadata.get("negative_windows") == 30


def test_save_profile_and_load_profile_round_trip(
    pipeline: RealtimeNeuroPipeline,
    generator: MockNeuroGenerator,
    tmp_path,
):
    output_dir = tmp_path / "bci_profiles"
    engine = BCICalibrationEngine(pipeline=pipeline, output_dir=str(output_dir))

    profile = engine.run_calibration_protocol(user_id="roundtrip_user", mock_generator=generator)
    engine.save_profile("roundtrip_user", profile)

    loaded = engine.load_profile("roundtrip_user")
    assert loaded is not None
    assert loaded["user_id"] == "roundtrip_user"
    assert loaded["baseline_band_powers"] == profile["baseline_band_powers"]
    assert loaded["attention_thresholds"] == profile["attention_thresholds"]
    assert loaded["load_baseline"] == profile["load_baseline"]
    assert loaded["valence_scale"] == profile["valence_scale"]


def test_load_profile_returns_none_for_missing_user(
    pipeline: RealtimeNeuroPipeline,
    tmp_path,
):
    engine = BCICalibrationEngine(pipeline=pipeline, output_dir=str(tmp_path))
    assert engine.load_profile("missing_user") is None


def test_apply_to_decoder_updates_decoder_thresholds(
    pipeline: RealtimeNeuroPipeline,
    generator: MockNeuroGenerator,
    tmp_path,
):
    output_dir = tmp_path / "bci_profiles"
    engine = BCICalibrationEngine(pipeline=pipeline, output_dir=str(output_dir))

    profile = engine.run_calibration_protocol(user_id="decoder_user", mock_generator=generator)
    engine.save_profile("decoder_user", profile)

    decoder = CognitiveStateDecoder(sfreq=250.0)
    original_high = decoder.attention_focused_executive_threshold
    original_medium = decoder.attention_selective_attention_threshold
    original_load_offset = decoder.cognitive_load_offset

    applied = engine.apply_to_decoder(decoder, "decoder_user")
    assert applied is True

    assert decoder.attention_focused_executive_threshold == pytest.approx(
        profile["attention_thresholds"]["high"]
    )
    assert decoder.attention_selective_attention_threshold == pytest.approx(
        profile["attention_thresholds"]["medium"]
    )
    assert decoder.cognitive_load_offset == pytest.approx(profile["load_baseline"])

    # Thresholds should have changed from their defaults
    assert decoder.attention_focused_executive_threshold != original_high
    assert decoder.attention_selective_attention_threshold != original_medium
    assert decoder.cognitive_load_offset != original_load_offset


def test_apply_to_decoder_returns_false_when_profile_missing(
    pipeline: RealtimeNeuroPipeline,
    tmp_path,
):
    engine = BCICalibrationEngine(pipeline=pipeline, output_dir=str(tmp_path))
    decoder = CognitiveStateDecoder(sfreq=250.0)
    assert engine.apply_to_decoder(decoder, "no_such_user") is False
