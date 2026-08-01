"""Test particle filter"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from harness_particle_filter import ParticleFilter

pf = ParticleFilter(n_particles=500)
print("ParticleFilter initialized with %d particles" % pf.n)

# 模拟几次 predict + update
for i in range(5):
    dt = 0.25
    pf.predict(dt)
    obs = {
        "input_sentiment": 0.5,
        "detected_keywords": ["想你", "宝贝"],
        "pre_needs": {"relatedness": max(0.3, 0.5 - i * 0.02)},
    }
    pf.update(obs)
    state = pf.get_state()
    dom_need = max(state["estimated_needs"], key=state["estimated_needs"].get)
    print("Step %d: need=%s(%.2f) ess=%.0f" % (
        i+1, dom_need, state["estimated_needs"][dom_need], pf.get_ess()))

# 预测
print("\n=== 预测未来 1 小时 ===")
forecast = pf.forecast(steps=4, dt_per_step=0.25)
for name in ["relatedness", "competence"]:
    traj = forecast["needs_trajectory"][name]
    print("  %s: %s" % (name, [round(v,3) for v in traj]))

ret = pf.predict_user_return(horizon_hours=1)
print("  用户1小时内回归概率: %.1f%%" % (ret["probability"] * 100))
print("  不确定性: %.3f" % ret["uncertainty"])

print("\n✅ Particle filter OK")
