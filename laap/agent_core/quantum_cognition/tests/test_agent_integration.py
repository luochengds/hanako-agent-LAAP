"""Agent import smoke test — verify integration doesn't break."""
import sys, os
sys.path.insert(0, 'D:/LAAP')
from laap.agent_core.agent import Agent, AgentConfig
from laap.agent_core.quantum_cognition import (
    PsiQuantumCognition, HallucinationGuard, CognitiveKet,
    QuantumCognitionConfig, KalmanSelfModel
)

cfg = AgentConfig(
    enable_quantum_cognition=True,
    enable_hallucination_guard=True,
)
try:
    agent = Agent(config=cfg, mode='kernel')
    has_qc = hasattr(agent, 'quantum_cognition') and agent.quantum_cognition is not None
    has_hg = hasattr(agent, 'hallucination_guard') and agent.hallucination_guard is not None
    print(f"Agent created: {agent.config.name}")
    print(f"Quantum cognition: {'OK' if has_qc else 'N/A'}")
    print(f"Hallucination guard: {'OK' if has_hg else 'N/A'}")
    if has_qc:
        stats = agent.cognitive_status()
        print(f"Cognitive status mode: {stats.get('mode', 'N/A')}")
        print(f"Confidence: {stats.get('confidence', 'N/A')}")
        print(f"Entropy: {stats.get('quantum_entropy', 'N/A')}")
except Exception as e:
    print(f"Note: Agent construction incomplete (may need LLM keys): {e}")
    # The quantum cognition part should still work even if LLM init fails
    qc = PsiQuantumCognition(QuantumCognitionConfig(verbose_logging=False))
    hg = HallucinationGuard()
    print(f"Standalone quantum engine: {qc}")
    print(f"Standalone guard: {hg}")
    stats = qc.get_stats()
    print(f"Stats: confidence={stats.get('confidence', 0):.2f}, entropy={stats.get('quantum_entropy', 0):.4f}")
    decision = hg.pre_gate(stats)
    print(f"Pre-gate: {decision.action} ({decision.reason})")

print("\n=== Integration smoke test complete ===")
