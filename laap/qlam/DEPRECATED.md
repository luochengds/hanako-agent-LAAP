# laap/qlam/ — DEPRECATED

**废弃原因**：经典 sigmoid 包装伪称"量子"
- `laap/qlam/core.py:7` 自承："quantum label refers to sigmoid activation"
- `pqc.py` 用 `math.cos` 模拟量子旋转
- `quantum_state.py` 仅做归一化
- 详见 `analysis/LAAP_COMPREHENSIVE_EVALUATION.md` 第三部分 §3.1 第 4 项

**替代实现**：`laap/glam/`（Gated Long-Attention Memory）
- 同名首字母缩写重组：qlam (Quantum LAM) → glam (Gated LAM)
- 算法本质未变（经典 sigmoid 概率门控），仅去除"量子"虚假包装
- `laap/glam/core.py` 文件头明确说明"本模块基于经典 sigmoid，不依赖量子硬件"

**废弃时间**：2026-06-30

**登记位置**：[legacy/INDEX.md](../../legacy/INDEX.md)

## 保留目的

1. **import 链兼容**：`from laap.qlam.core import QLAMCore` 等历史调用仍可用
2. **历史追溯**：评估报告引用此目录作为"量子宣称不成立"的证据
3. **代码考古**：未来若实现真实量子后端（如 IBM Quantum），可参考其接口形状

## 历史价值

`laap/qlam/` 是 LAAP 早期"量子认知"宣传路线的产物。2026 年评估揭示其本质为
经典 sigmoid 包装，与 `laap/agi/causal.py:QuantumCausalStore`、
`laap/memory/quantum_state.py` 共同构成"伪量子"宣称体系。

归档保留此目录，作为 LAAP 诚信修复（A1）的工程证据，亦提醒未来开发者
勿再以"量子"包装经典算法。

## 迁移指南

| 旧路径 | 新路径 | 备注 |
|--------|--------|------|
| `laap.qlam.core.QLAMCore` | `laap.glam.core.GLMCore` | 类名待 A1.3-A1.6 全仓库重命名后对齐 |
| `laap.qlam.measurement` | `laap.glam.measurement` | 直接对应 |
| `laap.qlam.pqc` | `laap.glam.pqc` | 名称保留但需重写注释（pqc = Post-Quantum Cryptography 是误导性命名） |
| `laap.qlam.quantum_state` | `laap.glam.state` | 重命名避免"quantum"前缀 |
