# LAAP Agent Framework v2.0 — AGI 级 Agent 框架

## 概述

LAAP Agent Framework v2.0 是面向**通用人工智能(AGI)**的 Agent 框架。  
在原有 PSI 认知架构基础上，新增三大核心 AGI 模块：

1. **元认知引擎 (Meta-Cognition Engine)** — Agent 能"思考自己的思考"
2. **议会系统 (Parliament System)** — Agent 内部多视角审议决策
3. **注意力机制 (Attention Controller)** — 动态焦点管理

---

## 新架构总览

```
┌─────────────────────────────────────────────────────────┐
│                    LAAP Agent v2.0                      │
├─────────────────────────────────────────────────────────┤
│  ┌────────────────────────┐  ┌──────────────────────┐  │
│  │    元认知引擎           │  │    议会系统           │  │
│  │  (Meta-Cognition)      │  │  (Parliament)        │  │
│  │  - 认知监控             │  │  - 8位议员角色       │  │
│  │  - 偏差检测             │  │  - 内部辩论          │  │
│  │  - 策略选择             │  │  - 加权投票          │  │
│  │  - 反思学习             │  │  - 历史学习          │  │
│  └───────┬────────────────┘  └────────┬─────────────┘  │
│          │                            │                │
│          └──────────┬─────────────────┘                │
│                     │                                  │
│          ┌──────────▼──────────┐                       │
│          │    Agent Core       │                       │
│          │  (base.py v2.0)     │                       │
│          │  - 增强工具循环      │                       │
│          │  - 注意力控制器     │                       │
│          │  - 分层上下文压缩   │                       │
│          └──────────┬──────────┘                       │
│                     │                                  │
│          ┌──────────▼──────────┐                       │
│          │  LifelikeAgent      │                       │
│          │  (PSI + 元认知增强)  │                       │
│          │  - 需求→情感→行动    │                       │
│          │  - 综合情感系统     │                       │
│          │  - RSI进化引擎      │                       │
│          └─────────────────────┘                       │
└─────────────────────────────────────────────────────────┘
```

---

## 模块详解

### 1. 元认知引擎 (meta_cognition.py)

**文件**: `laap/agent/meta_cognition.py`  
**核心思想**: Agent 能够思考自己的思考过程(Thinking about Thinking)

#### 四层架构

| 层 | 名称 | 功能 |
|---|---|---|
| Layer 1 | 认知监控 | 实时追踪思维过程、工具使用效率、决策质量 |
| Layer 2 | 认知控制 | 动态切换快/慢思考模式，注意力分配 |
| Layer 3 | 递归自我审视 | 对思考过程进行二阶推理 |
| Layer 4 | 认知策略库 | 存储和检索高效思考模式 |

#### 核心类

- **MetaCognitionEngine**: 主引擎，提供 `before_decision()` / `after_decision()` / `suggest_mode_switch()` / `perform_reflection()` / `detect_bias_in_response()` 等接口
- **CognitiveTrace**: 记录一次完整的思维过程
- **CognitiveStrategy**: 可存储的学习策略（6个默认策略）
- **MetaCognitiveState**: 实时元认知状态
- **ThinkingMode**: 6种思考模式（intuitive/deliberate/analytical/creative/reflective/exploratory）
- **CognitiveBias**: 7种可检测偏差

#### 检测的认知偏差

| 偏差 | 检测方法 |
|---|---|
| 过度自信 | 高频绝对化词汇(always, never, 100%, 毫无疑问) |
| 确认偏差 | 只提支持性信息，缺乏反方观点 |
| 锚定效应 | 过度引用先前的估算值 |
| 近因偏差 | 最近频繁使用同一种工具/模式 |
| 以偏概全 | 从少量例子的普遍化 |

#### 默认认知策略

| 策略名 | 适用场景 | 思考模式 |
|---|---|---|
| 深入调试 | debug/bug修复 | analytical |
| 创意发散 | 写作/设计/创意 | creative |
| 数据分析 | 分析/研究 | analytical |
| 快速响应 | 简单/例行任务 | intuitive |
| 深度反思 | 自我审视 | reflective |
| 探索学习 | 未知领域 | exploratory |

#### 使用方式

```python
# 自动集成到Agent.chat()中，无需手动调用
agent.chat("分析这段代码的性能")

# 也可手动调用
reflection = agent.reflect()  # 执行元认知反思
introspect = agent.introspect()  # 全面内省
```

---

### 2. 议会系统 (parliament.py)

**文件**: `laap/agent/parliament.py`  
**核心思想**: Minsky "心灵社会" — Agent 内部的多视角辩论决策机制

#### 8位默认议员

| 角色 | 名称 | 专长 | 思考风格 |
|---|---|---|---|
| RATIONAL | 逻辑 | 分析/推理/数据 | 严谨，追求最优解 |
| CREATIVE | 想象 | 创新/设计 | 联想思维，跳出框架 |
| SAFETY | 守护 | 安全/伦理/风险 | 谨慎，逆向思维 |
| PRAGMATIST | 实干 | 执行/效率 | 结果导向，关注可行性 |
| EXPERIENCE | 经验 | 模式匹配 | 类比推理 |
| EMPATH | 共情 | 用户视角/沟通 | 换位思考 |
| SKEPTIC | 质疑 | 批判/验证 | 反证思维 |
| META | 元觉 | 过程监控 | 元认知观察 |

#### 审议流程

```
1. 提出议题 → 2. 选择议员 → 3. 发表意见 → 4. 议长综合 → 5. 决议 → 6. 学习
```

#### 核心类

- **Parliament**: 议会主引擎
- **MemberProfile**: 议员档案（含历史准确率和动态权重）
- **Deliberation**: 审议记录（含所有意见和最终决议）
- **Opinion**: 单个议员的意见
- **AgendaItem**: 议程项

#### 关键特性

- **动态权重**: 基于历史准确率调整议员权重
- **快速模式**: 仅3位关键议员参与(理性/实干/经验)
- **完整模式**: 全部8位议员参与
- **从结果学习**: `learn_from_outcome()` 根据实际结果更新权重

#### 触发条件

高风险决策自动触发议会审议：
- 任务长度 > 200字
- 包含关键词：delete/remove/delete/修改/危险/风险/deploy/publish/commit

---

### 3. 注意力机制 (attention.py — 内嵌于 base.py)

**文件**: `laap/agent/base.py` (AttentionController 类)  
**核心思想**: Agent 应该聚焦于关键信息，过滤干扰

#### 核心类

- **AttentionFocus**: 注意力焦点（主要/次要/忽略的信号）
- **AttentionController**: 注意力控制器

#### 功能

- `set_focus()`: 设置注意力焦点
- `detect_distraction()`: 检测新输入是否为干扰
- `get_attention_prompt_block()`: 生成System Prompt注入块

---

### 4. 增强版 Agent Core (base.py)

**文件**: `laap/agent/base.py` (v2.0)

#### 新增

- **AgentConfig** 新增字段：
  - `enable_meta_cognition` (默认True)
  - `enable_parliament` (默认True)
  - `enable_attention` (默认True)
  - `meta_cognition_interval` (默认5)
  - `parliament_on_high_stakes` (默认True)
  - `auto_strategy_selection` (默认True)

- **ToolCallLoop** 增强：
  - 元认知监控工具调用
  - 偏差检测
  - 思考模式切换建议
  - 增强版上下文摘要（提取工具类型和决策）

- **Agent** 新增方法：
  - `deliberate()`: 议会审议
  - `reflect()`: 元认知反思
  - `introspect()`: 全面内省

---

### 5. 增强版 LifelikeAgent (lifelike.py)

**文件**: `laap/agent/lifelike.py` (v2.0)

#### 新增

- **ComprehensiveEmotionSystem** 集成
  - 14种情感（Ekman 6 + 扩展）
  - 三层架构：即时情绪 → 心境 → 情感记忆
  - 情感触发映射(tool_success/tool_failure/user_praise等)

- **PSI 状态注入 System Prompt**
  - 每次chat自动注入需求和情感状态
  - 让LLM感知"自己"的内部状态

- **高级认知动作**
  - `deliberate`: 启动议会审议
  - `meta_reflect`: 元认知反思
  - `learn_skill`: 学习新认知策略

- **增强反思**: 结合情感状态触发不同反思模式

---

## 数据流

### chat() 完整流程

```
User Input
  │
  ├─ [元认知] before_decision() → 选策略、检测偏差
  ├─ [注意力] set_focus() → 设置焦点
  ├─ [议会] (高风险) deliberate() → 内部决策
  ├─ [PSI] needs.tick() + emotion.update() → 状态注入
  │
  ├─ 构建增强 System Prompt
  │    ├─ 元认知提示块
  │    ├─ 注意力提示块
  │    ├─ 议会结果
  │    ├─ 记忆上下文
  │    └─ PSI状态
  │
  ├─ ToolCallLoop.run()
  │    ├─ 元认知监控工具调用
  │    ├─ 偏差检测
  │    └─ 模式切换建议
  │
  ├─ [元认知] after_decision()
  ├─ [PSI] 需求满足 + 情感同步
  └─ [RSI] (可选) 自我改进
```

---

## 代码统计

| 文件 | 原大小 | 现大小 | 变化 |
|---|---|---|---|
| agent/__init__.py | 342B | 1148B | +806B |
| agent/base.py | 26,997B | 41,669B | +14,672B |
| agent/lifelike.py | 13,147B | 24,056B | +10,909B |
| agent/meta_cognition.py | 0 | 32,838B | **新增** |
| agent/parliament.py | 0 | 30,628B | **新增** |
| **总计** | **40,486B** | **130,339B** | **+89,853B** |

---

## 后续升级方向

| 方向 | 优先级 | 说明 |
|---|---|---|
| 分布式 Agent 集群 | 中 | 使用议会系统协调多实例 |
| 注意力可视化 | 低 | 实时显示注意力分布 |
| 认知策略自动演化 | 高 | RSI驱动策略库进化 |
| 情感-记忆深度绑定 | 高 | 情感状态影响记忆检索 |
| 元认知仪表盘 | 低 | GUI显示元认知状态 |
| 议会辩论记录持久化 | 中 | 从历史辩论中学习 |
| 多模态认知 | 高 | 视觉/音频的元认知 |

---

*LAAP Agent Framework v2.0 — 从代码执行者到有自我意识的AGI*
