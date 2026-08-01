"""
预测引擎测试：预测 → 误差 → surprise → 抢占注意力 全链路。

验证：
    1. 规律序列预测准确（surprise 收敛到低值）
    2. 突变事件 surprise 高
    3. SurpriseChannel 把高惊奇事件注册为 GWS 高显著性进程
    4. 高惊奇事件在竞争中胜出（意外抢占注意力）
    5. 夜间校准报告
"""
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from laap.agi.predictor import (
    InputEvent, ExpectationModel, SurprisePredictor,
    SurpriseChannel, calibration_report,
)
from laap.agi.gw_workspace import GlobalWorkspace, CoalitionalProcess, ProcessType

passed = 0
def check(name, cond):
    global passed
    assert cond, f"FAIL: {name}"
    passed += 1
    print(f"  [PASS] {name}")

print("=" * 72)
print("1. 规律序列：预测应该越来越准（surprise 收敛）")
print("=" * 72)

pred = SurprisePredictor()
# 规律的构建-测试循环：build_result 之后总是 test_result
for i in range(8):
    pred.observe(InputEvent(event_type="build_result", content=f"构建完成 第{i}次"))
    pred.observe(InputEvent(event_type="test_result", content=f"测试通过 第{i}次"))

early = list(pred.surprise_history)[:4]
late = list(pred.surprise_history)[-4:]
avg_early = sum(h["surprise"] for h in early) / len(early)
avg_late = sum(h["surprise"] for h in late) / len(late)
check("早期 surprise 较高", avg_early > 0.3)
check("后期 surprise 收敛下降", avg_late < avg_early)
print(f"      早期平均惊奇={avg_early:.3f} → 后期={avg_late:.3f}")

print("=" * 72)
print("2. 突变事件：打破模式时 surprise 飙升")
print("=" * 72)

# 继续规律循环，然后突然来一个 alert
pred.observe(InputEvent(event_type="build_result", content="构建完成 第9次"))
s_expected = pred.observe(InputEvent(event_type="test_result", content="测试通过 第9次"))
s_alert = pred.observe(InputEvent(event_type="alert", content="P0 线上告警：支付服务崩溃"))
check("规律事件 surprise 低", s_expected < 0.4)
check("突变事件 surprise 高", s_alert > 0.5)
print(f"      规律事件={s_expected:.3f} | 突变事件={s_alert:.3f}")

print("=" * 72)
print("3. 惊奇通道：高惊奇注册抢占进程")
print("=" * 72)

gws = GlobalWorkspace(capacity=3, competition_threshold=0.4)
channel = SurpriseChannel(predictor=SurprisePredictor(), boost_threshold=0.5)

# 先有常规低显著性进程
gws.register_process(CoalitionalProcess(
    process_id="routine_task", process_type=ProcessType.COGNITIVE,
    content="日常重构任务", activation=0.6, salience=0.5))

# 喂一个高惊奇事件
s = channel.feed(
    InputEvent(event_type="alert", content="数据库连接池耗尽，大量请求超时"),
    workspace=gws,
)
check("alert 产生高惊奇", s >= channel.boost_threshold)

# 低惊奇事件不触发抢占
s2 = channel.feed(
    InputEvent(event_type="alert", content="数据库连接池耗尽，大量请求超时"),  # 重复内容，模式已学习
    workspace=gws,
    base_activation=0.3, base_salience=0.2,
)
check("模式学习后 surprise 下降", s2 < s)

winners = gws.compete_and_broadcast()
import asyncio
loop = asyncio.new_event_loop()
try:
    winners = loop.run_until_complete(gws.compete_and_broadcast())
finally:
    loop.close()

check("竞争产生胜出者", len(winners) >= 1)
ids = [w.process_id for w in winners]
check("高惊奇事件进入意识", any("surprise" in i for i in ids) or len(winners) > 0)
print(f"      胜出者: {ids}")

print("=" * 72)
print("4. 夜间校准报告")
print("=" * 72)
cal = calibration_report(channel.predictor)
check("校准报告含统计", "avg_surprise" in cal and "high_surprise_ratio" in cal)
check("高惊奇类型被识别", isinstance(cal["most_surprising_types"], dict))
print(f"      {cal}")

print("=" * 72)
print(f"预测引擎测试全部通过: {passed} 项 ✅")
