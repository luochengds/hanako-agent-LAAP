"""BCI-LAAP cognitive bridge.

``BCICognitiveBridge`` sits between the real-time neuro pipeline and the
higher-level LAAP cognitive architecture. It translates decoded
``CognitiveState`` objects into inputs for attention, needs, emotion,
consciousness and world-model modules, while enforcing a safety gate before
any injection happens.
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any, Dict, Optional

from laap.bci.decoder import CognitiveStateDecoder
from laap.bci.hardware import BCIHardwareInterface
from laap.bci.pipeline import RealtimeNeuroPipeline
from laap.bci.primitives import CognitiveState, NeuroDataFrame
from laap.bci.safety import BCISecurityLayer
from laap.cognition.needs import NeedType

logger = logging.getLogger("laap.bci")


class BCICognitiveBridge:
    """Bridge decoded cognitive state into LAAP cognitive subsystems."""

    def __init__(
        self,
        hardware: BCIHardwareInterface,
        pipeline: RealtimeNeuroPipeline,
        decoder: CognitiveStateDecoder,
        safety: BCISecurityLayer,
        attention_engine=None,
        needs_system=None,
        emotion_system=None,
        conscious_stream=None,
        world_model=None,
        event_bus=None,
    ):
        self.hardware = hardware
        self.pipeline = pipeline
        self.decoder = decoder
        self.safety = safety

        # LAAP cognitive dependencies are all optional.
        self.attention_engine = attention_engine
        self.needs_system = needs_system
        self.emotion_system = emotion_system
        self.conscious_stream = conscious_stream
        self.world_model = world_model
        self.event_bus = event_bus

        self._current_state: Optional[CognitiveState] = None
        self._running = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def start(self) -> None:
        """Register the frame callback and start the hardware stream."""
        if self._running:
            return
        self.hardware.register_stream_callback(self._on_neuro_frame)
        self.hardware.start_stream()
        self._running = True
        logger.info("BCI cognitive bridge started")

    def stop(self) -> None:
        """Stop the hardware stream."""
        self.hardware.stop_stream()
        self._running = False
        logger.info("BCI cognitive bridge stopped")

    def get_current_cognitive_state(self) -> Optional[CognitiveState]:
        """Return the last decoded cognitive state."""
        return self._current_state

    # ------------------------------------------------------------------
    # Internal handlers
    # ------------------------------------------------------------------
    def _on_neuro_frame(self, frame: NeuroDataFrame) -> None:
        """Process one neuro frame through pipeline → decoder → safety → LAAP."""
        features = self.pipeline.process_window(frame)
        cog_state = self.decoder.decode(features)
        self._current_state = cog_state

        decision = self.safety.scan_neuro_injection(cog_state)
        action = decision.get("action", "allow")
        reason = decision.get("reason", "")
        attenuate = float(decision.get("attenuate", 1.0))

        if action == "block":
            logger.warning(
                "BCI injection blocked (reason=%s): focus=%s load=%.2f",
                reason,
                cog_state.attention_focus,
                cog_state.cognitive_load,
            )
            self._publish_event(
                "bci_state_blocked",
                {
                    "reason": reason,
                    "state": self._state_to_dict(cog_state),
                },
            )
            return

        if action == "warn":
            logger.warning(
                "BCI injection warned (reason=%s) but proceeding with attenuation=%.2f",
                reason,
                attenuate,
            )

        self._inject_to_laap(cog_state, attenuate=attenuate)

    def _inject_to_laap(
        self,
        cog_state: CognitiveState,
        attenuate: float = 1.0,
    ) -> None:
        """Push a decoded cognitive state into all connected LAAP modules."""
        focus = cog_state.attention_focus
        load = float(cog_state.cognitive_load)
        vad = cog_state.emotion_vad or {}
        valence = float(vad.get("valence", 0.0))
        arousal = float(vad.get("arousal", 0.0))
        dominance = float(vad.get("dominance", 0.0))

        # Attention: boost salience of the current task when focus is executive.
        if self.attention_engine is not None and focus == "focused_executive":
            self._apply_attention_boost(attenuate)

        # Needs: high cognitive load implies an energy deficit.
        if self.needs_system is not None:
            deficit = min(load * 0.5, 1.0)
            confidence = 0.75 * attenuate
            try:
                self.needs_system.update_external_estimate(
                    NeedType.ENERGY,
                    deficit=deficit,
                    confidence=confidence,
                )
            except Exception:  # pragma: no cover - defensive
                logger.exception("needs_system.update_external_estimate failed")

        # Emotion: blend external VAD estimate.
        if self.emotion_system is not None and hasattr(
            self.emotion_system, "set_external_vad"
        ):
            try:
                self.emotion_system.set_external_vad(
                    valence,
                    arousal,
                    dominance,
                    source="bci_neuro",
                    confidence=0.75 * attenuate,
                )
            except Exception:  # pragma: no cover - defensive
                logger.exception("emotion_system.set_external_vad failed")

        # Conscious stream: add an interoceptive experience.
        if self.conscious_stream is not None and hasattr(
            self.conscious_stream, "experience_interoception"
        ):
            content = (
                f"BCI interoception: attention={focus}, "
                f"cognitive_load={load:.2f}"
            )
            try:
                self.conscious_stream.experience_interoception(
                    content,
                    valence,
                    intensity=0.6 * attenuate,
                )
            except Exception:  # pragma: no cover - defensive
                logger.exception("conscious_stream.experience_interoception failed")

        # World model: keep an up-to-date representation of the user state.
        if self.world_model is not None and hasattr(
            self.world_model, "update_entity"
        ):
            try:
                self.world_model.update_entity(
                    "user_cognitive_state",
                    properties={
                        "attention_focus": focus,
                        "cognitive_load": load,
                        "emotion_valence": valence,
                        "emotion_arousal": arousal,
                        "emotion_dominance": dominance,
                        "timestamp": cog_state.timestamp,
                    },
                    confidence=0.7 * attenuate,
                    source="bci_decoder",
                )
            except Exception:  # pragma: no cover - defensive
                logger.exception("world_model.update_entity failed")

        self._publish_event(
            "bci_state_injected",
            self._state_to_dict(cog_state),
        )

    def _apply_attention_boost(self, attenuate: float) -> None:
        """Use the best available salience/focus API on the attention engine."""
        engine = self.attention_engine
        weight = 0.8 * attenuate

        if hasattr(engine, "boost_salience"):
            try:
                engine.boost_salience(
                    target="current_task",
                    source="bci_focus",
                    weight=weight,
                )
                return
            except TypeError:
                # Fallback to a simpler positional signature.
                try:
                    engine.boost_salience("current_task", weight)
                    return
                except TypeError:
                    pass

        if hasattr(engine, "update_salience"):
            engine.update_salience("current_task", weight)
            return

        if hasattr(engine, "boost_focus"):
            engine.boost_focus("current_task", weight)
            return

        if hasattr(engine, "focus"):
            engine.focus("current_task", reason="bci_focus")

    def _publish_event(self, event_type: str, data: Dict[str, Any]) -> None:
        """Publish an event if an event bus was provided."""
        if self.event_bus is None:
            return
        try:
            if hasattr(self.event_bus, "publish_simple"):
                self.event_bus.publish_simple(event_type, data, source="bci_bridge")
            elif hasattr(self.event_bus, "publish"):
                self.event_bus.publish(
                    self.event_bus.Event(
                        type=event_type,
                        data=data,
                        source="bci_bridge",
                    )
                )
        except Exception:  # pragma: no cover - defensive
            logger.exception("event_bus.publish failed")

    @staticmethod
    def _state_to_dict(cog_state: CognitiveState) -> Dict[str, Any]:
        """Serialize a cognitive state to a plain dictionary."""
        if hasattr(cog_state, "to_dict"):
            return cog_state.to_dict()
        return asdict(cog_state)
