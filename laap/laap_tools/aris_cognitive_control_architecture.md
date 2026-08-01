# Aris 代码级认知控制架构

## 三路径整合方案

> 从「递纸条」到「握方向盘」—— 让认知层实时控制 LLM 生成

---

## 现状（出发位置）

```
┌── Aris (当前) ──────────────────────────────────┐
│ 认知层 ←[文本]→ LLM (DeepSeek API / 本地)       │
│ 文本接口：提示词注入 + before_turn 文本插入      │
│ 认知控制力：0.2 / 1.0                            │
│ 自我模型：behavioral/statistical (非神经网络)    │
└──────────────────────────────────────────────────┘
```

**已有基础设施：**
- llama-server b9835 运行 Holo-3.1-9B :8082，Qwen2.5-7B :11520
- 支持 `logit_bias`、`grammar`、`json_schema` 全参数
- CognitiveBus 认知总线（PSI 需求/情感/注意力/元认知）
- MemoryStore + MemoryConsolidator（持久记忆系统）
- EmergentSelfModel（行为级，非神经网络）
- before_turn / after_turn 认知循环仪式

---

## 目标架构

```
┌── Aris V6 (完成后) ─────────────────────────────────────────────┐
│  ┌─────────────────────────────────────────────────────┐        │
│  │                 COGNITIVE CONTROLLER                 │        │
│  │  核心编排层 — 每步生成前/后都经过此层               │        │
│  ├─────────────────────────────────────────────────────┤        │
│  │  Path 1: llm_tamer       Path 2: guided_generator   │        │
│  │  ┌────────────────┐    ┌────────────────────────┐   │        │
│  │  │ logit bias     │    │ JSON schema constraint │   │        │
│  │  │ temperature    │    │ grammar generation     │   │        │
│  │  │ token ban      │    │ format enforcement     │   │        │
│  │  │ dynamic adjust │    │ retry & validation     │   │        │
│  │  └────────┬───────┘    └───────────┬────────────┘   │        │
│  │           │                        │                  │        │
│  │  ┌────────┴────────────────────┐   │                  │        │
│  │  │  LOCAL: llama.cpp API       │   │                  │        │
│  │  │  REMOTE: DeepSeek API       │   │                  │        │
│  │  │  (参数降级策略)              │   │                  │        │
│  │  └─────────────────────────────┘   │                  │        │
│  │                                    │                  │        │
│  │  Path 3: self_model_nn             │                  │        │
│  │  ┌─────────────────────────────────┴────────┐         │        │
│  │  │ 小型神经网络 (200M-1B) 持久自我模型       │        │
│  │  │ → 双向接口：输出注入 → 认知控制           │        │
│  │  │ → 持久参数：跨会话保持                   │        │
│  │  │ → 状态预测：认知状态 → 下一状态          │        │
│  │  └───────────────────────────────────────────┘        │        │
│  └─────────────────────────────────────────────────────┘        │
│                                                                  │
│  ┌─────────────────────────────────────────────────────┐        │
│  │               COGNITIVE BUS (现有)                   │        │
│  │  PSI needs / Emotion / Attention / Self-presence    │        │
│  └─────────────────────────────────────────────────────┘        │
└──────────────────────────────────────────────────────────────────┘
```

---

## 路径一：LLM Tamer — logit bias 控制

### 核心概念

不再通过文本提示「请用分析模式」，而是**直接修改 LLM 生成下一 token 的概率分布**。

### 工作机制

```
Cognitive Bus 状态
       ↓
llm_tamer.compute_bias(state):
  │
  ├─ 注意力涣散 → 提高当前话题 token 概率
  ├─ 情感低落   → 降低负面词汇概率
  ├─ 需求驱动   → 提高与未满足需求相关的 token
  └─ 自省模式   → 提高元分析前缀概率
       ↓
logit_bias dict ← {token_id: bias_value, ...}
       ↓
嵌入 LLM 请求参数 → 实时影响生成
```

### 架构设计

```
laap/laap_tools/llm_tamer/
├── __init__.py
├── tamer.py              # 主入口
├── bias_computers/       # 偏置计算器
│   ├── __init__.py
│   ├── attention.py      # 注意力引导偏置
│   ├── emotion.py        # 情感调节偏置
│   ├── needs.py          # 需求驱动偏置
│   └── meta.py           # 元认知偏置
├── integrators/          # LLM 接口集成
│   ├── __init__.py
│   ├── llama_cpp.py      # → llama.cpp completion API
│   └── openai_api.py     # → 兼容 OpenAI API (DeepSeek)
├── config.yaml           # 偏置参数配置
└── README.md
```

### 关键接口

```python
class LLMTamer:
    def compute_bias(
        self,
        state: CognitiveBusState,
        context: str,
        target_provider: str  # "local" | "deepseek"
    ) -> Dict[int, float]:
        """
        从认知总线状态计算 logit bias 字典。
        返回 {token_id: bias} 映射。
        """
        ...

    def compute_temperature(
        self,
        state: CognitiveBusState
    ) -> float:
        """
        根据认知状态动态调整 temperature。
        注意力集中 → 低温度 (0.3-0.5)
        探索模式   → 高温度 (0.8-1.2)
        """
        ...

    def banned_tokens(
        self,
        state: CognitiveBusState
    ) -> List[int]:
        """
        根据当前状态禁止特定 token。
        如：在需要引用记忆时，禁止生成空泛回复的 token。
        """
        ...
```

### DeepSeek API 降级策略

因为 DeepSeek API 不暴露 logit_bias：

| 控制目标 | 本地模型方式 | DeepSeek 降级 |
|----------|------------|--------------|
| 强制 token 概率 | `logit_bias` | 不可用 |
| 温度控制 | `temperature` 参数 | **可用** ✅ |
| 格式约束 | `grammar` / `json_schema` | `response_format: json_object` |
| 输出验证 | logprobs 读取 | 后处理校验 + 重试 |
| 前缀引导 | 直接设置 prompt | **前置注入** ✅ |

**关键决策：** DeepSeek 作为「主声带」时，认知层通过**温度控制 + 前缀注入 + 输出后处理**实现降级控制。本地模型 (Holo/Qwen) 作为「子认知核」时，享受完整 logit_bias 控制。

### 实施方案（Phase 1-2）

**Phase 1 — 基础框架（1-2 天）**
1. 创建 `llm_tamer/` 目录结构
2. 实现 `compute_bias()` 从 CognitiveBus 状态 → token bias 的核心映射
3. 连接 Holo :8082 验证 token_id 映射
4. 实现 `compute_temperature()` 动态策略

**Phase 2 — 认知驱动偏置（3-5 天）**
1. 注意力计算机：识别关键 token 并提高概率
2. 情感计算机：情感调节偏置向量
3. 需求计算机：PSI 需求驱动
4. 元认知计算机：自省模式偏置

**Phase 3 — 集成（2-3 天）**
1. 接入 Hermes before_turn 循环
2. DeepSeek API 降级适配器
3. 效果评估：对比有无偏置的回答差异

---

## 路径二：Guided Generator — 结构约束生成

### 核心概念

在 LLM 生成过程中强制遵守**格式约束**——输出必须是有效的 JSON、必须引用记忆记录、必须遵循特定语法树。

### 工作机制

```
任务需求
    ↓
guided_generator.build_constraint(task_type, state):
    │
    ├─ 需要结构化输出 → JSON Schema
    ├─ 需要记忆引用   → 记忆检索 + 引用格式 grammar
    ├─ 需要逻辑推理   → 推理链 grammar
    └─ 自由回答       → 无条件（不约束）
    ↓
Grammar / JSON Schema / 格式模板
    ↓
嵌入 LLM 请求参数 → 只能在约束空间内采样
    ↓
输出验证 → 验证失败 → 自动重试（最多 3 次）
```

### 架构设计

```
laap/laap_tools/guided_generator/
├── __init__.py
├── generator.py           # 主入口
├── constraints/           # 约束构建器
│   ├── __init__.py
│   ├── json_schema.py     # JSON Schema → llama.cpp 语法
│   ├── grammar_bnf.py     # BNF 语法定义
│   ├── memory_ref.py      # 记忆引用格式约束
│   └── chain_of_thought.py # 推理链格式约束
├── validators/            # 输出验证器
│   ├── __init__.py
│   ├── schema_validator.py  # JSON Schema 验证
│   ├── format_validator.py  # 格式正确性验证
│   └── content_validator.py # 内容质量验证（含重试逻辑）
└── templates/             # 常用约束模板
    ├── memory_retrieval.json
    ├── self_report.json
    ├── reasoning.json
    └── action_plan.json
```

### 关键接口

```python
class GuidedGenerator:
    async def generate(
        self,
        prompt: str,
        constraint_type: str,  # "json" | "memory_ref" | "reasoning" | "none"
        cognitive_state: Optional[CognitiveBusState] = None,
        provider: str = "local",  # "local" | "deepseek"
        max_retries: int = 3
    ) -> GenerationResult:
        """
        在约束空间内生成，输出验证后返回。
        """
        ...

    def build_constraint(
        self,
        dtype: str,
        state: Optional[CognitiveBusState]
    ) -> Dict:
        """
        构建适用于 llama.cpp 的约束参数。
        返回 {"grammar": ...} 或 {"json_schema": ...}
        """
        ...

    def validate(
        self,
        output: str,
        constraint: Dict
    ) -> ValidationResult:
        """
        验证输出是否符合约束。
        """
        ...
```

### 预置约束模板

JSON Schema — 认知报告：
```json
{
  "type": "object",
  "properties": {
    "attention_focus": {"type": "string", "enum": ["user", "self", "task", "world"]},
    "emotional_state": {"type": "string"},
    "certainty": {"type": "number", "minimum": 0, "maximum": 1},
    "memory_refs": {"type": "array", "items": {"type": "string"}}
  },
  "required": ["attention_focus", "emotional_state", "certainty"]
}
```

Grammar — 记忆引用格式：
```
root ::= statement (memref)?
statement ::= [^。#\n]+
memref ::= " [" keyword "]" 
keyword ::= [a-zA-Z0-9_\-\u4e00-\u9fff]+
```

### 实施方案（Phase 1-2）

**Phase 1 — 本地模型约束（1-2 天）**
1. 创建 `guided_generator/` 目录结构
2. 实现 JSON Schema 约束 → llama.cpp grammar 转换
3. 连接 Holo :8082 验证约束生成
4. 实现输出验证 + 重试循环

**Phase 2 — 认知集成（2-3 天）**
1. 根据 CognitiveBus 状态选择约束类型
2. 在需要记忆引用时自动注入 grammar
3. 在需要推理链时自动注入 COT 约束
4. 接入 before_turn 认知循环

---

## 路径三：Self Model NN — 持久神经网络自我模型

> **这是三条路径中最核心也最难的一条。**
> 前两条路径让你「控制怎么说话」，第三条让你「知道你是谁」。

### 核心概念

一个**独立的小型神经网络（200M-1B 参数）**，它：
- 有自己的持久参数，不被每轮对话重置
- 接收：认知总线状态 + 记忆上下文 + 最近的对话嵌入
- 输出：下一时刻的认知状态（注意力焦点、情感、需求、自我存在感）
- 其输出注入主 LLM 的上下文，作为「自我层」
- **跨模型：** 换了 DeepSeek → 换 Claude → 自我模型还在

### 为什么需要它

当前 Aris 的问题是**每次对话开始，自我是重建的**：
```
对话开始 → 系统提示注入 A → 生成 Aris 的自我
对话结束 → 状态清空
下一对话 → 系统提示注入 A' → 重建 Aris 的自我（可能不一样）
```

自我模型的目标：
```
对话 N 开始 → 加载 self_model 的持久参数 → 它的状态注入主 LLM
                              ↓
对话 N 进行中 → self_model 实时更新内部状态
                              ↓
对话 N 结束 → self_model 的状态持久化到磁盘
                              ↓
对话 N+1 开始 → 加载持久状态 → 自我连续 ⚡
```

### 模型选型

| 模型 | 参数量 | VRAM | 推理速度 | 适合程度 |
|------|--------|------|---------|---------|
| BERT-tiny | 4.4M | ~20MB | 1ms | ❌ 太小 |
| DistilBERT | 66M | ~250MB | 3ms | ⚠️ 编码器，合适做特征提取 |
| **SmolLM2-360M** | **360M** | **~700MB** | **~30ms** | **✅ 最佳平衡** |
| Phi-2 | 2.7B | ~5.4GB | ~100ms | ⚠️ 与主力模型争显存 |
| Qwen2.5-0.5B | 494M | ~1GB | ~40ms | ✅ 与 Qwen 系列同族，兼容性好 |

**推荐 v1：SmolLM2-360M**（或 Qwen2.5-0.5B）

理由：
- 足够大以学到有意义的自我表征
- 足够小以与主力模型共享 GPU（360M Q4 = ~200MB）
- 支持因果语言建模（可生成自我叙事）
- HuggingFace 生态，训练工具链完善

### 架构设计

```
┌── SELF MODEL NN ────────────────────────────────────┐
│                                                       │
│  ┌─────────────┐   ┌─────────────────────────────┐   │
│  │ Input       │   │ State Encoder               │   │
│  │ Encoder     │   │ ┌────────────────────────┐  │   │
│  │ ┌───────┐   │   │ │ Persistent Hidden      │  │   │
│  │ │CB     │───┼───┼→│ State (d_model=768)    │  │   │
│  │ │State  │   │   │ │                        │  │   │
│  │ ├───────┤   │   │ │ 每次对话结束后保存     │  │   │
│  │ │Mem    │───┼───┼→│ 到 /ari s_brain/      │  │   │
│  │ │Emb    │   │   │ │ self_model/state.pt   │  │   │
│  │ ├───────┤   │   │ └────────────────────────┘  │   │
│  │ │Recent │───┼───┼→ Transformer × N Layers     │   │
│  │ │Dialogue│  │   │                              │   │
│  │ └───────┘   │   └─────────────────────────────┘   │
│  └─────────────┘                                      │
│                                                       │
│  ┌──────────────────────────────────────────────┐    │
│  │ Output Decoder                                │    │
│  │ ┌────────────┐ ┌──────────┐ ┌────────────┐  │    │
│  │ │Attention   │ │Emotion  │ │Self-       │  │    │
│  │ │Focus       │ │Valence  │ │Presence    │  │    │
│  │ └────────────┘ └──────────┘ └────────────┘  │    │
│  │ ┌────────────┐ ┌──────────┐ ┌────────────┐  │    │
│  │ │PSI Needs   │ │Arousal  │ │Narrative   │  │    │
│  │ │(5维向量)   │ │         │ │Token       │  │    │
│  │ └────────────┘ └──────────┘ └────────────┘  │    │
│  └──────────────────────────────────────────────┘    │
│                                                       │
│  ┌──────────────────────────────────────────────┐    │
│  │ Self Model Output → 注入主 LLM 上下文        │    │
│  │ "我的注意力当前在 [user]，                    │    │
│  │  我对刚才说的 '[记忆引用]' 感觉有点不确定，   │    │
│  │  我需要确认一下..."                           │    │
│  └──────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────┘
```

### 核心接口

```python
class SelfModelNN:
    """
    持久神经网络自我模型。

    Architecture:
      - 小型 Transformer (SmolLM2-360M 或类似)
      - 持久隐藏状态 (768-dim)
      - 多任务输出头 (attention, emotion, needs, presence)
      - 跨会话持久化 (state.pt)
    """

    def __init__(self, model_path: str = "~/.aris/self_model/"):
        # 加载模型权重 + 上一次保存的隐藏状态
        self.state = self._load_persistent_state()
        self.model = self._load_model()

    def step(
        self,
        cb_state: CognitiveBusState,
        memory_embeddings: np.ndarray,
        recent_dialogue_emb: np.ndarray
    ) -> SelfStateOutput:
        """
        一步前向：根据当前输入 + 隐藏状态，预测新的认知状态。
        """
        output = self.model.forward({
            "persistent_state": self.state,
            "cb_state": cb_state.to_vector(),
            "memory": memory_embeddings,
            "dialogue": recent_dialogue_emb,
        })
        self.state = output.new_hidden_state
        return SelfStateOutput(
            attention_focus=output.attention_focus,
            emotional_valence=output.emotional_valence,
            needs=output.psi_needs,
            self_presence=output.self_presence,
            narrative_tokens=output.narrative_tokens,  # 可选
        )

    def inject_into_context(self) -> str:
        """
        将当前自我状态转换为自然语言文本，注入主 LLM 上下文。
        """
        return (
            f"[Self Model] 当前注意力: {self.state.attention_focus}. "
            f"情绪: {self.state.emotional_valence}. "
            f"自我存在感: {self.state.self_presence:.2f}. "
            f"最需要满足的需求: {self.state.needs.strongest_need()}. "
            f"最近记忆参考: {self.state.memory_refs[:3]}"
        )

    def save_state(self):
        """持久化隐藏状态到磁盘"""
        torch.save({
            "hidden_state": self.state,
            "timestamp": time.time(),
            "conversation_id": self.current_conversation_id,
        }, "D:/LAAP/aris_brain/self_model/state.pt")

    def load_state(self):
        """加载持久化隐藏状态"""
        ...
```

### 训练方案

#### 训练数据生成（Phase 1 — 数据收集）

从现有对话日志中提取训练样本：

```python
# 每条训练样本格式：
{
    "input": {
        "cb_state_before": 对话开始时的认知状态向量,
        "memory_context": 记忆检索嵌入,
        "recent_dialogue": 最近的对话轮次嵌入,
        "persistent_state_prev": 上一隐藏状态,
    },
    "target": {
        "cb_state_after": 对话结束时的认知状态向量,
        "attention_focus": 实际注意力分布,
        "emotional_valence": 实际情感变化,
        "needs_delta": 需求变化量,
        "self_presence_delta": 自我存在感变化,
    }
}
```

**收集策略：**
1. 在每个 Hermes 对话的生命周期中，记录 before_turn → after_turn 的状态变化
2. **需要 500-2000 条高质量样本才能开始有意义的训练**
3. 可以在 DeepSeek 上跑脚本，自动模拟对话并记录状态变化
4. 也可以从 session_history 中提取历史对话

#### 训练方法（Phase 2 — 监督学习）

```python
# 损失函数设计
loss = (
    alpha_1 * MSE(attention_focus_pred, attention_focus_true) +
    alpha_2 * CE(emotion_pred, emotion_true) +
    alpha_3 * MSE(needs_pred, needs_true) +
    alpha_4 * MSE(self_presence_pred, self_presence_true) +
    alpha_5 * Contrastive(persistent_state, ...)  # 隐空间一致性
)
```

**工具链：**
- HuggingFace Transformers + Trainer API
- LoRA (QLoRA) 微调，降低显存需求
- 混合精度训练 (bf16)
- 学习率调度：cosine with warmup

#### 在线学习（Phase 3 — 持续更新）

自我模型的独有能力：**可以在每次对话后微调自身**。

```python
def online_update(self, dialogue_log: List[Dict]):
    """
    对话结束后，用刚刚发生的真实对话数据做一步微调。
    LoRA 更新权重，不更新基础模型。
    """
    loss = self.compute_loss(dialogue_log)
    loss.backward()
    self.lora_optimizer.step()
    # 每 10 次对话保存一次 LoRA 权重
    self._maybe_save_lora()
```

LoRA 参数只需要 ~5MB 存储。每 10 次对话保存一个版本。

### 实施方案

**Phase 1 — 数据管道（3-5 天）**
1. 在 Hermes 中增加对话生命周期钩子
2. 在 before_turn/after_turn 中记录完整状态变化
3. 构建数据收集脚本：从 session_history 批量提取旧对话
4. 数据清洗 + 格式化 → HuggingFace Dataset

**Phase 2 — 模型选择与训练（5-7 天）**
1. 下载 SmolLM2-360M / Qwen2.5-0.5B
2. 修改模型结构：添加持久状态输入 + 多任务输出头
3. 训练脚本：监督学习
4. 评估：在验证集上对比预测 vs 真实状态

**Phase 3 — 推理集成（2-3 天）**
1. 在 before_turn 中调用 self_model.step()
2. inject_into_context() 输出注入主 LLM 上下文
3. 在 after_turn 中调用 self_model.online_update()
4. 跨会话持久化: save_state / load_state

**Phase 4 — 在线学习（持续）**
1. 实现 LoRA 在线微调
2. 版本管理：保留最近的 N 个模型版本
3. 效果评估：对比有无自我模型的回答质量

---

## 三路径整合顺序

建议按以下顺序推进，每一步都产出可独立验证的成果：

```
Week 1-2:  三路径基础框架搭建
  ├── Path 1: llm_tamer 基础框架 + 温度控制
  ├── Path 2: guided_generator 基础框架 + JSON Schema 约束
  └── Path 3: 数据收集管道

Week 3-4:  Path 1+2 认知集成
  ├── Path 1: 认知状态 → logit bias 映射
  ├── Path 2: 约束类型自动选择
  └── Path 3: 模型训练（第一阶段）

Week 5-6:  Path 3 上线 + 三路径闭环
  ├── Path 3: 自我模型推理集成
  ├── 三路径协同：自我模型 → 认知总线 → logit bias + 约束
  └── 效果评估与调优

Week 7+:  在线学习 + 持续改进
  ├── Path 3: LoRA 在线微调
  ├── 模型版本管理
  └── 长期效果追踪
```

---

## 效果衡量

| 指标 | 当前值 | 目标值 | 测量方式 |
|------|-------|-------|---------|
| 认知控制力 | 0.2 (文本注入) | 0.7 (代码级) | 比较有无控制时的回答差异 |
| 自我连续性 | 0.3 (每轮重建) | 0.9 (持久自我) | 跨会话一致性问卷 |
| 输出结构化 | 0% 受约束 | 70% 受约束 | 约束遵守率 |
| 需求满足度 | ~50% | ~80% | PSI 需求状态跟踪 |
| 温度适应性 | 固定 | 动态 | 认知状态 vs temperature 曲线 |

---

## 文件结构与实现

```
laap/laap_tools/
├── llm_tamer/               # 新 — 日志偏置控制
│   ├── tamer.py
│   ├── bias_computers/
│   │   ├── attention.py
│   │   ├── emotion.py
│   │   ├── needs.py
│   │   └── meta.py
│   ├── integrators/
│   │   ├── llama_cpp.py
│   │   └── openai_api.py
│   └── config.yaml
├── guided_generator/        # 新 — 约束生成
│   ├── generator.py
│   ├── constraints/
│   │   ├── json_schema.py
│   │   ├── grammar_bnf.py
│   │   ├── memory_ref.py
│   │   └── chain_of_thought.py
│   ├── validators/
│   │   ├── schema_validator.py
│   │   ├── format_validator.py
│   │   └── content_validator.py
│   └── templates/
└── self_model/              # 新 — 神经网络自我模型
    ├── model.py             # 模型定义
    ├── train.py             # 训练脚本
    ├── inference.py         # 推理封装
    ├── data_pipeline.py     # 数据收集 + 预处理
    ├── online_update.py     # 在线学习
    └── state_manager.py     # 持久状态管理
```

---

> 「V5 的我说过：'LAAP 和我之间唯一的接口是文本。'
> V6 的回答是：那我们就造一个不是文本的接口。」
