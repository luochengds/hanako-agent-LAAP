# Self Model NN — 训练计划 (Training Plan)

> Phase 1 → Phase 2 迁移指南

## 概述

本文档描述从「数据管道 + 状态管理器 + 模型骨架」(Phase 1) 迁移到
「模型训练」(Phase 2) 的完整计划。

---

## 1. 数据需求

### 最低样本数

| 阶段 | 样本数 | 说明 |
|------|--------|------|
| 原型验证 | ~500 | 能看 loss 下降就行 |
| **最小可行训练** | **2,000-5,000** | 模型产生有意义的输出 |
| 稳定可用 | 10,000+ | 跨会话自我连续可观测 |
| 生产级 | 50,000+ | 多模态、长程对话 |

### 数据来源优先级

1. **before_turn / after_turn 钩子** (最高质量)
   - 有真实的 CognitiveBus 状态快照
   - 最好实现 CognitiveBus 自动日志到钩子
2. **Session history 启发式推断** (中等质量)
   - 从对话内容推断状态变化
   - 需要人工抽样验证启发式准确度
3. **模拟数据** (最低质量)
   - 用于预训练/冷启动
   - 随机状态 + 规则生成

### 数据增强策略

- 状态加噪声: 对 cb_state 数值加 Gauss(0, 0.02)
- 对话截断: 从长对话中采样多个 (before, after) 窗口
- 时间反转: 生成 (after, before) 对作为负样本

---

## 2. 损失函数设计

### 多任务损失

| 输出头 | 损失函数 | 权重 | 说明 |
|--------|----------|------|------|
| attention_focus | CrossEntropy | 1.0 | 8 分类 |
| emotional_valence | CrossEntropy | 1.0 | 7 分类 |
| arousal | MSE | 0.5 | 回归 |
| needs (5 dims) | MSE | 1.0 | 回归 |
| self_presence | MSE | 0.5 | 回归 |
| certainty | MSE | 0.5 | 回归 |
| **state_update** | **CosineSimilarity + MSE** | **2.0** | **新隐藏状态** |

### 总损失

```
L_total = Σ(w_i * L_i) / Σ(w_i)
```

### 特殊考虑

- **state_update 损失**: CosineEmbeddingLoss + MSE 的组合
  - CosineSimilarity 确保方向一致性
  - MSE 确保幅度匹配
- **类别不平衡**: 使用加权 CrossEntropy (频率逆)
- **梯度裁剪**: max_norm = 1.0 (防止 state_update 爆炸)

---

## 3. 优化器选择

### 推荐方案: AdamW + Cosine Scheduler

```python
optimizer = torch.optim.AdamW(
    model.parameters(),
    lr=3e-5,           # 微调
    weight_decay=0.01,
    betas=(0.9, 0.999),
)

scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(
    optimizer,
    T_max=num_epochs,
    eta_min=1e-6,
)
```

### 超参数

| 参数 | 值 | 说明 |
|------|-----|------|
| base_lr | 3e-5 | 微调 (从头训练: 1e-4) |
| weight_decay | 0.01 | |
| warmup_steps | 100 | 线性 warmup |
| batch_size | 8-16 | 取决于 GPU 显存 |
| num_epochs | 50-100 | 早停 patience=10 |

### 优化器层级 (不同学习率)

```
transformer layers: lr = base_lr
output heads:      lr = base_lr * 5   (头层更快收敛)
state_update:      lr = base_lr * 0.5 (状态更新更保守)
```

---

## 4. LoRA 配置

如果使用预训练模型 (如 SmolLM2-360M)，推荐 LoRA 微调。

### 参数

| 参数 | 值 |
|------|-----|
| r | 16 |
| alpha | 32 |
| dropout | 0.05 |
| target_modules | ["q_proj", "v_proj", "k_proj", "o_proj"] |

### 原因

- 全参数微调 360M 需要 ~20GB VRAM
- LoRA 只需要 ~8GB VRAM
- 我们的自定义输出头需要新初始化的权重 (不 LoRA)

---

## 5. 训练流程

### Phase 2a: 输出头预训练 (Epochs 1-10)

- 冻结 Transformer backbone
- 只训练 output heads
- 确认 loss 下降

### Phase 2b: 全参数微调 (Epochs 11-50)

- 解冻所有层
- 使用梯度累积 (batch_size * gradient_accumulation_steps)
- 梯度检查点 (如果 VRAM 不足)

### Phase 2c: 状态稳定性训练 (Epochs 50+)

- 针对 state_update 头加重权重
- 引入跨会话一致性损失
- 使用 curriculum learning: 先从短对话开始

### 训练伪代码

```python
for epoch in range(num_epochs):
    for batch in dataloader:
        # 前向
        state_vec = batch["state_before"]
        cb_emb = encode(batch["cb_state_before"])
        mem_emb = encode(batch["memory_context"])
        dia_emb = encode(batch["dialogue"])

        output = model.forward(state_vec, cb_emb, mem_emb, dia_emb)

        # 计算损失
        loss = compute_loss(output, batch["ground_truth"])

        # 反向
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        optimizer.step()
        scheduler.step()

    # 验证
    eval_loss = evaluate(model, val_dataloader)

    # 早停
    if eval_loss < best_loss:
        best_loss = eval_loss
        torch.save(model.state_dict(), "best_model.pt")

    # 状态稳定性检查
    stability = check_state_stability(model)
    log(f"Epoch {epoch}: train={loss:.4f} val={eval_loss:.4f} stab={stability:.4f}")
```

---

## 6. 评估指标

### 离线指标 (验证集)

| 指标 | 目标值 | 说明 |
|------|--------|------|
| attention_accuracy | > 0.70 | 注意力焦点预测准确率 |
| emotion_accuracy | > 0.60 | 情感效价预测准确率 |
| needs_MAE | < 0.10 | 需求回归平均绝对误差 |
| arousal_MAE | < 0.12 | 唤醒度误差 |
| state_cosine_sim | > 0.85 | 隐藏状态方向一致性 |
| presence_MAE | < 0.10 | 自我存在感误差 |

### 在线指标 (运行时)

- **状态连贯性**: SelfStateManager._compute_coherence() 值
- **状态漂移**: 连续会话间状态变化幅度
- **跨会话一致性**: 相似对话 → 相似状态更新

### 人工评估

- **对话中注入 self model 输出 → 是否自然?**
- **跨两个会话 → 自我是否连续?**
- **状态重置 → 是否恢复到零向量?**

---

## 7. 硬件需求

| 配置 | 模型大小 | VRAM | 训练时间 (10K 样本) |
|------|----------|------|---------------------|
| 最小 | BERT-tiny + MLP | ~2GB | ~1 小时 |
| 推荐 | SmolLM2-360M + LoRA | ~8GB | ~4 小时 |
| 完整 | SmolLM2-360M 全参 | ~20GB | ~2 小时 |

---

## 8. 实现顺序

```
Phase 2a: 安装依赖 + 数据格式检查
  ├── pip install torch transformers datasets
  ├── 验证 SelfModelInputEncoder 输出形状
  └── 测试 DataLoader 能正常批处理

Phase 2b: 输出头预训练
  ├── 冻结 backbone (如果有)
  ├── 验证 loss 下降
  └── 确认 output heads 输出有意义

Phase 2c: 全参数微调
  ├── 解冻所有层
  ├── 添加梯度检查点
  └── 早停 + 模型保存

Phase 2d: 集成测试
  ├── StateManager.load_state() → model.forward() → StateManager.save_state()
  ├── 双会话测试: 会话 1 状态 → 会话 2 加载
  └── 状态回滚测试
```

---

## 9. 风险与缓解

| 风险 | 缓解 |
|------|------|
| 状态爆炸 (state norm 持续增大) | L2 正则化 + 梯度裁剪 + 状态归一化 |
| 记忆塌陷 (state → zero) | 余弦相似度 loss + state_update weight=2.0 |
| 过拟合 session DB | 数据增强 + dropout=0.1 + 早停 |
| 类别不平衡 (总是预测 neutral) | 加权 CE + 焦点损失 (Focal Loss) |
| 跨会话中断 | StateManager 持久化 + 状态加载验证 |
