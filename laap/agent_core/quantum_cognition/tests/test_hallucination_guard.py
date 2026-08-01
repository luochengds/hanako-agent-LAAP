"""End-to-end smoke test: hallucination guard + agent integration.

Tests the three-layer guard without an actual LLM call.
"""
import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', '..')))

from laap.agent_core.quantum_cognition import (
    PsiQuantumCognition, QuantumCognitionConfig,
    HallucinationGuard, GuardConfig,
)

print("=== Test 1: HallucinationGuard pre-gate ===")
guard = HallucinationGuard(GuardConfig(
    confidence_min=0.35,
    confidence_hard_floor=0.15,
    enable_pre_gate=True,
))

# Test: high confidence → generate
decision = guard.pre_gate({'confidence': 0.8, 'uncertainty': 0.1, 'quantum_entropy': 0.02})
assert decision.action == 'generate', f"Expected generate, got {decision.action}"
print(f"  High confidence (0.8): {decision.action} (correct)")

# Test: low confidence → caveat
decision = guard.pre_gate({'confidence': 0.25, 'uncertainty': 0.5, 'quantum_entropy': 0.3})
assert decision.action == 'caveat', f"Expected caveat, got {decision.action}"
print(f"  Low confidence (0.25): {decision.action} (correct)")

# Test: very low confidence → reject
decision = guard.pre_gate({'confidence': 0.10, 'uncertainty': 1.5, 'quantum_entropy': 0.8})
assert decision.action == 'reject', f"Expected reject, got {decision.action}"
print(f"  Very low confidence (0.10): {decision.action} (correct)")
print(f"  Safe response: {decision.safe_response[:40]}...")

print("\n=== Test 2: HallucinationGuard parameter modulation ===")
params = guard.modulate_params({
    'confidence': 0.9, 'uncertainty': 0.1,
    'spectral_coherence': 0.8, 'quantum_entropy': 0.01,
})
print(f"  High confidence params: temp={params.temperature:.2f}, top_p={params.top_p:.2f}, max_tokens={params.max_tokens}")
assert params.temperature < 0.5, f"Expected low temp for high confidence, got {params.temperature}"

params = guard.modulate_params({
    'confidence': 0.25, 'uncertainty': 0.5,
    'spectral_coherence': 0.3, 'quantum_entropy': 0.4,
})
print(f"  Low confidence params: temp={params.temperature:.2f}, top_p={params.top_p:.2f}, max_tokens={params.max_tokens}")
assert params.temperature > 0.6, f"Expected high temp for low confidence, got {params.temperature}"
assert params.system_prefix != '', "Expected system_prefix for low confidence"

print("\n=== Test 3: HallucinationGuard post-validation ===")

# Test: clean response
result = guard.validate(
    "I think the answer is 42, based on the data we've seen.",
    "what is the answer?",
    {'spectral_coherence': 0.8, 'quantum_entropy': 0.05},
)
print(f"  Clean response: valid={result.is_valid}, caveat={result.needs_caveat}")
assert result.is_valid, "Expected clean response to be valid"

# Test: contradictory response
result = guard.validate(
    "Yes, that's definitely correct. No, wait, that's wrong. Actually I'm not sure.",
    "is this right?",
    {'spectral_coherence': 0.6, 'quantum_entropy': 0.3},
)
print(f"  Contradictory response: valid={result.is_valid}, caveat={result.needs_caveat}, issues={result.issues}")
assert result.needs_caveat, "Expected caveat for contradictory response"

# Test: verbosity
result = guard.validate(
    " ".join(["word"] * 150),
    "hi",
    {'spectral_coherence': 0.7, 'quantum_entropy': 0.1},
)
print(f"  Verbose response: valid={result.is_valid}, issues={result.issues}, caveat={result.needs_caveat}")
assert result.needs_caveat, "Expected caveat for verbose response"

print("\n=== Test 4: Quantum cognition engine lifecycle ===")
qc = PsiQuantumCognition(QuantumCognitionConfig(verbose_logging=False))
stats = qc.get_stats()
print(f"  Initial state: confidence={stats.get('confidence', 'N/A')}, entropy={stats.get('quantum_entropy', 'N/A')}")

goal, state = qc.decide("This is a normal test message")
stats = qc.get_stats()
print(f"  After decide: goal='{goal}', state='{state}', confidence={stats.get('confidence', 'N/A'):.3f}")

qc.learn("positive outcome", success=True)
stats = qc.get_stats()
print(f"  After learn: curiosity={stats.get('curiosity', 'N/A'):.3f}, confidence={stats.get('confidence', 'N/A'):.3f}")

print(f"\n  Full stats: {stats}")

print("\n=== Test 5: Full integration path ===")
guard2 = HallucinationGuard()

# Simulate what _kernel_chat does:
# 1. perceive + decide
qc.decide("Tell me something you're not sure about")

# 2. pre-gate
stats = qc.get_stats()
print(f"  Pre-gate stats: conf={stats.get('confidence', 0):.2f}, uncert={stats.get('uncertainty', 0):.2f}")
decision = guard2.pre_gate(stats)
print(f"  Decision: {decision.action} ({decision.reason})")

# 3. modulate
params = guard2.modulate_params(stats)
print(f"  Modulated params: temp={params.temperature:.2f}, top_p={params.top_p:.2f}")

# 4. (simulate generation) 
simulated_response = "I think there might be some uncertainty here, but here's my best answer."

# 5. post-validate
result = guard2.validate(simulated_response, "Tell me something you're not sure about", stats)
print(f"  Post-validation: valid={result.is_valid}, caveat={result.needs_caveat}")
qc.learn("generated response", success=result.is_valid)

print("\n=== ALL TESTS PASSED ===")
