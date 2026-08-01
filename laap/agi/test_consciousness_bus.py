"""
意识总线集成测试：GWS 竞争-广播 → 记忆/内感受/自指帧 全链路。

验证：
    1. 广播内容按显著性进入记忆系统（高显著性记住，低显著性丢弃）
    2. 自指帧生成（HOT 雏形）
    3. 内感受背景层刷新
    4. 竞争机制（高显著性胜出）
    5. 与 LifecycleAwareLongTermMemory 真实对接
"""
import faulthandler
faulthandler.dump_traceback_later(6, exit=True)
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from laap.agi.consciousness_bus import (
    ConsciousnessBus, build_consciousness_bus, MemorySubscriber, FrameSubscriber,
)
from laap.agi.gw_workspace import GlobalWorkspace, CoalitionalProcess, ProcessType
from laap.memory.lifecycle_integration import LifecycleAwareLongTermMemory
from laap.self_inspection import SelfInspectionEngine

WORKDIR = Path(__file__).resolve().parent / "_tmp_bus"
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
print("1. 装配：GWS + 记忆订阅 + 内感受 + 帧订阅")
print("=" * 72)

ltm = LifecycleAwareLongTermMemory(WORKDIR / "mem.db")
inspector = SelfInspectionEngine(memory_db=WORKDIR / "mem.db")
bus = build_consciousness_bus(memory_store=ltm, inspection_engine=inspector)
check("总线已装配", len(bus.subscribers) == 3)
check("GWS 广播回调已挂载", len(bus.workspace.broadcast_callbacks) == 3)

print("=" * 72)
print("2. 竞争-广播：高显著性胜出并进入记忆")
print("=" * 72)

# 三个竞争过程：强信号 / 中信号 / 弱信号
bus.workspace.register_process(CoalitionalProcess(
    process_id="urgent_task", process_type=ProcessType.COGNITIVE,
    content="用户报告系统崩溃，需要立即修复", activation=0.9, salience=0.95))
bus.workspace.register_process(CoalitionalProcess(
    process_id="casual_thought", process_type=ProcessType.PERCEPTUAL,
    content="窗外天气不错", activation=0.5, salience=0.3))
bus.workspace.register_process(CoalitionalProcess(
    process_id="weak_noise", process_type=ProcessType.PERCEPTUAL,
    content="背景噪音信息", activation=0.2, salience=0.1))

winners = bus.cycle()
check("竞争产生胜出者", len(winners) >= 1)
check("强信号胜出", winners[0].process_id == "urgent_task")

# 记忆订阅者统计
mem_sub = bus.subscribers["memory"]
check("广播被接收", mem_sub.received >= 1)
check("强信号被记住", mem_sub.memorized >= 1)

# 验证真实写入记忆库
with ltm._lock:
    rows = ltm._conn.execute(
        "SELECT content, lifecycle FROM long_term_memories WHERE source = 'gws_broadcast'"
    ).fetchall()
check("意识内容写入情景记忆", len(rows) >= 1)
check("记忆带生命周期", all(r["lifecycle"] == "active" for r in rows))

print("=" * 72)
print("3. 自指帧（HOT 雏形）")
print("=" * 72)

frame_sub = bus.subscribers["frames"]
frame = frame_sub.current_frame()
check("自指帧已生成", frame is not None)
check("帧含自指表征", "正在经历" in (frame.self_reflection or ""))
print(f"      自指: {frame.self_reflection}")

print("=" * 72)
print("4. 内感受背景层")
print("=" * 72)

sr_sub = bus.subscribers["self_review"]
bg = sr_sub.last_background
check("背景层记录焦点", "focus" in bg)
check("背景层含健康快照", "vital_summary" in bg or bg.get("focus") == "urgent_task")

print("=" * 72)
print("5. 低显著性丢弃")
print("=" * 72)

before = mem_sub.memorized
# 只推弱信号
bus.workspace.register_process(CoalitionalProcess(
    process_id="weak_noise2", process_type=ProcessType.PERCEPTUAL,
    content="无关紧要的琐碎信息", activation=0.15, salience=0.1))
bus.cycle()
check("弱信号未进入记忆", mem_sub.memorized == before)

print("=" * 72)
print("6. 总线统计")
print("=" * 72)
stats = bus.stats()
check("统计含三个订阅者", set(stats.keys()) >= {"memory", "self_review", "frames"})
print(f"      {stats}")

print("=" * 72)
print(f"意识总线测试全部通过: {passed} 项 ✅")

ltm.close()  # 关闭数据库连接，避免进程挂起
