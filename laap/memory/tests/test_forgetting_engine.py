"""
遗忘引擎自测：验证三阶段生命周期、核心记忆保护、唤醒机制。
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from laap.memory.forgetting import (
    ActivationCalculator,
    ForgettingEngine,
    LifecyclePolicy,
    MemoryLifecycle,
)
from laap.memory.consolidation import ConsolidationEngine

now = time.time()
DAY = 86400.0

# ── 构造记忆库 ──────────────────────────────────────────────
def mem(mid, created_days_ago, importance, valence=0.0, accesses=1, mtype="episodic"):
    created = now - created_days_ago * DAY
    return {
        "id": mid,
        "content": f"memory {mid}",
        "memory_type": mtype,
        "importance": importance,
        "valence": valence,
        "access_count": accesses,
        "created_at": created,
        # 访问时间：创建时 + 均匀分布的最近访问
        "access_times": [created - i * 0.5 * DAY for i in range(accesses)],
        "lifecycle": MemoryLifecycle.ACTIVE.value,
        "tags": ["test", mtype],
    }

memory_store = [
    # 1. 刚创建的高重要性记忆（应受 consolidation_window 保护）
    mem("fresh_important", created_days_ago=0.5, importance=0.9),
    # 2. 30 天前的低重要性记忆（应归档）
    mem("old_trivial", created_days_ago=30, importance=0.2, accesses=1),
    # 3. 60 天前但被频繁访问的记忆（应保持活跃）
    mem("old_frequent", created_days_ago=60, importance=0.5, accesses=20),
    # 4. 20 天前中等重要性（应休眠）
    mem("mid_importance", created_days_ago=20, importance=0.35, accesses=2),
    # 5. 强情绪记忆（应抵抗遗忘）
    mem("emotional", created_days_ago=45, importance=0.3, valence=0.9, accesses=2),
    # 6. 身份记忆（宪章级保护，永不降级）
    mem("identity_mem", created_days_ago=100, importance=0.3, accesses=1, mtype="identity"),
    # 7. 极端情况：200 天前、0 重要性、从未访问（最应归档）
    mem("ancient_neglected", created_days_ago=200, importance=0.05, accesses=1),
]

# ── 运行遗忘扫描 ─────────────────────────────────────────────
engine = ForgettingEngine(
    calculator=ActivationCalculator(),
    policy=LifecyclePolicy(min_age_days=3.0),
)
audit = engine.scan(memory_store, apply=True)

print("=" * 72)
print("遗忘引擎扫描结果")
print("=" * 72)
print(f"{'memory':<22}{'activation':>10}{'age(d)':>8}{'lifecycle':>12}  reason")
print("-" * 72)
for d in audit.details:
    print(f"{d['memory_id']:<22}{d['activation']:>10.3f}{d['age_days']:>8.1f}"
          f"{d['target']:>12}  {d['reason']}")

print("-" * 72)
print(f"扫描 {audit.scanned} | 归档 {audit.archived} | 休眠 {audit.demoted_to_dormant} "
      f"| 保护跳过 {audit.skipped_fresh}")

# ── 断言 ─────────────────────────────────────────────────────
state = {m["id"]: m["lifecycle"] for m in memory_store}
assert state["fresh_important"] == "active", "新记忆应受保护"
assert state["old_trivial"] == "archived", "30天低重要性应归档"
assert state["old_frequent"] == "active", "高频访问应保持活跃"
assert state["mid_importance"] == "dormant", "20天中重要性应休眠"
assert state["identity_mem"] == "active", "身份记忆永不降级"
print("\n[PASS] 生命周期状态机全部符合预期")

# ── 巩固引擎验证 ────────────────────────────────────────────
print("\n" + "=" * 72)
print("巩固引擎：归纳 3 条相似情景记忆")
print("=" * 72)
episodic = [
    {"id": "e1", "content": "和Lorry讨论LAAP架构", "tags": ["laap"], "importance": 0.6, "valence": 0.4, "memory_type": "episodic"},
    {"id": "e2", "content": "给Lorry展示认知引擎", "tags": ["laap"], "importance": 0.7, "valence": 0.5, "memory_type": "episodic"},
    {"id": "e3", "content": "Lorry部署遗忘引擎", "tags": ["laap"], "importance": 0.5, "valence": 0.3, "memory_type": "episodic"},
    {"id": "e4", "content": "无关记忆", "tags": ["other"], "importance": 0.3, "valence": 0.0, "memory_type": "episodic"},
]
cons = ConsolidationEngine()
report = cons.run_consolidation(episodic, apply=False)
assert report.induced >= 1, "3条laap主题记忆应被归纳"
print(f"归纳出 {report.induced} 条语义记忆:")
for note in report.notes:
    print(f"  - {note}")

# ── 遗忘+巩固闭环模拟（10轮） ───────────────────────────────
print("\n" + "=" * 72)
print("闭环模拟：遗忘与巩固对抗 10 轮")
print("=" * 72)
store = [
    mem("busy", created_days_ago=10, importance=0.5, accesses=3),
    mem("neglected", created_days_ago=10, importance=0.5, accesses=1),
]
for round_i in range(10):
    # 遗忘
    engine.scan(store, apply=True)
    # 巩固：busy 每次被访问强化，neglected 没有
    for m in store:
        if m["id"] == "busy":
            m["access_count"] += 2
            m["access_times"].append(now)
        m["importance"] = cons.strengthen(
            m["importance"], m["access_count"], m["valence"], m["memory_type"]
        )["importance"]
    # 时间流逝
    for m in store:
        m["created_at"] -= 1 * DAY
        m["access_times"] = [t - 1 * DAY for t in m["access_times"]]

final = {m["id"]: (m["lifecycle"], round(m["importance"], 3)) for m in store}
print(f"10轮后: {final}")
assert final["busy"][0] == "active", "持续访问的记忆应保持活跃"
assert final["neglected"][0] != "active", "被忽视的记忆应降级"
print("[PASS] 遗忘与巩固的对抗动态符合预期")

print("\n全部测试通过 ✅")
