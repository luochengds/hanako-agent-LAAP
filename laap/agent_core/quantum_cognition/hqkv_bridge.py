"""H-QKV bridge: inject quantum cognitive state into LLM generation context.

Implements the Hamiltonian-Query-Key-Value principle at the prompt level.
Instead of modifying attention weights directly (requires model-level access),
we inject the current quantum cognitive state as structured context that the
LLM can attend to during generation.

This is the **current feasible equivalent** of H-QKV:
  - Q' modulation         → cognitive state injected into system prompt
  - C coherence bias      → temperature/top_p modulation by uncertainty
  - uncertainty gate      → post-generation validation + caveat injection

Architecture (H-QKV prompt bridge):
┌──────────────────────────────────────────────────────────┐
│  Quantum Cognition Engine                                │
│    → |psi⟩ = exp(-iH·dt)·|psi₀⟩                         │
│    → confidence = Kalman.x[CONFIDENCE]                   │
│    → uncertainty = trace(Kalman.P)                       │
│    → coherence = Spectral.coherence                      │
│    → entropy = BornRule.entropy(|psi⟩)                   │
│    → mode = dominant cognitive mode                      │
└────────────────────┬─────────────────────────────────────┘
                     │
┌────────────────────▼─────────────────────────────────────┐
│  H-QKV Prompt Builder                                    │
│    → confidence > 0.7 → "You are confident. Be direct."  │
│    → confidence < 0.4 → "You are uncertain. Acknowledge."│
│    → mode = 'perceive' → "Focus on understanding input." │
│    → mode = 'integrate' → "Synthesize multiple views."    │
│    → entropy > 0.3 → "Consider alternatives."            │
└────────────────────┬─────────────────────────────────────┘
                     │ injected into system prompt
┌────────────────────▼─────────────────────────────────────┐
│  LLM Generation (with cognitive context)                  │
│    → temperature = f(uncertainty)                        │
│    → top_p = f(coherence)                                │
│    → response is modulated by cognitive state            │
└────────────────────┬─────────────────────────────────────┘
                     │
┌────────────────────▼─────────────────────────────────────┐
│  Post-Generation Validation                               │
│    → check consistency with cognitive state              │
│    → inject caveat if needed                             │
│    → learn from outcome                                  │
└──────────────────────────────────────────────────────────┘
"""

from __future__ import annotations

import logging
from typing import Dict, Optional

logger = logging.getLogger('quantum_cognition.hqkv_bridge')


# ---------------------------------------------------------------------------
# Cognitive state → prompt mapping
# ---------------------------------------------------------------------------

#: Mode-specific task descriptions injected into system prompt
MODE_PROMPTS: Dict[str, str] = {
    'perceive': (
        "Your current cognitive mode is PERCEIVE. "
        "Focus on understanding the input clearly before responding."
    ),
    'select': (
        "Your current cognitive mode is SELECT. "
        "You are weighing multiple possible responses. "
        "Choose the most appropriate one."
    ),
    'integrate': (
        "Your current cognitive mode is INTEGRATE. "
        "You are synthesizing information from multiple sources. "
        "Provide a coherent synthesis."
    ),
    'act': (
        "Your current cognitive mode is ACT. "
        "You are ready to respond decisively."
    ),
    'learn': (
        "Your current cognitive mode is LEARN. "
        "Reflect on the conversation and extract insights."
    ),
    'rest': (
        "Your current cognitive mode is REST. "
        "Keep responses brief and low-effort."
    ),
    'attention': (
        "Your current cognitive mode is ATTENTION. "
        "You are highly focused on a specific aspect. "
        "Maintain that focus in your response."
    ),
    'emotion': (
        "Your current cognitive mode is EMOTION. "
        "The conversation has emotional content. "
        "Respond with appropriate warmth."
    ),
    'meta': (
        "Your current cognitive mode is META. "
        "You are reflecting on your own cognition. "
        "Be introspective and analytical."
    ),
    'memory': (
        "Your current cognitive mode is MEMORY. "
        "You are retrieving past context. "
        "Reference relevant history."
    ),
}

#: Default prompt when mode is not recognized
DEFAULT_MODE_PROMPT = (
    "Respond naturally to the user's input."
)


# ---------------------------------------------------------------------------
# H_QKVBuilder
# ---------------------------------------------------------------------------

class H_QKVBuilder:
    """Builds H-QKV cognitive state prompts for LLM generation.

    This is the **prompt-level equivalent** of Hamiltonian-modulated
    attention.  It injects the current quantum cognitive state into the
    LLM's context window, achieving similar effects to Q' = exp(-iHτ)Q:

      High confidence + low entropy
        → LLM sees "You are confident. Be direct and decisive."
        → mimics Q' modulation toward focused attention

      Low confidence + high entropy
        → LLM sees "You are uncertain. Consider alternatives and
           acknowledge uncertainty."
        → mimics C coherence bias expansion

      Dominant cognitive mode
        → LLM sees mode-specific task framing
        → mimics |psi⟩ state projection onto attention heads
    """

    def build_cognitive_prefix(self, quantum_stats: Dict[str, float]) -> str:
        """Build a cognitive-state prefix to inject into the system prompt.

        Parameters
        ----------
        quantum_stats : dict
            Output from ``PsiQuantumCognition.get_stats()``.

        Returns
        -------
        str
            Cognitive prefix to append to the system prompt.
            Empty string if quantum_stats is empty or default state.
        """
        if not quantum_stats:
            return ''

        parts = []

        # 1. Mode-specific task framing
        mode = quantum_stats.get('most_likely_mode', '')
        mode_prompt = MODE_PROMPTS.get(mode, DEFAULT_MODE_PROMPT)
        parts.append(f"[cognitive state] {mode_prompt}")

        # 2. Confidence-aware instruction
        confidence = quantum_stats.get('confidence', 0.5)
        entropy = quantum_stats.get('quantum_entropy', 0.0)
        uncertainty = quantum_stats.get('uncertainty', 0.5)

        if confidence > 0.7 and entropy < 0.1:
            parts.append(
                "Your confidence level is high. "
                "Be direct and precise in your answer."
            )
        elif confidence < 0.4 and uncertainty > 0.3:
            parts.append(
                "Your confidence level is low. "
                "Acknowledge uncertainty rather than guessing. "
                "If you're not sure, say so clearly."
            )
        elif entropy > 0.3:
            parts.append(
                "You are considering multiple possibilities. "
                "Present alternatives rather than a single answer."
            )
        else:
            parts.append(
                "Your confidence level is moderate. "
                "Be measured in your tone and avoid overstatement."
            )

        # 3. Coherence-based instruction
        coherence = quantum_stats.get('spectral_coherence', 0.5)
        if coherence < 0.3:
            parts.append(
                "The conversation topic is shifting. "
                "Make sure your response addresses the current context."
            )

        # 4. Curiosity-awareness
        curiosity = quantum_stats.get('curiosity', 1.0)
        if curiosity > 1.5:
            parts.append(
                "You are in an exploratory state. "
                "Feel free to ask clarifying questions or offer new angles."
            )

        return '\n'.join(parts)

    def build_temperature_modulation(self, quantum_stats: Dict[str, float],
                                      base_temp: float = 0.7) -> float:
        """Compute temperature from cognitive state (H-QKV uncertainty gate).

        Equivalent to the uncertainty gate in H-QKV:
          low uncertainty → low temperature → focused generation
          high uncertainty → high temperature → broad exploration

        Parameters
        ----------
        quantum_stats : dict
        base_temp : float
            Default temperature.

        Returns
        -------
        float
            Modulated temperature.
        """
        confidence = quantum_stats.get('confidence', 0.5)
        uncertainty = quantum_stats.get('uncertainty', 0.5)

        # Temperature range: base ± 0.3
        temp_offset = (1.0 - confidence) * 0.3 + uncertainty * 0.1
        temp = base_temp + temp_offset
        return float(max(0.1, min(1.0, temp)))

    def __repr__(self) -> str:
        return "H_QKVBuilder(prompt-level H-QKV bridge)"
