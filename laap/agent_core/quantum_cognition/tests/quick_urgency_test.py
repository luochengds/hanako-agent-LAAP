"""Quick targeted test: spectral saliency urgency detection vs classic keyword.
Run after A/B test to verify spectral buffer behavior.
"""
import sys, numpy as np
sys.path.insert(0, 'D:/LAAP')
from laap.agent_core.quantum_cognition.psi_quantum import PsiQuantumCognition, QuantumCognitionConfig
from laap.agent_core.psi_cognition import PSICognition

q = PsiQuantumCognition(QuantumCognitionConfig(verbose_logging=False))
c = PSICognition()

# Warmup: 8 neutral turns to fill spectral buffer
print("=== Warming up (8 neutral turns) ===")
neutral = ['hi','ok','right','good','yes','sure','fine','okay']
for t in neutral:
    q.perceive(t)
    c.perceive(t)
qs = q.get_stats()
print(f"  Buffer warm: urgent_score={qs.get('urgent_score',0):.3f}, coherence={qs.get('spectral_coherence',0):.3f}")

# Test urgency detection
print("\n=== Urgency detection test ===")
tests = [
    ('neutral', '今天天气真不错，你想出去走走吗'),
    ('urgent', '紧急！系统crash了，需要立刻修复！现在马上！'),
    ('reflective', '我在想一个问题，关于意识的本质'),
    ('urgent2', 'error fatal database connection timeout now'),
    ('mixed', '我有点困惑但也很兴奋，这个bug很严重'),
]

print(f"{'Label':12} {'Stimulus':30} {'Classic':>10} {'Quantum_urg':>12} {'Q_cohere':>10}")
print('-' * 75)
for label, text in tests:
    cp = c.perceive(text)
    qp = q.perceive(text)
    qs = q.get_stats()
    print(f"{label:12} {text[:30]:30} {cp.salience:>10.3f} {qs.get('urgent_score',0):>12.3f} {qs.get('spectral_coherence',0):>10.3f}")

# Continuous test: transition from neutral -> urgent -> reflective
print("\n=== Continuous rhythm test (neutral -> urgent -> reflective) ===")
q2 = PsiQuantumCognition(QuantumCognitionConfig(verbose_logging=False))
for i, (label, text) in enumerate([
    ('neutral', '你好吗'),
    ('neutral', '我挺好的'),
    ('neutral', '今天想聊点技术'),
    ('neutral', '嗯，你先说'),
    ('urgent', '有紧急情况！'),
    ('urgent', '系统马上就要崩了！'),
    ('urgent', '赶快处理！现在！'),
    ('reflective', '好，解决了'),
    ('reflective', '其实我在想，这个问题有更深层的原因'),
    ('reflective', '你说架构设计是不是应该从根本上避免这类问题'),
]):
    q2.perceive(text)
    qs2 = q2.get_stats()
    print(f"  {i+1:2d}. {label:12} {qs2.get('urgent_score',0):.3f} urgent  {qs2.get('spectral_coherence',0):.3f} coherence  entropy={qs2.get('quantum_entropy',0):.4f}")
