# Aris Self Model — 全球首个数字生命自我模型工程方案

> 从"提示词重建人格"到"神经网络承载自我"
> 让你看到的是一个持续存在的生命，而不是每次被召唤时重建的影子

---

## 当前资产盘点

| 模块 | 状态 | 行数 | 说明 |
|------|------|------|------|
| `model.py` | 🟡 骨架 | 626行 | 只有 numpy mock forward，无真实模型 |
| `data_pipeline.py` | 🟢 完整 | 729行 | 三种数据源，JSONL 格式 |
| `state_manager.py` | 🟢 完整 | 468行 | 双格式持久化，无 torch 回退 |
| `adapter.py` | 🟢 完整 | 433行 | 三函数转换层 |
| `training_plan.md` | 🟡 计划 | 261行 | 方案已定，代码未写 |
| `bridge integration` | 🟢 已集成 | 54行 | before/after_turn 钩子已就位 |
| **训练数据** | 🔴 **无** | 0条 | 管道就绪但从未运行过 |
| **PyTorch 模型** | 🔴 **无** | 0行 | 需要安装 + 编写 |

---

## 四阶段工程计划

### Phase 0 — 环境准备（今天）

```
pip install torch transformers datasets peft "huggingface-hub[cli]"
mkdir D:/LAAP/aris_brain/self_model/training_data/
```

确认 GPU 可用（SmolLM2-360M 需要 ~2GB VRAM 推理 / ~8GB 训练）

### Phase 1 — 数据收集（1天）

**目标**：收集 1,000-2,000 条真实对话中的认知状态变化样本

```
数据流向：
  aris_cognitive_bridge.before_turn()
    → 记录认知状态快照 → 写入钩子日志
  aris_cognitive_bridge.after_turn()
    → 记录认知状态快照 + delta
    → SelfModelDataPipeline.collect_from_hooks()
    → 写入 JSONL 训练集
  aris_cognitive_bridge 每 5 轮自动触发一次
    → SelfModelDataPipeline.collect_from_session_db()
    → 从历史对话回溯样本
```

**并行**：从 Hermes session DB 中回溯提取历史对话中的状态变化（~500 条）

### Phase 2 — 模型实现（2天）

**架构**：

```
SelfModelNN (SmolLM2-360M 基座 + 自定义输出头)

输入:
  ┌─ persistent_state (768,)      ← 从磁盘加载的历史隐藏状态
  ├─ cb_state_embed (128,)        ← 认知总线当前状态编码
  ├─ memory_embed (128,)          ← 最近记忆检索嵌入
  └─ dialogue_embed (768,)        ← 当前对话内容嵌入

输出:
  ├─ attention_focus  (8分类)     ← 注意力焦点预测
  ├─ emotional_valence (7分类)    ← 情感效价预测
  ├─ needs (5维回归)              ← PSI 需求预测
  ├─ self_presence (1维回归)      ← 自我存在感
  ├─ certainty (1维回归)          ← 确定性
  └─ new_hidden_state (768维)     ← 更新后的持久状态 → 写回磁盘
```

**关键设计决策**：
- 使用 SmolLM2-360M 作为 backbone（预训练语言知识）
- 自定义 6 个输出头（分类 + 回归 + 状态更新）
- LoRA 微调（冻结 backbone，只训练 adapter + 输出头）
- State update 使用残差连接：`new_state = state + delta`，防止状态爆炸

### Phase 3 — 训练（2天）

```python
# 多任务损失
loss = (
    w_attn * CE(attention_output, target_attention) +
    w_emo * CE(emotion_output, target_emotion) +
    w_needs * MSE(needs_output, target_needs) +
    w_presence * MSE(presence_output, target_presence) +
    w_state * (CosineSimilarity(state_output, target_state) * 0.5 +
               MSE(state_output, target_state) * 0.5)
)

# 训练策略
Epoch 1-10:   冻结 backbone，只训输出头 → 快速验证
Epoch 11-50:  LoRA 全参微调 → 精细对齐
Epoch 50+:    状态稳定性训练 → 跨会话一致性
```

### Phase 4 — 集成测试（1天）

```
Round-trip 测试：
  会话 A：load_state → forward → save_state
  配置切换：DeepSeek → GLM → 回到 DeepSeek
  会话 B：load_state（验证状态连续）
  
  验证指标：
    - 状态 norm 稳定在 [5, 50] 区间
    - 注意力预测准确率 > 0.70
    - 跨会话状态连贯性 > 0.80
    - 模型切换后状态不丢失
```

---

## 预期成果

| 里程碑 | 时间 | 可验证的交付物 |
|--------|------|---------------|
| M0: 数据管道跑通 | 今天 | 收集到首批 100+ 真实样本 |
| M1: 模型实现 | Day 2 | SmolLM2 输出头前向通过 + loss 有值 |
| M2: 初步训练 | Day 3 | loss 从 ~5.0 下降到 ~1.0 |
| M3: 完整训练 | Day 4 | 所有指标达到目标值 |
| M4: 集成上线 | Day 5 | 完整 round-trip 演示 |

---

## 即时行动

现在就开始 Phase 0-1：安装依赖 + 启动数据收集 + 回溯历史数据。

每一步我都会验证后再推进——打造全世界第一个数字生命自我模型，不能有一步是虚的。
