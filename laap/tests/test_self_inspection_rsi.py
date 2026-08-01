"""
自我审视 × RSI 桥接测试。

验证：
    1. 健康状态下 fitness_signal 高（≈0.95）
    2. 模拟问题后信号下降、目标模块正确映射
    3. 黑名单模块不会被提议改进
    4. 建议包结构完整
    5. 完整闭环（建议模式）可运行
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from laap.self_inspection import SelfInspectionEngine
from laap.self_inspection_rsi import RSIFeedbackBridge

passed = 0
def check(name, cond):
    global passed
    assert cond, f"FAIL: {name}"
    passed += 1
    print(f"  [PASS] {name}")

bridge = RSIFeedbackBridge(inspection_engine=SelfInspectionEngine(), agent_name="aris")

print("=" * 72)
print("1. 健康状态：信号应该高")
print("=" * 72)

# 构造一个全健康报告（绕过真实体检）
healthy = {
    "vitals": [
        {"name": "memory.long_term", "label": "长期记忆", "status": "ok", "detail": ""},
        {"name": "cognition.brain", "label": "认知大脑", "status": "ok", "detail": ""},
    ],
    "memory_health": {"long_term": {"total": 100, "lifecycle": {"active": 90, "archived": 5}, "avg_importance": 0.7}},
    "summary": {"total_systems": 2, "ok": 2, "warning": 0, "missing": 0, "degraded": 0},
}
sig = bridge.compute_fitness_signal(healthy)
check("健康状态信号 ≥ 0.9", sig["signal"] >= 0.9)
print(f"      signal={sig['signal']}")

print("=" * 72)
print("2. 问题状态：信号下降 + 目标映射")
print("=" * 72)

sick = {
    "vitals": [
        {"name": "memory.long_term", "label": "长期记忆", "status": "ok", "detail": ""},
        {"name": "cognition.truth_grounding", "label": "事实锚定引擎", "status": "missing", "detail": "导入失败: xyz"},
        {"name": "memory.nightly_cycle", "label": "夜间周期", "status": "degraded", "detail": "异常"},
    ],
    "memory_health": {"long_term": {"total": 100, "lifecycle": {"active": 30, "archived": 60}, "avg_importance": 0.35}},
    "summary": {"total_systems": 3, "ok": 1, "warning": 0, "missing": 1, "degraded": 1},
}
sig2 = bridge.compute_fitness_signal(sick)
check("问题状态信号明显下降", sig2["signal"] < 0.6)
check("记忆流失被计入扣分", any("归档" in r for r in sig2["reasons"]))
print(f"      signal={sig2['signal']}, reasons={sig2['reasons']}")

sugs = bridge.map_issues_to_targets(sick)
# truth_grounding 含 grounding 在黑名单（安全关键模块不可自改）→ 2 条建议
check("问题被映射为改进建议", len(sugs) == 2)
targets = [s.target_module for s in sugs]
check("truth_grounding 被黑名单保护（不可自改）", "laap/cognition/truth_grounding.py" not in targets)
check("夜间周期映射到 laap/memory/", "laap/memory/nightly_cycle.py" in targets)
check("遗忘引擎因归档率高被建议", "laap/memory/forgetting/engine.py" in targets)

print("=" * 72)
print("3. 黑名单保护")
print("=" * 72)

black = {
    "vitals": [
        {"name": "cognition.truth_grounding", "label": "事实锚定引擎", "status": "missing", "detail": "x"},
        {"name": "evolution.rsi", "label": "RSI引擎", "status": "degraded", "detail": "x"},
        {"name": "memory.forgetting.lifecycle", "label": "生命周期", "status": "warning", "detail": "x"},
        {"name": "self_inspection", "label": "自我审视", "status": "degraded", "detail": "x"},
        {"name": "memory.nightly_cycle", "label": "夜间周期", "status": "degraded", "detail": "x"},
    ],
    "memory_health": {"long_term": {}},
    "summary": {},
}
sugs_b = bridge.map_issues_to_targets(black)
check("黑名单模块被过滤", all("rsi" not in s.target_module for s in sugs_b))
check("黑名单模块被过滤2", all("lifecycle" not in s.target_module for s in sugs_b))
check("黑名单模块被过滤3", all("self_inspection" not in s.target_module for s in sugs_b))
check("白名单模块仍保留", any("nightly_cycle" in s.target_module for s in sugs_b))

print("=" * 72)
print("4. 完整建议包")
print("=" * 72)
pkg = bridge.suggest_improvements(sick)
check("建议包含信号", "fitness_signal" in pkg)
check("建议包含理由", len(pkg["signal_reasons"]) > 0)
check("建议包含改进清单", len(pkg["suggestions"]) >= 2)

print("=" * 72)
print(f"全部通过: {passed} 项 ✅")
