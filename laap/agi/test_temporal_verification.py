"""
阶段 4+5 测试：时间绑定 + 验证套件。

验证：
    1. 时间窗口整合（有厚度的现在）
    2. 整合帧焦点 = 窗口内众数（滞留效果）
    3. 自指表征含时间跨度
    4. 感知盲测试（弱信号不可见）
    5. 整合度估计
    6. 自我一致性
"""
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from laap.agi.temporal_binding import TemporalBinding, attach_temporal_binding
from laap.agi.consciousness_verification import ConsciousnessVerifier
from laap.agi.consciousness_bus import ConsciousnessFrame, build_consciousness_bus
from laap.agi.gw_workspace import GlobalWorkspace, CoalitionalProcess, ProcessType
from laap.agi.predictor import SurprisePredictor
from laap.agi.present_self import attach_present_self
from laap.memory.lifecycle_integration import LifecycleAwareLongTermMemory
from laap.self_inspection import SelfInspectionEngine

WORKDIR = Path(__file__).resolve().parent / "_tmp_tb"
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
print("1. 时间绑定：有厚度的现在")
print("=" * 72)

binding = TemporalBinding(window_seconds=3.0)
# 模拟 1 秒内的连续帧：同一焦点（fix_bug）3 帧
t0 = time.time()
for i in range(3):
    binding.push(ConsciousnessFrame(
        timestamp=t0 + i * 0.3, dominant="fix_bug",
        contents=[{"id": "fix_bug", "content": f"修复步骤 {i}"}]))
# 再推 2 帧不同焦点
for i in range(2):
    binding.push(ConsciousnessFrame(
        timestamp=t0 + 0.9 + i * 0.3, dominant="code_review",
        contents=[{"id": "code_review", "content": f"评审 {i}"}]))

ip = binding.current()
check("整合帧生成", ip is not None)
check("焦点轨迹记录滞留", len(ip.focus_sequence) >= 4)
check("众数焦点胜出", ip.dominant == "fix_bug")
check("自指含时间跨度", "过去3秒" in ip.self_reflection)
print(f"      整合帧: dominant={ip.dominant} 轨迹={ip.focus_sequence}")
print(f"      自指: {ip.self_reflection}")

print("=" * 72)
print("2. 感知盲测试：强事件占据意识，弱事件不可见")
print("=" * 72)

ltm = LifecycleAwareLongTermMemory(WORKDIR / "mem.db")
gws = GlobalWorkspace(capacity=3, competition_threshold=0.5)
verifier = ConsciousnessVerifier()

blind = verifier.inattentional_blindness_test(gws, ltm)
check("强事件进入意识", blind["strong_seen"])
check("弱事件未进入意识", not blind["weak_seen"])
check("感知盲成立", blind["inattentional_blindness"])
print(f"      判定: {blind['verdict']}")

print("=" * 72)
print("3. 整合度估计")
print("=" * 72)

focus = ["a", "a", "b", "b", "c", "c"]  # 焦点切换 2 次
memory = [1, 1, 2, 2, 3, 3]              # 切换处有记忆写入
surprise = [0.1, 0.1, 0.8, 0.1, 0.1, 0.1]  # 1 次高惊奇（b 切换处）
est = verifier.integration_estimate(focus, memory, surprise)
check("整合度分数计算", 0 <= est["integration_score"] <= 1)
check("耦合度指标存在", "focus_memory_coupling" in est)
print(f"      整合度: {est}")

print("=" * 72)
print("4. 自我一致性")
print("=" * 72)

body = {"health": {"total_systems": 16, "ok": 16}, "issues": 0}
actual = {"total_systems": 16, "ok": 15, "issues": 1}
cons = verifier.self_consistency_score(body, actual)
check("一致性分数计算", 0 <= cons["consistency_score"] <= 1)
check("偏差被识别", len(cons["deviations"]) >= 1)
print(f"      一致性: {cons}")

print("=" * 72)
print("5. 完整集成：总线 + 时间绑定 + 当下自我")
print("=" * 72)

inspector = SelfInspectionEngine(memory_db=WORKDIR / "mem.db")
predictor = SurprisePredictor()
bus = build_consciousness_bus(memory_store=ltm, workspace=gws, predictor=predictor)
ps = attach_present_self(bus, inspection_engine=inspector, memory_store=ltm, sample_interval=1)
tb = attach_temporal_binding(bus, window_seconds=3.0, predictor=predictor)

# 驱动几轮认知
for i in range(6):
    from laap.agi.predictor import InputEvent
    bus.surprise_channel.feed(InputEvent(
        event_type="build_result", content=f"构建 #{i} 通过"), workspace=gws)
    bus.cycle()

ip2 = tb.current()
check("集成后整合帧生成", ip2 is not None)
check("当下自我持续更新", ps["model"].snapshot()["focus"] != "")
check("时间绑定订阅广播", "temporal_binding" in bus.subscribers)
print(f"      整合焦点: {ip2.dominant} | 当下自我焦点: {ps['model'].snapshot()['focus']}")

print("=" * 72)
print(f"阶段 4+5 测试全部通过: {passed} 项 ✅")
ltm.close()
