"""BCI calibration engine for personalising cognitive-state thresholds.

The engine runs a short, scenario-driven protocol on a ``MockNeuroGenerator``,
extracts features via ``RealtimeNeuroPipeline.process_window``, and derives
per-user thresholds that can be applied to a ``CognitiveStateDecoder``.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional

import numpy as np

from laap.bci.decoder import CognitiveStateDecoder
from laap.bci.hardware import MockNeuroGenerator
from laap.bci.pipeline import RealtimeNeuroPipeline
from laap.bci.primitives import NeuroDataFrame
from laap.config.paths import get_state_dir

_DEFAULT_OUTPUT_DIR = str(get_state_dir() / "bci_calibration")


class BCICalibrationEngine:
    """Personalised calibration workflow for the BCI Neuro Bridge."""

    def __init__(self, pipeline: RealtimeNeuroPipeline, output_dir: str = None):
        self.pipeline = pipeline
        self.output_dir = output_dir if output_dir is not None else _DEFAULT_OUTPUT_DIR

    def _collect_features(
        self,
        generator: MockNeuroGenerator,
        scenario: str,
        duration_sec: int,
        marker_every: Optional[int] = None,
        marker: str = "marker",
    ) -> List[Dict]:
        """Generate synthetic windows, convert them to frames, and process them."""
        generator.scenario = scenario
        features: List[Dict] = []
        for i in range(duration_sec):
            eeg = generator.generate_window(duration_sec=1.0)
            frame_marker = marker if marker_every is not None and i % marker_every == 0 else None
            frame = NeuroDataFrame(
                timestamp=time.time(),
                eeg=eeg,
                marker=frame_marker,
            )
            feature = self.pipeline.process_window(frame)
            feature["marker"] = frame_marker
            features.append(feature)
        return features

    @staticmethod
    def _mean_band_power(feature: Dict, band: str) -> float:
        """Return the mean power of ``band`` across channels for one feature window."""
        powers = feature.get("band_powers", {}).get(band)
        if powers is None:
            return 0.0
        return float(np.mean(np.asarray(powers, dtype=np.float64)))

    @staticmethod
    def _ratios(features: List[Dict], numerator_band: str, denominator_band: str) -> List[float]:
        """Compute per-window ratios of two band powers."""
        ratios = []
        for feature in features:
            num = BCICalibrationEngine._mean_band_power(feature, numerator_band)
            den = BCICalibrationEngine._mean_band_power(feature, denominator_band)
            ratios.append(num / (den + 1e-12))
        return ratios

    @staticmethod
    def _frontal_asymmetries(features: List[Dict]) -> List[float]:
        """Extract frontal asymmetry values from a list of feature dicts."""
        return [float(f.get("spatial", {}).get("frontal_asymmetry", 0.0)) for f in features]

    def run_calibration_protocol(
        self,
        user_id: str,
        mock_generator: MockNeuroGenerator,
    ) -> Dict:
        """Run the three-phase calibration protocol and return a profile dict.

        The protocol consists of:

        1. Eyes-closed baseline (2 min) using the ``meditation`` scenario.
        2. P300 oddball task (2 min) using the ``focused_coding`` scenario with
           occasional ``oddball`` markers.
        3. Emotion induction (1 min) alternating between positive
           (``creative_flow``) and negative (``stress_debug``) scenarios.
        """
        # Phase 1: eyes-closed baseline
        baseline_features = self._collect_features(
            mock_generator, "meditation", duration_sec=120
        )

        # Phase 2: P300 oddball task
        oddball_features = self._collect_features(
            mock_generator,
            "focused_coding",
            duration_sec=120,
            marker_every=10,
            marker="oddball",
        )

        # Phase 3: emotion induction (alternating positive / negative blocks)
        block_duration = 10  # seconds
        positive_features: List[Dict] = []
        negative_features: List[Dict] = []
        for block_idx in range(6):
            if block_idx % 2 == 0:
                positive_features.extend(
                    self._collect_features(
                        mock_generator, "creative_flow", duration_sec=block_duration
                    )
                )
            else:
                negative_features.extend(
                    self._collect_features(
                        mock_generator, "stress_debug", duration_sec=block_duration
                    )
                )

        # Baseline statistics
        gamma_alpha_ratios = np.asarray(
            self._ratios(baseline_features, "gamma", "alpha"), dtype=np.float64
        )
        theta_alpha_ratios = np.asarray(
            self._ratios(baseline_features, "theta", "alpha"), dtype=np.float64
        )

        baseline_mean_ga = float(np.mean(gamma_alpha_ratios))
        baseline_std_ga = float(np.std(gamma_alpha_ratios))
        baseline_mean_ta = float(np.mean(theta_alpha_ratios))

        baseline_band_powers = {}
        for band in self.pipeline.bands:
            values = [self._mean_band_power(f, band) for f in baseline_features]
            baseline_band_powers[band] = float(np.mean(values))

        # Valence scale derived from frontal asymmetry during emotion induction
        pos_asym = np.asarray(self._frontal_asymmetries(positive_features), dtype=np.float64)
        neg_asym = np.asarray(self._frontal_asymmetries(negative_features), dtype=np.float64)
        mean_pos = float(np.mean(pos_asym)) if pos_asym.size else 0.0
        mean_neg = float(np.mean(neg_asym)) if neg_asym.size else 0.0
        valence_scale = float(np.clip(mean_pos - mean_neg, -1.0, 1.0))

        # Capture oddball marker statistics (useful for downstream P300 tuning)
        oddball_count = sum(1 for f in oddball_features if f.get("marker") == "oddball")

        profile = {
            "user_id": user_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "baseline_band_powers": baseline_band_powers,
            "attention_thresholds": {
                "high": baseline_mean_ga + 1.0 * baseline_std_ga,
                "medium": baseline_mean_ga + 0.5 * baseline_std_ga,
            },
            "load_baseline": baseline_mean_ta,
            "valence_scale": valence_scale,
            "metadata": {
                "baseline_windows": len(baseline_features),
                "oddball_windows": len(oddball_features),
                "oddball_markers": oddball_count,
                "positive_windows": len(positive_features),
                "negative_windows": len(negative_features),
            },
        }
        return profile

    def _profile_path(self, user_id: str) -> str:
        """Return the on-disk path for ``user_id``'s profile."""
        return os.path.join(self.output_dir, f"{user_id}_bci_profile.json")

    def save_profile(self, user_id: str, profile: Dict) -> None:
        """Persist ``profile`` to ``output_dir/{user_id}_bci_profile.json``."""
        os.makedirs(self.output_dir, exist_ok=True)
        path = self._profile_path(user_id)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(profile, fh, indent=2, ensure_ascii=False)

    def load_profile(self, user_id: str) -> Optional[Dict]:
        """Load a previously saved profile, or ``None`` if it does not exist."""
        path = self._profile_path(user_id)
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)

    def apply_to_decoder(self, decoder: CognitiveStateDecoder, user_id: str) -> bool:
        """Load ``user_id``'s profile and update ``decoder`` thresholds.

        Returns ``True`` when a profile was found and applied, ``False`` otherwise.
        """
        profile = self.load_profile(user_id)
        if profile is None:
            return False

        attention_thresholds = profile.get("attention_thresholds", {})
        decoder.attention_focused_executive_threshold = float(
            attention_thresholds.get("high", decoder.attention_focused_executive_threshold)
        )
        decoder.attention_selective_attention_threshold = float(
            attention_thresholds.get("medium", decoder.attention_selective_attention_threshold)
        )
        decoder.cognitive_load_offset = float(
            profile.get("load_baseline", decoder.cognitive_load_offset)
        )
        return True
