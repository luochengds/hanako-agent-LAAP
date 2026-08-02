# Hanako-LAAP 认知 Runtime 对照试验

更新时间：2026-08-02

## 试验目的

比较当前两套认知 Runtime：

```text
BridgeCognitiveRuntime
AGIAgentCognitiveRuntime
```

确认哪一套更适合作为后续唯一主体认知核心。

## 试验原则

- 两套 Runtime 接收完全相同的输入 fixture；
- 使用隔离的 AGIAgent state_dir；
- 不调用真实 LLM；
- 不修改生产记忆和生产状态；
- 比较认知报告、需求变化、注意力变化和状态恢复；
- 不把语言表达质量混入本轮认知引擎比较。

## 运行工具

```text
scripts/compare_cognitive_runtimes.py
```

运行：

```powershell
cd E:\worke\hanako-agent-LAAP
.\.venv\Scripts\python.exe scripts/compare_cognitive_runtimes.py `
  --output "$env:TEMP\laap-cognitive-compare.json"
```

## 默认输入样本

共 6 条：

1. 普通问候与自我介绍；
2. 系统风险分析；
3. 焦虑情绪表达；
4. 记忆主体性原则；
5. 工具失败处理；
6. 安全自我改进建议。

## 第一轮结果：基础成功率

```text
Bridge：6/6 成功
AGIAgent：6/6 成功
```

## 第二轮结果：认知状态变化

### Bridge

返回状态主要包括：

```text
meta
parliament
unity
version
```

默认 fallback 下没有可比较的完整需求/注意力状态变化。

### AGIAgent

返回：

```text
cognitive_state
needs
emotion
attention
conscious
causal
autonomy
self_assessment
prediction
```

需求首末变化：

```text
competence：-0.003
autonomy：-0.002
relatedness：-0.007
certainty：-0.014
growth：+0.007
```

注意力：

```text
首轮：learning
末轮：task
```

结论：AGIAgent 产生了可观测的需求和注意力变化；Bridge fallback 主要提供基础认知桥接状态。

## 第三轮结果：状态恢复

初次对照发现：AGIAgent 能恢复 `total_interactions`，但世界模型和 CognitiveBus 的稳定摘要未完全一致。

已修复：

- `AGIAgent.save()` 持久化 CognitiveBus；
- `AGIAgent` 启动时恢复 CognitiveBus；
- `AbstractWorldModel` 增加统一 `save/load` façade；
- LocalWorldModel 的世界实体通过 UnifiedWorldModel 持久化。

修复后结果：

```text
保存状态：成功
新实例加载：成功
total_interactions：6
stable_summary_matches：True
world_entities：12 → 12
cognitive_bus_cycles：12 → 12
```

Bridge：

```text
无独立 AGIAgent 状态恢复能力
```

结论：AGIAgent 已具备可验证的认知状态、世界模型和 CognitiveBus 重载能力。

## 第四轮结果：需求、情绪、注意力恢复

继续比较重载前后的 CognitiveBus 状态，忽略运行时间戳后，比较：

```text
needs：一致
emotion：一致
attention.focus：一致
attention.intensity：一致
attention.top_salient：一致
self_presence：一致
curiosity：一致
narrative：一致
```

结果：

```text
cognitive_state equality：True
stable_summary_matches：True
```

本轮发现并修复一个细节：注意力的 `top_salient` 在保存后被写出，但加载时没有恢复到 `salience_map`。修复后注意力状态实现完整恢复。

## 第五轮结果：长期记忆内容恢复

新增唯一记忆探针：

```text
persistence probe unique memory marker
```

AGIAgent 保存并重载后，通过 `UnifiedMemory.query()` 检索：

```text
restored_query_match：True
stable_summary_matches：True
```

这确认恢复的不只是记忆计数，具体 episodic memory 内容也可以被重新检索。

进一步加入 semantic 与 procedural 探针：

```text
semantic_probe_restored：True
procedural_probe_restored：True
second_reload_summary_matches：True
```

结果表明三类记忆都可恢复，且连续两次重载不会改变稳定摘要，当前实验未发现重复加载导致的状态膨胀。

## 第七轮结果：异常与重复写入

异常探针结果：

```text
duplicate_memory_count_after_reload：2
duplicate_write_is_append_semantics：True
corrupt_main_state_load_result：False
corrupt_state_does_not_raise：True
```

结论：重复写入当前是明确的 append 语义，而不是自动去重；损坏的主状态文件会返回加载失败，但不会向调用方抛出异常。后续需要决定是否增加记忆内容去重策略，以及是否提供更明确的 degraded recovery 状态。

## 第八轮结果：部分状态文件缺失

删除单个 sidecar 后，当前 `AGIAgent.load()` 仍返回 `True`：

```text
缺失 world_model.json：load=True，世界模型回到初始化状态
缺失 unified_memory.json：load=True，episodic memory 回到 0
缺失 cognitive_bus_state.json：load=True，bus cycles 回到 0
```

这说明主状态文件与 sidecar 的恢复目前是“尽力加载”语义，但没有向调用方暴露降级信息。现已增加结构化 `load_status`，报告每个状态层的 `loaded/missing/corrupt` 状态和总的 `degraded` 标志：

```json
{
  "main_state": "loaded",
  "world_model": "missing",
  "unified_memory": "loaded",
  "cognitive_bus": "loaded",
  "degraded": true
}
```

`load()` 继续保持兼容，返回值表示主状态是否可读取；详细恢复质量通过 `get_state()["load_status"]` 获取。

进一步验证损坏 sidecar：

```text
损坏 world_model.json：main_state=loaded，world_model=corrupt，degraded=True
损坏 unified_memory.json：main_state=loaded，unified_memory=corrupt，degraded=True
```

sidecar 损坏不会再被误报为主状态损坏，也不会阻断其他状态层恢复。

## 第九轮结果：严格降级门

统一 `AGIAgentCognitiveRuntime` 新增严格持久化模式：

```powershell
$env:LAAP_PERSISTENCE_STRICT="1"
```

或在代码中显式创建：

```python
AGIAgentCognitiveRuntime(agent, strict_persistence=True)
```

当 `load_status.degraded=True` 时，主体 turn 会被阻断；完整状态时正常放行。

实验结果：

```text
缺失 unified_memory.json：blocked
```

默认模式仍保持兼容，不会因为首次启动没有历史状态而阻断；严格模式只针对已有主状态但 sidecar 缺失或损坏的情况生效。

## 当前判断

从本轮指标看：

```text
BridgeCognitiveRuntime
  优点：轻量、兼容、启动快、风险低
  缺点：fallback 认知状态较少，持续状态能力弱

AGIAgentCognitiveRuntime
  优点：认知模块完整，需求/情绪/注意力可观测，支持状态恢复
  缺点：初始化更重，依赖更多，尚未完成生产默认切换
```

当前推荐：

```text
生产默认：暂时保持 Bridge
认知验证：使用 AGIAgent
下一阶段：完成 PSIDriver canonical 接入，再做 shadow mode
```

## 试验边界说明

本报告验证的是 **BridgeCognitiveRuntime 与 AGIAgentCognitiveRuntime 的行为、状态和持久化对照**，不是 `laap.agi.PSIDriver` 六阶段循环已经成为 canonical core 的证明。

当前源码事实是：`AGIAgent.process_interaction(use_psi=True)` 运行的是 `AGIAgent.core` 自己的 CognitiveBus/PSI 阶段；`PSIDriver` 虽被导入，但尚未作为唯一 driver 接管该入口。因此：

```text
对照试验：已完成
AGIAgent 持久化恢复：已完成
需求/情绪/注意力/三类记忆恢复：已完成
异常/缺失/损坏/严格降级门：已完成
AGIAgent/PSIDriver/Bridge 唯一核心收敛：未完成
完整 PSIDriver 六阶段接入且避免双重循环：未完成
Shadow mode：未完成
```

## Git 记录

对照试验工具及结果记录提交：

```text
e304445  test: add cognitive runtime comparison harness
844cfcf  test: compare cognitive state deltas
0b2016d  test: compare cognitive runtime state recovery
```
