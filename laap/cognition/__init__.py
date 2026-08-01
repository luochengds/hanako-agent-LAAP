"""LAAP - Cognitive Engine (Unified Brain Layer + Embodiment)"""
from laap.cognition.needs import NeedDriveSystem, Need, NeedType
from laap.cognition.emotion import EmotionGradient, EmotionalState
from laap.cognition.emotion import EmotionSystem, EmotionState, EmotionEventType
from laap.cognition.emotion_system import ComprehensiveEmotionSystem
from laap.cognition.metacognition import (
    MetacognitionSystem, ReflectionReport, Anomaly, AnomalyType,
    Improvement, ImprovementType,
)
from laap.cognition.goals import GoalTree, Goal, GoalStatus
from laap.cognition.awareness import AwarenessSystem
from laap.cognition.engine import CognitiveEngine, CognitiveAction, CognitiveState
from laap.cognition.integrated_engine import IntegratedCognitiveEngine
from laap.cognition.brain import Brain, BrainRegion, CorticalState, Thought, CognitiveSignal
from laap.cognition.first_principles import (
    FirstPrinciplesEngine, FirstPrinciple, DecompositionNode,
    DecompositionStyle, ReconstructionPlan,
)
from laap.cognition.embodiment import (
    # Body types
    BodyType, SensorType, SensorEvent,
    BodyCapabilities, EmbodimentInterface,
    RobotBody, CloudBrainBody,
    # Consciousness
    ConsciousnessStream, ConsciousnessFrame,
    # Unified
    EmbodiedBrain,
)
from laap.cognition.unity import (
    UnityEngine, UnityDecision, EmbodiedSkill, SkillProficiency,
)
# EWC 权威实现（单一来源）；evolution.py 仅 re-export 以保持向后兼容
from laap.cognition.ewc import ElasticWeightConsolidation
from laap.cognition.evolution import (
    # 1. Performance
    RustNativeBridge, NativeOp,
    # 2. Distributed
    AgentCluster, AgentNode, InterAgentMessage,
    # 3. Federated
    FederatedLearner,
    # 4. Multi-modal
    MultiModalEngine, ModalityType, ModalityInput,
    # 5. Mobile
    MobileBridge,
    # 6. Blockchain
    BlockchainLedger, MemoryBlock,
    # 7. Explainability
    ExplainabilityEngine,
    # 8. Continual Learning (EWC) — 见上方 laap.cognition.ewc
    # Unified
    EvolutionEngine,
)

__all__ = [
    # PSI Needs
    "NeedDriveSystem", "Need", "NeedType",
    # Emotion
    "EmotionGradient", "EmotionalState", "ComprehensiveEmotionSystem",
    "EmotionSystem", "EmotionState", "EmotionEventType",
    # Metacognition (意识中间件层)
    "MetacognitionSystem", "ReflectionReport", "Anomaly", "AnomalyType",
    "Improvement", "ImprovementType",
    # Goals
    "GoalTree", "Goal", "GoalStatus",
    # Awareness
    "AwarenessSystem",
    # Engines
    "CognitiveEngine", "CognitiveAction", "CognitiveState",
    "IntegratedCognitiveEngine",
    # Brain (Unified Human-Like Thinking Layer)
    "Brain", "BrainRegion", "CorticalState", "Thought", "CognitiveSignal",
    # First Principles
    "FirstPrinciplesEngine", "FirstPrinciple", "DecompositionNode",
    "DecompositionStyle", "ReconstructionPlan",
    # Embodiment
    "BodyType", "SensorType", "SensorEvent",
    "BodyCapabilities", "EmbodimentInterface",
    "RobotBody", "CloudBrainBody",
    "ConsciousnessStream", "ConsciousnessFrame",
    "EmbodiedBrain",
    # Unity (知行合一)
    "UnityEngine", "UnityDecision", "EmbodiedSkill", "SkillProficiency",
    # Evolution (8 directions)
    "EvolutionEngine", "RustNativeBridge", "NativeOp",
    "AgentCluster", "AgentNode", "InterAgentMessage",
    "FederatedLearner",
    "MultiModalEngine", "ModalityType", "ModalityInput",
    "MobileBridge",
    "BlockchainLedger", "MemoryBlock",
    "ExplainabilityEngine",
    "ElasticWeightConsolidation",
]
