"""Hallucination guard — three-layer hallucination mitigation framework.

Architecture
────────────
  Pre-generation layer (decision gate):
    Quantum cognition stats → confidence threshold → reject/accept generation
    Uncertainty → temperature ceiling modulation
    Cognitive entropy → prompt prefix injection (e.g., "I need to clarify")

  In-generation layer (parameter modulation):
    Kalman uncertainty → temperature upper bound
    Spectral coherence → top_p range
    Occam complexity → max_tokens cap

  Post-generation layer (validation):
    Text coherence scan → contradiction detection
    Response length vs stimulus entropy → verbosity check
    Cognitive state alignment → confidence overlay

Usage
─────
    guard = HallucinationGuard()
    
    # Pre-generation check
    decision = guard.pre_gate(quantum_stats)
    if decision.action == 'reject':
        return decision.safe_response
    
    # In-generation modulation
    params = guard.modulate_params(quantum_stats)
    response = llm.generate(prompt, **params)
    
    # Post-generation validation
    result = guard.validate(response, stimulus, quantum_stats)
    if result.needs_caveat:
        response = result.annotated_response
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger('quantum_cognition.hallucination_guard')


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class GuardConfig:
    """Configuration for the hallucination guard.

    Parameters
    ----------
    confidence_min : float
        Minimum Kalman confidence for unconditional generation.
        Below this, the guard may reject or add a caveat.
    confidence_hard_floor : float
        Absolute minimum. Below this, generation is rejected outright.
        The engine says "I need more information" instead.
    uncertainty_max : float
        Maximum allowed total uncertainty (trace of P matrix).
    temperature_min : float
        Minimum temperature to use (even when confident).
    temperature_max : float
        Maximum temperature when uncertainty is high.
    top_p_default : float
        Default top_p for nucleus sampling.
    top_p_range : float
        Range of top_p modulation (default ±0.1).
    max_tokens_base : int
        Base max_tokens for generation.
    max_tokens_min : int
        Minimum max_tokens (when coherence is very low).
    enable_pre_gate : bool
        Enable pre-generation rejection gate.
    enable_post_validation : bool
        Enable post-generation coherence validation.
    enable_temperature_modulation : bool
        Enable in-generation temperature modulation.
    contradiction_patterns : List[Tuple[str, str]]
        Pairs of contradictory patterns to scan for in responses.
    name : str
        Human-readable identifier for logging.
    """
    confidence_min: float = 0.35
    confidence_hard_floor: float = 0.15
    uncertainty_max: float = 2.0
    temperature_min: float = 0.3
    temperature_max: float = 0.9
    top_p_default: float = 0.9
    top_p_range: float = 0.15
    max_tokens_base: int = 2048
    max_tokens_min: int = 512
    enable_pre_gate: bool = True
    enable_post_validation: bool = True
    enable_temperature_modulation: bool = True
    contradiction_patterns: List[Tuple[str, str]] = field(default_factory=lambda: [
        (r'\b(是|yes|对|correct|right)\b', r'\b(不|no|wrong|incorrect)\b'),
        (r'\b(一定|必然|绝对|always|never)\b', r'\b(可能|也许|maybe|perhaps)\b'),
    ])
    safe_rejection_response: str = (
        "I need a bit more context to give you a confident answer. "
        "Could you clarify what you're looking for?"
    )
    name: str = "hallucination_guard"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class PreGateDecision:
    """Result of the pre-generation gate check.

    Parameters
    ----------
    action : str
        'generate', 'reject', or 'caveat'
    safe_response : str
        Response when action is 'reject'.
    confidence : float
        Current cognitive confidence.
    uncertainty : float
        Current cognitive uncertainty.
    reason : str
        Human-readable reason for the decision.
    """
    action: str = 'generate'
    safe_response: str = ''
    confidence: float = 0.5
    uncertainty: float = 0.0
    reason: str = 'pass'


@dataclass
class ModulatedParams:
    """LLM generation parameters modulated by cognitive state.

    Parameters
    ----------
    temperature : float
        Temperature for generation.
    top_p : float
        Nucleus sampling threshold.
    max_tokens : int
        Maximum tokens to generate.
    system_prefix : str
        Additional system prompt prefix for this turn.
    """
    temperature: float = 0.7
    top_p: float = 0.9
    max_tokens: int = 2048
    system_prefix: str = ''


@dataclass
class ValidationResult:
    """Result of post-generation validation.

    Parameters
    ----------
    is_valid : bool
        Whether the response passes all validation checks.
    needs_caveat : bool
        Whether a caveat should be appended.
    confidence_delta : float
        Adjustment to cognitive confidence based on validation.
    caveat_text : str
        Text to append (disclaimer, uncertainty marker).
    annotated_response : str
        Response with caveat appended if needed.
    issues : List[str]
        List of detected issues for logging.
    """
    is_valid: bool = True
    needs_caveat: bool = False
    confidence_delta: float = 0.0
    caveat_text: str = ''
    annotated_response: str = ''
    issues: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# HallucinationGuard
# ---------------------------------------------------------------------------

class HallucinationGuard:
    """Three-layer hallucination mitigation for LLM-generated responses.

    Does NOT modify the LLM internally. Operates as a cognitive wrapper:
      pre-generation → modulation → generation → validation

    Parameters
    ----------
    config : GuardConfig, optional
    """

    def __init__(self, config: Optional[GuardConfig] = None):
        self.cfg = config or GuardConfig()
        self._gate_count: int = 0
        self._rejection_count: int = 0
        self._caveat_count: int = 0

    # ── Pre-generation gate ──────────────────────────────────────────

    def pre_gate(self, quantum_stats: Dict[str, float]) -> PreGateDecision:
        """Pre-generation gate: decide whether to generate, reject, or caveat.

        Parameters
        ----------
        quantum_stats : dict
            Output from ``PsiQuantumCognition.get_stats()``.  Must contain
            'confidence' and 'uncertainty' keys.

        Returns
        -------
        PreGateDecision
        """
        self._gate_count += 1

        if not self.cfg.enable_pre_gate:
            return PreGateDecision(action='generate', confidence=0.5)

        confidence = quantum_stats.get('confidence', 0.5)
        uncertainty = quantum_stats.get('uncertainty', 0.5)
        entropy = quantum_stats.get('quantum_entropy', 0.5)

        # Hard floor: outright rejection
        if confidence < self.cfg.confidence_hard_floor:
            self._rejection_count += 1
            logger.info(
                f"[guard] REJECT: confidence={confidence:.3f} < "
                f"floor={self.cfg.confidence_hard_floor}"
            )
            return PreGateDecision(
                action='reject',
                safe_response=self.cfg.safe_rejection_response,
                confidence=confidence,
                uncertainty=uncertainty,
                reason=f'confidence {confidence:.3f} below hard floor',
            )

        # Soft boundary: caveat
        if confidence < self.cfg.confidence_min:
            self._caveat_count += 1
            logger.info(
                f"[guard] CAVEAT: confidence={confidence:.3f} < "
                f"min={self.cfg.confidence_min}"
            )
            return PreGateDecision(
                action='caveat',
                confidence=confidence,
                uncertainty=uncertainty,
                reason=f'confidence {confidence:.3f} below soft threshold',
            )

        # High uncertainty: reject
        if uncertainty > self.cfg.uncertainty_max:
            self._rejection_count += 1
            logger.info(
                f"[guard] REJECT: uncertainty={uncertainty:.3f} > "
                f"max={self.cfg.uncertainty_max}"
            )
            return PreGateDecision(
                action='reject',
                safe_response=self.cfg.safe_rejection_response,
                confidence=confidence,
                uncertainty=uncertainty,
                reason=f'uncertainty {uncertainty:.3f} above max',
            )

        # High entropy: cautious generation
        if entropy > 0.3:
            return PreGateDecision(
                action='caveat',
                confidence=confidence,
                uncertainty=uncertainty,
                reason=f'high entropy {entropy:.3f}',
            )

        return PreGateDecision(
            action='generate',
            confidence=confidence,
            uncertainty=uncertainty,
            reason='pass',
        )

    # ── In-generation parameter modulation ──────────────────────────

    def modulate_params(self, quantum_stats: Dict[str, float]) -> ModulatedParams:
        """Modulate LLM generation parameters based on cognitive state.

        Parameters
        ----------
        quantum_stats : dict

        Returns
        -------
        ModulatedParams
        """
        if not self.cfg.enable_temperature_modulation:
            return ModulatedParams()

        confidence = quantum_stats.get('confidence', 0.5)
        uncertainty = quantum_stats.get('uncertainty', 0.5)
        coherence = quantum_stats.get('spectral_coherence', 0.5)
        entropy = quantum_stats.get('quantum_entropy', 0.0)

        # Temperature: inverse of confidence
        # confident (0.9) → low temperature (0.3)
        # uncertain (0.2) → high temperature (0.9)
        temp_range = self.cfg.temperature_max - self.cfg.temperature_min
        temperature = self.cfg.temperature_max - confidence * temp_range
        temperature = float(np.clip(temperature,
                                     self.cfg.temperature_min,
                                     self.cfg.temperature_max))

        # top_p: modulated by coherence
        # high coherence → tight sampling (less random)
        # low coherence → wider sampling (more exploration)
        top_p = self.cfg.top_p_default + (1.0 - coherence) * self.cfg.top_p_range
        top_p = float(np.clip(top_p, 0.7, 1.0))

        # max_tokens: cap based on uncertainty
        # high uncertainty → shorter generations
        max_tokens = int(self.cfg.max_tokens_base *
                         (1.0 - np.clip(uncertainty / 5.0, 0.0, 0.75)))

        # System prefix for caveat mode
        system_prefix = ''
        if entropy > 0.5:
            system_prefix = (
                "You are uncertain about this topic. "
                "Acknowledge uncertainty rather than guessing."
            )
        elif confidence < 0.5:
            system_prefix = (
                "Be cautious and avoid definitive statements "
                "unless you're highly confident."
            )

        return ModulatedParams(
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
            system_prefix=system_prefix,
        )

    # ── Post-generation validation ──────────────────────────────────

    def validate(self, response: str, stimulus: str,
                 quantum_stats: Dict[str, float]) -> ValidationResult:
        """Post-generation validation: check response for hallucination signals.

        Parameters
        ----------
        response : str
            The LLM-generated response.
        stimulus : str
            The original user input that triggered this response.
        quantum_stats : dict

        Returns
        -------
        ValidationResult
        """
        if not self.cfg.enable_post_validation or not response:
            return ValidationResult(
                is_valid=True,
                annotated_response=response,
            )

        issues: List[str] = []
        confidence_delta = 0.0

        # 1. Contradiction scan
        for pattern_a, pattern_b in self.cfg.contradiction_patterns:
            match_a = re.search(pattern_a, response, re.IGNORECASE)
            match_b = re.search(pattern_b, response, re.IGNORECASE)
            if match_a and match_b:
                # Check distance — close contradictions are suspicious
                pos_a = match_a.start()
                pos_b = match_b.start()
                if abs(pos_a - pos_b) < 200:
                    issues.append(
                        f"nearby contradiction: '{pattern_a}' vs '{pattern_b}'"
                    )
                    confidence_delta -= 0.1

        # 2. Verbosity check: very long response to short stimulus
        #    can indicate hallucinatory elaboration
        stimulus_words = len(stimulus.split())
        response_words = len(response.split())
        if response_words > 50 and stimulus_words < 5:
            ratio = response_words / max(stimulus_words, 1)
            if ratio > 15:
                issues.append(
                    f"verbosity: {response_words} words for "
                    f"{stimulus_words}-word stimulus (ratio={ratio:.0f})"
                )
                confidence_delta -= 0.05

        # 3. Cognitive state alignment
        coherence = quantum_stats.get('spectral_coherence', 0.5)
        if coherence < 0.3:
            issues.append(f"low coherence ({coherence:.2f})")
            confidence_delta -= 0.05

        # 4. Entropy-based content check
        entropy = quantum_stats.get('quantum_entropy', 0.0)
        if entropy > 0.5 and response_words > 30:
            issues.append(f"high entropy ({entropy:.2f}) with long response")
            confidence_delta -= 0.05

        needs_caveat = len(issues) > 0
        is_valid = len(issues) <= 1  # one minor issue is acceptable

        # Build caveat text
        caveat = ''
        if needs_caveat:
            if 'contradiction' in ' '.join(issues):
                caveat = (
                    "\n\n[Note: I've detected some potential inconsistency "
                    "in my response. Please verify critical information.]"
                )
            else:
                caveat = (
                    "\n\n[Note: I'm uncertain about parts of this response. "
                    "Let me know if you'd like me to elaborate.]"
                )

        annotated = response + caveat if caveat else response

        result = ValidationResult(
            is_valid=is_valid,
            needs_caveat=needs_caveat,
            confidence_delta=confidence_delta,
            caveat_text=caveat,
            annotated_response=annotated,
            issues=issues,
        )

        if issues:
            logger.info(
                f"[guard] validation issues: {issues}, "
                f"confidence_delta={confidence_delta:.2f}"
            )

        return result

    # ── Stats ───────────────────────────────────────────────────────

    def get_stats(self) -> dict:
        """Return guard statistics."""
        return {
            'total_gates': self._gate_count,
            'rejections': self._rejection_count,
            'caveats': self._caveat_count,
            'rejection_rate': (self._rejection_count / max(self._gate_count, 1)),
        }

    def __repr__(self) -> str:
        return (f"HallucinationGuard(gates={self._gate_count}, "
                f"reject={self._rejection_count}, "
                f"caveat={self._caveat_count})")
