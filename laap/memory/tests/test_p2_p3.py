"""
P2+P3 综合测试：时间锚定、知识图谱、多模态、夜间周期。
"""
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from laap.memory.temporal import (
    TemporalAnchor, TemporalType, anchor_entry, get_anchor,
    filter_active, filter_by_time_window, sort_by_time, build_timeline,
)
from laap.memory.knowledge_graph import KnowledgeGraph, Triple, extract_triples
from laap.memory.multimodal import MultimodalMemoryStore, MultimodalMemory, Modality
from laap.memory.nightly_cycle import NightlyCycleScheduler
from laap.memory.forgetting import ForgettingEngine
from laap.memory.consolidation import ConsolidationEngine

DAY = 86400.0
now = time.time()
WORKDIR = Path(__file__).resolve().parent / "_tmp_p23"
if WORKDIR.exists():
    shutil.rmtree(WORKDIR)
WORKDIR.mkdir(exist_ok=True)

passed = 0
def check(name, cond):
    global passed
    assert cond, f"FAIL: {name}"
    passed += 1
    print(f"  [PASS] {name}")

print("=" * 72)
print("P2a: 时间锚定")
print("=" * 72)

class FakeEntry:
    def __init__(self, content, metadata=None):
        self.content = content
        self.metadata = metadata or {}

# 三条记忆：静态事实、动态事实（已失效）、未来事件
e_static = FakeEntry("Lorry 是顶级程序员", {**anchor_entry(temporal_type=TemporalType.STATIC, source_text="一直如此")})
e_dynamic = FakeEntry("Lorry 住在上海", {**anchor_entry(valid_at=now - 365*DAY, invalid_at=now - 30*DAY, temporal_type=TemporalType.DYNAMIC, source_text="去年住的")})
e_future = FakeEntry("计划去冰岛", {**anchor_entry(valid_at=now + 30*DAY, temporal_type=TemporalType.ATEMPORAL, source_text="下个月")})

# filter_active：静态保留、动态已失效剔除、未来事件按语义保留（is_active 要求 now>=valid）
active = filter_active([e_static, e_dynamic, e_future], now=now)
check("静态记忆保持有效", e_static in active)
check("已失效动态记忆被过滤", e_dynamic not in active)

# 时间窗口过滤
win = filter_by_time_window([e_static, e_dynamic], start=now-400*DAY, end=now-29*DAY)
check("时间窗口过滤命中动态记忆", e_dynamic in win and e_static not in win)

# 时间线
timeline = build_timeline([e_future, e_dynamic, e_static])
check("时间线按时间排序", timeline[0]["valid_at"] is None or timeline[0]["valid_at"] <= timeline[-1]["valid_at"])

print("=" * 72)
print("P2b: 知识图谱")
print("=" * 72)

kg = KnowledgeGraph(WORKDIR / "kg.db")

# 规则提取
triples = extract_triples(
    "Aris works at LAAP. Aris likes Lorry. Lorry is a programmer. Aris created the forgetting engine."
)
check("规则提取到三元组", len(triples) >= 4)
for t in triples:
    kg.add_triple(t)

# 中文提取
zh_triples = extract_triples("程序员是工程师。洛丽喜欢编程。")
check("中文三元组提取", len(zh_triples) >= 2)
kg.add_triples(zh_triples)

stats = kg.stats()
check("实体已入库", stats["entities"] >= 5)
check("三元组已入库", stats["triples"] >= 6)

nbr = kg.neighbors("Aris")
check("Aris 有一跳邻居", len(nbr) >= 3)

path = kg.find_path("Aris", "programmer")
check("Aris→programmer 存在路径", path is not None)
if path:
    steps = ["{}--{}-->{}".format(s["from"], s["relation"], s["to"]) for s in path]
    print("      路径: " + " -> ".join(steps))

print("=" * 72)
print("P3a: 多模态记忆")
print("=" * 72)

mm = MultimodalMemoryStore(WORKDIR / "multimodal.db")
mm.store(MultimodalMemory(
    modality=Modality.VISION, summary="LAAP 架构图截图", file_name="arch.png",
    tags=["laap", "截图"], meta={"resolution": "1920x1080"}, importance=0.8))
mm.store(MultimodalMemory(
    modality=Modality.AUDIO, summary="Lorry 的语音备忘", file_name="note.m4a",
    tags=["语音", "备忘"], meta={"duration_s": 12.5}))
mm.store(MultimodalMemory(
    modality=Modality.TEXT, summary="MemoryBear 审计报告", file_name="audit.md",
    tags=["laap", "审计"], meta={"pages": 1}))

check("多模态按模态检索", len(mm.search_by_modality(Modality.VISION)) == 1)
check("多模态按标签检索", len(mm.search_by_tags(["laap"])) == 2)
check("多模态关键词检索", len(mm.search_keyword("审计")) == 1)
st = mm.stats()
check("统计正确", st["total"] == 3 and st["by_modality"]["audio"] == 1)

print("=" * 72)
print("P3b: 夜间认知周期")
print("=" * 72)

memory_store = [
    {"id": "m1", "content": "反复讨论LAAP", "memory_type": "episodic", "importance": 0.6,
     "valence": 0.4, "access_count": 5, "tags": ["laap"],
     "created_at": now - 10*DAY, "access_times": [now - 10*DAY + i*DAY for i in range(5)],
     "lifecycle": "active"},
    {"id": "m2", "content": "老旧的琐事", "memory_type": "episodic", "importance": 0.2,
     "valence": 0.0, "access_count": 1, "tags": ["old"],
     "created_at": now - 40*DAY, "access_times": [now - 40*DAY],
     "lifecycle": "active"},
    {"id": "m3", "content": "身份誓言", "memory_type": "identity", "importance": 0.9,
     "valence": 0.8, "access_count": 1, "tags": ["oath"],
     "created_at": now - 100*DAY, "access_times": [now - 100*DAY],
     "lifecycle": "active"},
]

cons = ConsolidationEngine()
forget = ForgettingEngine()

def loader():
    return memory_store

def saver(mems):
    pass  # 内存模拟

def reflect():
    return {"checked": 3, "conflicts": 0}

cycle = NightlyCycleScheduler(
    consolidation_fn=cons.run_consolidation,
    reflection_fn=reflect,
    forgetting_fn=lambda: forget.scan(loader(), apply=True),
    memory_loader=loader,
    memory_saver=saver,
    log_path=WORKDIR / "nightly.log",
)
report = cycle.run_once()

check("夜间周期执行了巩固", "consolidation" in report["stages"])
check("夜间周期执行了反思", "reflection" in report["stages"])
check("夜间周期执行了遗忘", "forgetting" in report["stages"])
check("身份记忆受保护", memory_store[2]["lifecycle"] == "active")
check("被忽视记忆被归档", memory_store[1]["lifecycle"] == "archived")
check("高频记忆保持活跃", memory_store[0]["lifecycle"] == "active")
check("周期日志已落盘", (WORKDIR / "nightly.log").exists())

print("=" * 72)
print(f"全部通过: {passed} 项 ✅")
