"""PSI cognitive state machine for the LAAP Aether orchestration layer."""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any


class PSIModulator(Enum):
    """Cognitive modulators that shape the PSI agent's processing mode."""

    ACTIVATION = auto()
    RESOLUTION = auto()
    SECURING = auto()
    SELECTION = auto()
    COMPETENCE = auto()


class PSIUrge(Enum):
    """Homeostatic urges that drive the PSI agent's behavior."""

    SURVIVAL = auto()
    AFFILIATION = auto()
    COMPETENCE = auto()
    CERTAINTY = auto()
    CURIOSITY = auto()


@dataclass
class PSIState:
    """Snapshot of the PSI agent's dynamic cognitive state."""

    modulators: dict[PSIModulator, float] = field(
        default_factory=lambda: {
            PSIModulator.ACTIVATION: 0.5,
            PSIModulator.RESOLUTION: 0.5,
            PSIModulator.SECURING: 0.3,
            PSIModulator.SELECTION: 0.6,
            PSIModulator.COMPETENCE: 0.7,
        }
    )
    urges: dict[PSIUrge, float] = field(
        default_factory=lambda: {
            PSIUrge.SURVIVAL: 0.8,
            PSIUrge.AFFILIATION: 0.6,
            PSIUrge.COMPETENCE: 0.7,
            PSIUrge.CERTAINTY: 0.5,
            PSIUrge.CURIOSITY: 0.7,
        }
    )
    pleasure: float = 0.0
    arousal: float = 0.0
    dominance: float = 0.0
    dominant_feeling: str = "neutral"
    goal_stack: list[dict[str, Any]] = field(default_factory=list)
    certainty: float = 0.5
    timestamp: float = field(default_factory=time.time)

    def update_emotions(self) -> None:
        """Derive PAD emotion dimensions and a categorical dominant feeling."""
        avg_satisfaction = sum(self.urges.values()) / len(self.urges)
        self.pleasure = (avg_satisfaction - 0.5) * 2
        uncertainty = 1.0 - self.certainty
        self.arousal = (self.modulators[PSIModulator.ACTIVATION] + uncertainty) / 2
        self.dominance = (
            self.modulators[PSIModulator.COMPETENCE]
            + self.modulators[PSIModulator.SELECTION]
            - 1.0
        )

        if self.pleasure > 0.3 and self.arousal > 0.6:
            self.dominant_feeling = "excited"
        elif self.pleasure > 0.3 and self.arousal < 0.4:
            self.dominant_feeling = "content"
        elif self.pleasure < -0.3 and self.arousal > 0.6:
            self.dominant_feeling = "distressed"
        elif self.pleasure < -0.3 and self.arousal < 0.4:
            self.dominant_feeling = "depressed"
        elif self.arousal > 0.7:
            self.dominant_feeling = "alert"
        else:
            self.dominant_feeling = "neutral"

    def to_dict(self) -> dict[str, Any]:
        """Serialize the state to a JSON-friendly dictionary."""
        return {
            "modulators": {k.name: v for k, v in self.modulators.items()},
            "urges": {k.name: v for k, v in self.urges.items()},
            "pleasure": self.pleasure,
            "arousal": self.arousal,
            "dominance": self.dominance,
            "dominant_feeling": self.dominant_feeling,
            "certainty": self.certainty,
            "goal_stack_depth": len(self.goal_stack),
        }


class PSIAgent:
    """A PSI-style cognitive agent that perceives, acts, and learns."""

    def __init__(
        self,
        agent_id: str = "psi_core",
        state: PSIState | None = None,
        learning_rate: float = 0.1,
    ) -> None:
        self.agent_id = agent_id
        self.state = state if state is not None else PSIState()
        self.perception_buffer: deque[dict[str, Any]] = deque(maxlen=100)
        self.memory_associations: dict[str, float] = {}
        self.learning_rate = learning_rate

    async def process_perception(self, stimulus: dict[str, Any]) -> PSIState:
        """Integrate a stimulus into the PSI state and update urges/modulators."""
        self.perception_buffer.append({"stimulus": stimulus, "timestamp": time.time()})

        stimulus_type = stimulus.get("type")
        if stimulus_type == "user_message":
            self.state.urges[PSIUrge.AFFILIATION] += 0.1
            self.state.urges[PSIUrge.CURIOSITY] += 0.05
        elif stimulus_type == "error":
            self.state.urges[PSIUrge.COMPETENCE] -= 0.2
            self.state.urges[PSIUrge.CERTAINTY] -= 0.15
        elif stimulus_type == "success":
            self.state.urges[PSIUrge.COMPETENCE] += 0.15
            self.state.urges[PSIUrge.CERTAINTY] += 0.1

        for urge in self.state.urges:
            self.state.urges[urge] = max(0.0, min(1.0, self.state.urges[urge]))

        max_urgency = 1.0 - min(self.state.urges.values())
        self.state.modulators[PSIModulator.ACTIVATION] = 0.3 + max_urgency * 0.7
        self.state.modulators[PSIModulator.RESOLUTION] = 0.8 - max_urgency * 0.4
        self.state.modulators[PSIModulator.SECURING] = max_urgency * 0.8

        self.state.certainty = stimulus.get("certainty", self.state.certainty)
        self.state.update_emotions()
        self.state.timestamp = time.time()
        return self.state

    async def select_action(self, candidates: list[dict[str, Any]]) -> dict[str, Any]:
        """Choose the candidate action that best matches the current PSI state."""
        if not candidates:
            return {"action": "wait", "confidence": 0.0}

        scored: list[tuple[dict[str, Any], float]] = []
        for candidate in candidates:
            score = 0.0
            if candidate.get("requires_detail"):
                score += self.state.modulators[PSIModulator.RESOLUTION]
            if candidate.get("requires_speed"):
                score += self.state.modulators[PSIModulator.ACTIVATION]
            satisfies = candidate.get("satisfies_urge")
            if satisfies in {u.name for u in self.state.urges}:
                urge = PSIUrge[satisfies]
                score += (1.0 - self.state.urges[urge]) * 2.0
            score += self.state.modulators[PSIModulator.COMPETENCE] * 0.5
            scored.append((candidate, score))

        scored.sort(key=lambda item: item[1], reverse=True)
        return scored[0][0]

    async def learn_from_outcome(
        self, action: dict[str, Any], outcome: dict[str, Any]
    ) -> None:
        """Update competence and memory associations based on action outcome."""
        success = outcome.get("success", False)
        key = f"{action.get('action')}->{outcome.get('type')}"

        if success:
            self.state.urges[PSIUrge.COMPETENCE] += 0.1
            self.state.modulators[PSIModulator.COMPETENCE] += 0.05
            self.memory_associations[key] = (
                self.memory_associations.get(key, 0.5) + self.learning_rate
            )
        else:
            self.state.urges[PSIUrge.COMPETENCE] -= 0.15
            self.state.modulators[PSIModulator.COMPETENCE] -= 0.05
            self.memory_associations[key] = max(
                0.0,
                self.memory_associations.get(key, 0.5) - self.learning_rate,
            )

        for urge in self.state.urges:
            self.state.urges[urge] = max(0.0, min(1.0, self.state.urges[urge]))
        for modulator in self.state.modulators:
            self.state.modulators[modulator] = max(
                0.0, min(1.0, self.state.modulators[modulator])
            )

        self.state.update_emotions()
