"""
阶段 2 端到端验证：预测引擎 × 意识总线 × 记忆系统 全链路。

场景：一个"编程日"——
  规律事件流（build → test 循环）→ 预测器学会模式（surprise 收敛）
  突发 P0 告警 → 高惊奇 → 抢占注意力 → 广播 → 写入记忆
"""
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from laap.agi.consciousness_bus import build_consciousness_bus
from laap.agi.predictor import InputEvent, SurprisePredictor, calibration_report
from laap.agi.gw_workspace import GlobalWorkspace, CoalitionalProcess, ProcessType
from laap.memory.lifecycle_integration import LifecycleAwareLongTermMemory

WORKDIR = Path(__file__).resolve().parent / "_tmp_predictor_e2e"
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
print("装配：总线 + 预测器 + 真实记忆库")
print("=" * 72)

ltm = LifecycleAwareLongTermMemory(WORKDIR / "mem.db")
predictor = SurprisePredictor()
gws = GlobalWorkspace(capacity=3, competition_threshold=0.5)
bus = build_consciousness_bus(memory_store=ltm, workspace=gws, predictor=predictor)
check("预测器挂入总线", bus.surprise_channel is not None)
check("预测器订阅广播", "predictor" in bus.subscribers)

print("=" * 72)
print("编程日：规律事件流（build→test）×6")
print("=" * 72)

for i in range(6):
    bus.surprise_channel.feed(
        InputEvent(event_type="build_result", content=f"构建成功 #{i} 全部通过"),
        workspace=gws)
    bus.surprise_channel.feed(
        InputEvent(event_type="test_result", content=f"测试通过 #{i} 42个用例"),
        workspace=gws)

stats = predictor.stats()
check("预测器已学习事件流", stats["events"] == 12)
check("平均惊奇下降", stats["avg_surprise"] < 0.5)
print(f"      平均惊奇: {stats['avg_surprise']}")

print("=" * 72)
print("突发：P0 告警抢占注意力")
print("=" * 72)

s = bus.surprise_channel.feed(
    InputEvent(event_type="alert", content="P0 线上告警：支付服务 500 错误激增"),
    workspace=gws,
    base_activation=0.6, base_salience=0.5,
)
check("P0 告警高惊奇", s >= 0.5)
check("已注册抢占进程", bus.surprise_channel.boosted_count >= 1)

# 驱动竞争-广播
winners = bus.cycle()
ids = [w.process_id for w in winners]
check("告警进入意识广播", any("surprise" in i for i in ids))
print(f"      意识焦点: {ids}")

print("=" * 72)
print("广播流向：告警内容写入记忆")
print("=" * 72)

with ltm._lock:
    rows = ltm._conn.execute(
        "SELECT content, source, lifecycle FROM long_term_memories WHERE source = 'gws_broadcast'"
    ).fetchall()
check("意识内容已写入记忆", len(rows) >= 1)
contents = " ".join(r["content"] for r in rows)
check("告警内容被记住", "支付服务" in contents or "P0" in contents)
print(f"      记忆条目: {len(rows)} 条")

print("=" * 72)
print("夜间校准报告")
print("=" * 72)

cal = calibration_report(predictor)
check("校准报告生成", cal["events"] > 0)
print(f"      事件={cal['events']} 平均惊奇={cal['avg_surprise']} "
      f"高惊奇占比={cal['high_surprise_ratio']}")
print(f"      最意外类型: {cal['most_surprising_types']}")

print("=" * 72)
print(f"阶段 2 端到端全部通过: {passed} 项 ✅")
ltm.close()
