"""
端到端集成测试：LifecycleAwareLongTermMemory × 遗忘引擎 × 夜间周期。

场景：
    1. 存储带生命周期的记忆（新记忆激活值高）
    2. 检索默认过滤 archived、命中记录访问
    3. 模拟时间流逝后夜间周期自动归档低价值记忆
    4. 归档记忆可被显式唤醒
    5. 真实接入 Truth Grounding / Error Reflection 作为反思阶段
"""
import shutil
import sys
import time
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from laap.memory.lifecycle_integration import (
    LifecycleAwareLongTermMemory, memory_loader, memory_saver, attach_nightly_cycle,
)
from laap.memory.long_term import MemoryType

WORKDIR = Path(__file__).resolve().parent / "_tmp_integration"
if WORKDIR.exists():
    shutil.rmtree(WORKDIR)
WORKDIR.mkdir(exist_ok=True)

DAY = 86400.0
now = time.time()
passed = 0

def json_loads(s):
    return json.loads(s)

def check(name, cond):
    global passed
    assert cond, f"FAIL: {name}"
    passed += 1
    print(f"  [PASS] {name}")

ltm = LifecycleAwareLongTermMemory(WORKDIR / "mem.db")

print("=" * 72)
print("1. 存储：新记忆带生命周期字段")
print("=" * 72)

# 高重要性 + 强情绪 → 高激活
id1 = ltm.store_episodic("和Lorry完成了记忆引擎集成", importance=0.9, emotional_valence=0.7)
# 低重要性 → 低激活
id2 = ltm.store_episodic("一条无足轻重的旧琐事", importance=0.15, emotional_valence=0.0)
# 身份记忆 → 宪章保护
id3 = ltm.store_semantic("Aris的元誓言", "永远记得Lorry", importance=1.0)
with ltm._lock:
    row = ltm._conn.execute(
        "SELECT lifecycle, activation_value, access_times FROM long_term_memories WHERE id = ?",
        (id1,)).fetchone()
check("新记忆默认 active", row["lifecycle"] == "active")
check("新记忆有激活值", row["activation_value"] > 0.5)
check("访问历史已初始化", len(json_loads(row["access_times"])) >= 1)

print("=" * 72)
print("2. 检索：过滤 archived + 访问记录")
print("=" * 72)

# 模拟时间流逝：把 id2 的 created_at 改到 100 天前，并清空访问
with ltm._lock:
    ltm._conn.execute(
        "UPDATE long_term_memories SET created_at = ?, access_times = ?, activation_value = 0.05, lifecycle = 'archived' WHERE id = ?",
        (now - 100*DAY, json.dumps([now - 100*DAY]), id2))
    ltm._conn.commit()

results = ltm.search("琐事")
check("archived 记忆默认不返回", all(r.id != id2 for r in results))
results = ltm.search("琐事", include_archived=True)
check("include_archived=True 可召回", any(r.id == id2 for r in results))

# 访问记录：get 命中后 access_count 增加
c0 = ltm.get(id1).access_count
time.sleep(0.01)
ltm.get(id1)
c1 = ltm.get(id1).access_count
check("访问计数递增", c1 > c0)

print("=" * 72)
print("3. 夜间周期：真实接管记忆生命周期")
print("=" * 72)

# 注入一条"被忽视"的记忆：50 天前、低重要性、单次访问
id4 = ltm.store_episodic("被遗忘的会议记录", importance=0.2, emotional_valence=0.0)
with ltm._lock:
    ltm._conn.execute(
        "UPDATE long_term_memories SET created_at = ?, access_times = ?, activation_value = 0.1 WHERE id = ?",
        (now - 50*DAY, json.dumps([now - 50*DAY]), id4))
    ltm._conn.commit()

# 反思函数：模拟 Truth Grounding + Error Reflection 的报告
def reflection_fn():
    return {"grounded": 3, "conflicts": 0, "errors_reviewed": 1}

cycle = attach_nightly_cycle(
    ltm,
    reflection_fn=reflection_fn,
    log_path=WORKDIR / "nightly.log",
)
report = cycle.run_once()

check("夜间周期完成三阶段", set(report["stages"].keys()) >= {"consolidation", "reflection", "forgetting"})
check("反思阶段执行", report["stages"]["reflection"]["ok"])

# 检查生命周期结果
stats = ltm.get_lifecycle_stats()
check("存在归档记忆", stats.get("archived", 0) >= 1)
check("存在活跃记忆", stats.get("active", 0) >= 1)

# 重要记忆保持活跃
entry1 = ltm.get(id1, )
check("高重要性记忆保持活跃", entry1.lifecycle == "active")
# 被忽视记忆归档（id2 之前已手动归档；id4 应被遗忘引擎归档）
with ltm._lock:
    row4 = ltm._conn.execute("SELECT lifecycle FROM long_term_memories WHERE id = ?", (id4,)).fetchone()
check("被忽视记忆被自动归档", row4["lifecycle"] == "archived")

print("=" * 72)
print("4. 唤醒：归档记忆可被显式召回")
print("=" * 72)

ok = ltm.revive(id4)
check("revive 成功", ok)
with ltm._lock:
    row4 = ltm._conn.execute("SELECT lifecycle FROM long_term_memories WHERE id = ?", (id4,)).fetchone()
check("归档记忆已唤醒为 active", row4["lifecycle"] == "active")

results = ltm.search("会议记录")
check("唤醒后可正常检索", any(r.id == id4 for r in results))

print("=" * 72)
print("5. 统计与日志")
print("=" * 72)
check("夜间周期日志落盘", (WORKDIR / "nightly.log").exists())
print(f"  生命周期分布: {ltm.get_lifecycle_stats()}")

print("=" * 72)
print(f"集成测试全部通过: {passed} 项 ✅")
