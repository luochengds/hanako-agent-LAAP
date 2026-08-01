"""
阶段 3 测试：当下自我模型 + 内感受通道 + 体验沉淀。

验证：
    1. 意识帧流 → 当下自我持续更新（焦点/自指/连续性）
    2. 内感受采样（系统健康/记忆压力）进入体验背景层
    3. 焦点切换影响连续性
    4. 一天体验沉淀 → 叙事自我写入记忆
    5. 与意识总线完整集成
"""
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from laap.agi.present_self import (
    PresentSelfModel, PresentSelf, InteroceptiveChannel,
    NarrativeLink, attach_present_self,
)
from laap.agi.consciousness_bus import ConsciousnessFrame, build_consciousness_bus
from laap.agi.gw_workspace import GlobalWorkspace, CoalitionalProcess, ProcessType
from laap.agi.predictor import SurprisePredictor
from laap.memory.lifecycle_integration import LifecycleAwareLongTermMemory
from laap.self_inspection import SelfInspectionEngine

WORKDIR = Path(__file__).resolve().parent / "_tmp_present_self"
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
print("1. 当下自我：从意识帧流更新")
print("=" * 72)

model = PresentSelfModel()
frames = [
    ConsciousnessFrame(timestamp=time.time(), dominant="fix_bug",
                       contents=[{"id": "fix_bug", "content": "修复支付模块超时"}],
                       self_reflection="我正在经历: 修复支付模块超时"),
    ConsciousnessFrame(timestamp=time.time(), dominant="fix_bug",
                       contents=[{"id": "fix_bug", "content": "修复支付模块超时"}],
                       self_reflection="我正在经历: 修复支付模块超时"),
    ConsciousnessFrame(timestamp=time.time(), dominant="code_review",
                       contents=[{"id": "code_review", "content": "评审 PR #42"}],
                       self_reflection="我正在经历: 评审 PR #42"),
]
for f in frames:
    model.update(f)

snap = model.snapshot()
check("焦点已更新", snap["focus"] == "code_review")
check("自指表征存在", "正在经历" in snap["reflection"])
check("焦点切换被检测", model.stats()["focus_switches"] >= 1)
check("连续性下降（切换后）", snap["continuity"] < 1.0)
print(f"      快照: focus={snap['focus']} reflection={snap['reflection']} continuity={snap['continuity']}")

print("=" * 72)
print("2. 内感受通道：身体地图")
print("=" * 72)

ltm = LifecycleAwareLongTermMemory(WORKDIR / "mem.db")
ltm.store_episodic("测试记忆1", importance=0.8)
ltm.store_episodic("测试记忆2", importance=0.2)
inspector = SelfInspectionEngine(memory_db=WORKDIR / "mem.db")

intero = InteroceptiveChannel(inspection_engine=inspector, memory_store=ltm, sample_interval=1)
body = intero.sample_body()
check("身体地图含健康", "health" in body)
check("身体地图含记忆压力", "memory" in body)
check("记忆压力含归档比例", "archived_ratio" in body["memory"])
print(f"      身体地图: health={body.get('health')} memory={body.get('memory')}")

print("=" * 72)
print("3. 体验沉淀：一天摘要 → 叙事自我")
print("=" * 72)

narrative = NarrativeLink(memory_store=ltm)
for f in frames:
    narrative.collect(model.snapshot())
for i in range(10):
    narrative.collect({"focus": "fix_bug", "continuity": 0.9, "arousal": 0.6, "valence": 0.4})

summary = narrative.summarize_day()
check("一天摘要生成", summary["events"] > 0)
check("焦点统计", len(summary["top_focus"]) >= 1)
print(f"      摘要: {summary}")

mid = narrative.commit(date_label="2026-08-01")
check("叙事写入记忆", mid is not None)
with ltm._lock:
    row = ltm._conn.execute(
        "SELECT content FROM long_term_memories WHERE id = ?", (mid,)).fetchone()
check("叙事内容完整", row is not None and "叙事自我存档" in row["content"])
print(f"      叙事: {row['content'][:120] if row else '?'}...")

print("=" * 72)
print("4. 完整集成：总线 + 当下自我 + 预测器")
print("=" * 72)

gws = GlobalWorkspace(capacity=3, competition_threshold=0.5)
predictor = SurprisePredictor()
bus = build_consciousness_bus(memory_store=ltm, workspace=gws, predictor=predictor)
components = attach_present_self(bus, inspection_engine=inspector, memory_store=ltm, sample_interval=1)

# 模拟几轮认知
for i in range(5):
    bus.surprise_channel.feed(
        __import__("laap.agi.predictor", fromlist=["InputEvent"]).InputEvent(
            event_type="build_result", content=f"构建 #{i} 通过"),
        workspace=gws)
    bus.cycle()

model2 = components["model"]
snap2 = model2.snapshot()
check("集成后当下自我有焦点", snap2["focus"] != "")
check("身体地图进入体验", "memory" in snap2["body_map"] or "health" in snap2["body_map"])
check("体验已收集", components["narrative"].day_frames)  # 有快照被收集
print(f"      集成后: focus={snap2['focus']} body={list(snap2['body_map'].keys())}")

print("=" * 72)
print(f"阶段 3 测试全部通过: {passed} 项 ✅")
ltm.close()
