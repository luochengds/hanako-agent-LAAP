# Aris 认知控制架构方案评估报告

> **评估对象**：`D:/LAAP/laap/laap_tools/aris_cognitive_control_architecture.md`
> **评估基准**：实际仓库代码（`aris_brain/`、`laap/agi/`、`laap/laap_tools/`）
> **评估时间**：2026-07-01
> **评估维度**：技术可行性 / 方案完整性 / 实施计划 / 风险挑战 / 架构一致性

---

## 评估摘要

方案提出"代码级认知控制"三路径（llm_tamer / guided_generator / self_model_nn），目标将认知控制力从 0.2 提升到 0.7。经对照代码实际状态评估：

- **三路径目录均已存在并有实现**（非从零开始），但实现完整度差异显著
- **Path 1（llm_tamer）与 Path 2（guided_generator）**：框架完整，存在导入 bug 与设计盲点，但可修复
- **Path 3（self_model_nn）**：当前是 numpy 启发式骨架，称"神经网络"为时尚早；训练数据源未接通
- **三路径闭环未接通**：缺 `SelfStateOutput → CognitiveStateSnapshot` 转换层，无联合集成测试
- **与现有系统集成完全缺失**：`ArisCognitiveBridge` 既不导入也不调用三路径任何模块
- **三套 LLM 后端并存**（:8082/:8089/:11520+DeepSeek），文档未明确主声带归属

**总体判断**：方案技术方向正确，但实施计划偏乐观，关键集成层缺失，需调整时间节点并补齐转换层与集成代码后方可启动。

---

## 第一章：技术可行性分析

### 1.1 路径一：llm_tamer — logit bias 控制

#### 1.1.1 验证状态表

| 验证项 | 文档声称 | 代码实际 | 状态 | 备注 |
|---|---|---|---|---|
| 主入口类 `LLMTamer` | 提供 `compute_bias/compute_temperature/banned_tokens` | `tamer.py:64-435` 完整实现三方法 | ✅ 已验证一致 | 接口签名与文档完全吻合 |
| CognitiveBus 类型导入 | `state: CognitiveBusState`（方案文档第 119 行） | `tamer.py:53-59` 导入 `CognitiveBus, CognitiveBusState`，但 `laap/agi/cognitive_bus.py` 仅导出 `CognitiveStateSnapshot`（第 169 行） | ❌ 不一致 | 导入失败后 `CognitiveBus=None`，且 `CognitiveBusState` 名字未在 except 分支定义 → 任何 `isinstance` 检查会 TypeError |
| 注解一致性 | 文档使用 `CognitiveBusState` | `tamer.py:130,182,232,274,339` 使用字符串注解 `"CognitiveStateSnapshot"` | ⚠️ 部分一致 | 注解已修正，但与方案文档示例不一致 |
| LlamaCppIntegrator 端口 | 8082 主 / 11520 备 | `config.yaml:7-8`、`tamer.py:116-118`、`llama_cpp.py:37-39` 一致 | ✅ 已验证一致 | — |
| logit_bias 支持 | 完整支持 `logit_bias`、`grammar`、`json_schema` | `llama_cpp.py:51-138` 三参数均实现 | ✅ 已验证一致 | — |
| logit_bias 参数格式 | 文档第 88 行示例 `{token_id: bias_value}` dict | `llama_cpp.py:90-97` 实际发送 `[[int(tid), float(bias)], ...]` 列表 | ⚠️ 部分一致 | 内部 API 用 dict，传输时转 list；文档未明示此转换 |
| 偏置范围 | 未明示 | `tamer.py:175-178` clamp 到 `[-100, 100]` | ✅ 已验证一致 | 与 llama.cpp 限制一致 |
| DeepSeek 不支持 logit_bias | 降级为温度+前缀+后处理 | `tamer.py:150-152` 直接返回 `{}`；`openai_api.py` 无 logit_bias 字段 | ✅ 已验证一致 | — |
| DeepSeek 降级"三件套" | 温度控制+前缀注入+输出后处理 | 温度✅（`tamer.py:360`）、前缀注入✅（`openai_api.py:104-143`）、**输出后处理/重试❌** | ⚠️ 部分一致 | OpenAIIntegrator 没有重试循环 |
| 四个偏置计算机 | attention/emotion/needs/meta | `bias_computers/` 四文件齐全 | ✅ 已验证一致 | — |
| 偏置强度配置 | 1.0/0.7/0.5/0.8 | `config.yaml:25-29` 与文档一致 | ✅ 已验证一致 | — |
| Token 映射 | Holo-3.1-9B 实际 token ID | `config.yaml:42-103` 提供 8 组映射 | ⚠️ 部分一致 | 两套模型（Holo/Qwen）混用同一份 config |

#### 1.1.2 关键发现

**发现 1：导入 bug 严重影响可用性**
- `tamer.py:52-59` 尝试导入 `CognitiveBusState`，但 `laap/agi/cognitive_bus.py:169` 实际定义的是 `CognitiveStateSnapshot`，**没有任何 `CognitiveBusState` 类**
- 导入失败后进入 except 分支，导致 `CognitiveBus=None`、`CognitiveStateSnapshot=None`，且 `CognitiveBusState` 名字完全未定义
- `bias_computers/attention.py:15-18` 与 `emotion.py:16-19` 直接导入无 try/except 保护，若 `laap.agi.cognitive_bus` 因任何原因无法导入，整个 `bias_computers` 包会失败

**发现 2：logit_bias 内外格式不一致是设计而非 bug**
- `compute_bias` 对外返回 `Dict[int, float]`（`tamer.py:129-180`）
- `LlamaCppIntegrator.send_completion` 接收 dict 后转 `[[tid, bias], ...]`（`llama_cpp.py:90-97`），并过滤 `abs(bias) <= 0.5` 的小偏置
- 文档示例 `logit_bias dict ← {token_id: bias_value, ...}`（第 88 行）描述的是内部表示，与传输格式不同，文档未明示

**发现 3：偏置量级风险**
- `attention.py:68` 实际是 `focus_strength = self.bias_strength * intensity * 15.0`
- `emotion.py:54-91` 的 `15.0~25.0` 倍数，累加后单 token bias 可达 ±30~50
- llama.cpp 中 `logit_bias=100` 等价于"近乎强制"，±30~50 在 softmax 后仍是压倒性概率（exp(30) ≈ 10^13），可能导致生成僵硬

**发现 4：DeepSeek 降级"后处理+重试"完全未实现**
- `openai_api.py:49-102` 的 `send_chat_completion` 没有任何重试或后处理逻辑
- `tamer.py:337-389` 的 `apply_to_deepseek` 也没有调用任何 validator
- 方案文档第 160-163 行声称"输出验证：后处理校验 + 重试"，但 llm_tamer 路径上完全没有这部分代码

#### 1.1.3 可行性结论

**本地路径（Holo/Qwen via llama.cpp）：可行，存在导入 bug 与偏置量级调参风险。** 修复 `CognitiveBusState` → `CognitiveStateSnapshot` 后即可运行；token 映射需要用 `llama_cpp.py:140-163` 的 `get_tokenizer_tokens` 在目标模型上重新校准。

**DeepSeek 降级路径：部分可行，"三件套"中只完成了 2/3。** 温度控制与文本前缀注入已实现且可工作，但"后处理+重试"在 llm_tamer 路径上缺失。文本前缀注入的"认知控制力"远弱于 logit_bias，能否达到方案目标 0.7 存在重大不确定性。

---

### 1.2 路径二：guided_generator — 结构约束生成

#### 1.2.1 验证状态表

| 验证项 | 文档声称 | 代码实际 | 状态 | 备注 |
|---|---|---|---|---|
| 主接口 `GuidedGenerator.generate` | 异步 `async def generate` | `generator.py:113` 是**同步** `def generate` | ⚠️ 部分一致 | 功能完整但与文档签名不符 |
| `build_constraint` 返回 | `{"grammar": ...}` 或 `{"json_schema": ...}` | `generator.py:223-252` 完全一致 | ✅ 已验证一致 | — |
| `validate` 接口 | 返回 `ValidationResult` | `generator.py:355-409` 返回聚合 `ValidationResult` | ✅ 已验证一致 | — |
| 约束类型支持 | json / memory_ref / reasoning / none | `generator.py:246-252` 支持 json/memory_ref/reasoning/grammar/none | ✅ 已验证一致 | 实现比文档多一种 `grammar` |
| 重试机制 | "最多 3 次" | `generator.py:165-217` 循环 `max_retries + 1` 次；`content_validator.py:85-132` 另有独立 `validate_with_retry` | ⚠️ 部分一致 | 存在两套重试循环，未明确协同策略 |
| JSON Schema 约束 | 4 个预置模板 | `json_schema.py:16-82` 定义 cognitive_report / action_plan / self_model / memory_retrieval | ✅ 已验证一致 | — |
| BNF Grammar | 提供基础 grammar | `grammar_bnf.py:14-68` 提供 10 个预置 grammar + `enum/sequence` 工厂 | ✅ 已验证一致 | — |
| 认知状态驱动选择 | 根据 CognitiveBus 状态选约束 | `generator.py:280-349` 实现 `infer_constraint_type` | ✅ 已验证一致 | 但 `generate()` 不自动调用 `infer_constraint_type`，切换逻辑未闭环 |
| 接入 before_turn | Phase 2 集成 | 仓库中未见 aris_cognitive_bridge 调用 GuidedGenerator | ❌ 不一致 | 集成尚未发生 |

#### 1.2.2 关键发现

**发现 1：异步 vs 同步签名不一致**
- 方案文档第 239 行：`async def generate(...)`
- 实际 `generator.py:113`：`def generate(self, prompt: str, ...) -> GenerationResult`
- 内部调用 `requests.post`（`generator.py:443-449`），是同步阻塞 IO

**发现 2：两套重试循环可能产生 N×M 次调用**
- `GuidedGenerator.generate`（`generator.py:165-217`）已实现外层重试
- `ContentValidator.validate_with_retry`（`content_validator.py:85-132`）是另一套独立的重试
- 当前 `generate` 内部用的是 `self.content_validator.validate(output)`（单次校验），**没有调用 `validate_with_retry`**，后者目前是"死代码"

**发现 3：JSON Schema → Grammar 转换器存在字符转义 bug**
- `json_schema.py:164` 字符串类型 grammar：`return f'{prefix}root ::= "\\\\\"[^\\\\"]*"\\\\""'` —— 输出多了一层转义，GBNF 解析器可能不接受
- 文档第 220 行也注明"prefer using the native json_schema parameter"，暗示作者知道转换不完美

**发现 4：grammar_bnf 的中文 grammar 与 llama.cpp GBNF 兼容性存疑**
- `grammar_bnf.py:52-54` 的 `CHINESE_TEXT_GRAMMAR` 使用 `[^。！？，、：；""''（）【】《》\n]+`
- GBNF 不支持中文字符直接出现在 negated class 中，需要用 `[\u4e00-\u9fff]` 这类显式区间
- 文档第 295 行的示例 grammar 用了 `\u4e00-\u9fff` 区间，但实现没用

#### 1.2.3 可行性结论

**本地约束生成：高度可行。** `generator.py` 与 `json_schema.py`/`grammar_bnf.py` 形成完整闭环，重试机制可用。主要工作是修复 grammar 字符转义 bug、统一两套重试循环、并在 `aris_cognitive_bridge.before_turn` 中接入。

**DeepSeek 路径：仅 `response_format: json_object` 可用。** DeepSeek API 不支持 `json_schema` structured output 严格模式。memory_ref/reasoning grammar 也无法在 DeepSeek 端强制执行，只能依赖客户端后验。

---

### 1.3 路径三：self_model_nn — 持久神经网络自我模型

#### 1.3.1 验证状态表

| 验证项 | 文档声称 | 代码实际 | 状态 | 备注 |
|---|---|---|---|---|
| 模型选型 | SmolLM2-360M / Qwen2.5-0.5B | `model.py:52` `model_type: str = "smol_lm2"`；`from_pretrained`（第 433-449 行）抛 `NotImplementedError` | ⚠️ 部分一致 | 仅骨架，无 torch 依赖 |
| `step()` 接口 | 接收 cb_state/memory/recent_dialogue，返回 `SelfStateOutput` | `model.py:277-393` `forward()` 接收 4 个 numpy 数组 | ⚠️ 部分一致 | 方法名是 `forward` 而非 `step`；签名不同 |
| `inject_into_context()` | 输出注入主 LLM 上下文 | 实际由 `state_manager.py:291-335` 的 `to_cognitive_context()` + `inject_via_hook()` 实现 | ⚠️ 部分一致 | 功能存在但分散在两个类 |
| `save_state/load_state` | `torch.save({...}, "state.pt")` | `state_manager.py:139-235` 实际用 `np.save` 存 `.npy`，元数据存 `meta.json` | ⚠️ 部分一致 | 无 torch 依赖；state.pt 路径保留但实际写入 state.npy |
| 训练样本需求 | 500-2000 条"高质量" | `training_plan.md:18-23` 原型 500 / 最小可行 2000-5000 / 稳定 10000+ | ⚠️ 部分一致 | 文档下限 500 与 plan 一致；上限 2000 < plan 的 5000 |
| 数据来源 | Hermes before_turn/after_turn 钩子 + session_history + 模拟 | `data_pipeline.py:139-390` 实现 3 个收集方法 | ✅ 已验证一致 | — |
| LoRA 在线学习 | Phase 4 实现 | 仓库中**无 `online_update.py` 文件**；`training_plan.md:114-129` 仅给出参数表 | ❌ 不一致 | 方案文档第 644 行列出 `online_update.py`，实际未创建 |
| 文件结构 | model.py / train.py / inference.py / data_pipeline.py / online_update.py / state_manager.py | 实际仅 model.py / data_pipeline.py / state_manager.py / training_plan.md / test_self_model.py | ❌ 不一致 | train.py、inference.py、online_update.py 三文件缺失 |
| 模型架构 | Input Encoder + State Encoder + Transformer × N + Output Decoder | `model.py:207-262` 仅 `SelfModelNN` 骨架；`OutputHeadConfig`（第 138-200 行）定义 7 个输出头 | ⚠️ 部分一致 | 输出头完整，Transformer 主体未实现 |
| 持久化路径 | `D:/LAAP/aris_brain/self_model/state.pt` | `state_manager.py:33` `_STATE_FILE = "D:/LAAP/aris_brain/self_model/state.pt"` | ✅ 已验证一致（路径） | 路径一致，格式不同（.npy） |

#### 1.3.2 关键发现

**发现 1：当前 forward() 是纯启发式，与"神经网络"宣称严重不符**
- `model.py:300-358` 的 `forward()` 实现是基于 `state_vec` 不同区段的 `np.mean(np.abs(...))` 计算各输出
- 完全无任何可训练参数，`from_pretrained` 直接 `raise NotImplementedError`
- `total_parameters` 是 `_estimate_params()` 估算值，并非真实存在的参数
- **结论：当前 self_model_nn 不是神经网络**，是 numpy 启发式 + 接口骨架

**发现 2：state_manager 与 model 之间的状态分段假设不一致**
- `state_manager.py:402-432` 把 768 维切成 `[0:128]/[128:256]/.../[640:768]` 六段
- `model.py:332-342` 把 state_vec 切成 `[0:160]/[160:320]/.../[640:768]` 五段
- 两个类对同一向量的"语义分段"假设不同，注入主 LLM 的文本与模型自身 forward 的输出语义不连续

**发现 3：训练数据收集严重依赖启发式，5 维 PSI 标签质量存疑**
- `data_pipeline.py:217-305` 的 `collect_from_session_db` 用启发式推断 cb_state_after（消息长度→competence，轮次→attention shift）
- 真实 Hermes state.db schema 只有 `messages(id, role, content, timestamp, session_id)` 和 `sessions(id, started_at)`，**没有任何 CognitiveBus 5 维 PSI 字段**
- session 数据的 `cb_state_before` 全部相同（启发式返回固定默认值），训练信号无效

**发现 4：模拟数据生成引入分布偏差**
- `data_pipeline.py:307-390` 的 `collect_simulated` 用 `random.choice` 均匀采样 8 种 attention 与 7 种 valence
- 真实分布中 `user` focus 与 `neutral` valence 占比远高于其他类别
- 均匀采样的模拟数据会让模型在真实推理时倾向预测少数类

**发现 5：跨会话持久化路径实际可用，但未接入任何认知循环**
- `state_manager.py:139-235` 的 `load_state/save_state` 已实现完整（多级回退）
- 但 `aris_cognitive_bridge.py:532-539` 的 `after_tool` 仍调用 `EmergentSelfModel`，而非 self_model_nn
- 两套"自我模型"并存：EmergentSelfModel（被调用、无持久化）+ SelfModelNN（有持久化、未被调用）

#### 1.3.3 可行性结论

**Phase 1（数据管道 + 状态管理 + 模型骨架）：已完成且可用。** `state_manager.py` 的持久化逻辑健壮，`data_pipeline.py` 三种收集方法齐全。但模型本身只是 numpy 骨架，称"神经网络自我模型"为时尚早。

**Phase 2（真实训练）：高风险。** 主要阻塞点：(1) 训练标签质量；(2) train.py / inference.py / online_update.py 三文件完全缺失；(3) state_manager 与 model 的状态分段假设不一致。

**Phase 3-4（推理集成 + 在线学习）：当前不可行。** 需先完成 Phase 2，且需在 `aris_cognitive_bridge.before_turn` 中新增调用点（当前无任何调用方）。

---

## 第二章：方案完整性审查

### 2.1 llm_tamer 四种认知状态策略审查

#### 策略一："注意力涣散 → 提高当前话题 token 概率"

**设计盲点**：
- **"当前话题 token"识别机制完全缺失**：`attention.py` 仅基于静态 token 组映射（confirm_tokens/question_tokens/positive_tokens），无任何"从对话上下文提取当前话题 → 转为 token_id"的逻辑
- token_id 映射如何维护？`config.yaml:42-103` 提供 8 组手工映射，但无自动维护脚本，新话题无法自动加入
- **未覆盖问题**：注意力涣散的检测阈值未定义，何时触发"提高"动作不明确

#### 策略二："情感低落 → 降低负面词汇概率"

**设计盲点**：
- **负面词汇词表仅 5 条手工词**：`emotion.py` 的 `negative_tokens` 只有 5 个 token，覆盖极低
- 中文场景下负面词汇极其丰富（"失望/沮丧/疲惫/无力/绝望..."），5 条不足以产生影响
- 词表来源未说明，无外部情感词典接入（如知网情感词典、SentaRus）
- **未覆盖问题**：情感状态到负面词汇的映射是静态的，无法根据上下文调整

#### 策略三："需求驱动 → 提高与未满足需求相关的 token"

**设计盲点**：
- **需求→token 映射用 positive_tokens 近似 relatedness**：`needs.py` 作者自认这是缺口
- PSI 五维需求（competence/autonomy/relatedness/certainty/growth）各自应映射到不同 token 集，但实际实现未区分
- "未满足需求"的判定阈值未定义（< 0.3？< 0.5？）
- **未覆盖问题**：需求满足后如何降低对应 token 的偏置（动态调整机制缺失）

#### 策略四："自省模式 → 提高元分析前缀概率"

**设计盲点**：
- **元分析"前缀序列"从未定义**：`meta.py` 提到"元分析前缀"，但具体 token 序列（如"让我思考一下"/"从元层面看"）未给出
- logit_bias 无法强制多 token 序列（只能逐 token 偏置），即使定义了前缀，也无法保证序列完整生成
- 自省模式的触发条件未定义（curiosity > 阈值？self_presence < 阈值？）

### 2.2 guided_generator 四类约束模板审查

#### 模板一：JSON Schema（认知报告）

**合理性**：
- `self_report.json` 定义了 cognitive_report schema，包含 attention_focus/emotional_state/certainty/memory_refs 字段
- enum 扩展为 8 个（`["user", "self", "task", "world", "memory", "planning", "learning", "idle"]`），比文档示例更完整

**缺口**：
- **缺失 PSI 五维需求字段**：schema 中无 competence/autonomy/relatedness/certainty/growth
- **缺失 arousal 与 self_presence 字段**：CognitiveStateSnapshot 包含这些字段，但 schema 未覆盖
- 与 `CognitiveStateSnapshot` 的字段对齐不完整

#### 模板二：记忆引用 Grammar

**合理性**：
- `memory_ref.py` 实现了 `["keyword"]` 格式约束
- 提供了 build/validate 方法

**缺口**：
- **因 llama.cpp 限制移除 CJK 支持**：实际实现的 grammar 移除了中文字符支持，与文档第 295 行的 `\u4e00-\u9fff` 区间直接冲突
- 中文 keyword 无法在 grammar 中使用，实际可用性大打折扣
- LLM 能否稳定遵守 `["keyword"]` 格式未实测

#### 模板三：推理链 Grammar

**缺口**：
- **文档完全留白**：方案文档第 222 行提到 `chain_of_thought.py`，但未给出具体 BNF 定义
- 实现填补了部分（`chain_of_thought.py` 存在），但未回写文档
- 推理链的具体格式（如 `Step 1: ... → Step 2: ... → Conclusion: ...`）未规范化
- 与现有 `reasoning.json` 模板的关系未定义

#### 模板四：自由回答（无约束）

**缺口**：
- `infer_constraint_type`（`generator.py:280-349`）存在，能根据 CognitiveBus 状态选择约束类型
- **但 `generate()` 不自动调用 `infer_constraint_type`**，切换逻辑未闭环
- 调用方需手动传入 `constraint_type` 参数，否则默认 `none`
- 约束模式与自由回答模式的切换阈值/条件未定义

### 2.3 self_model_nn 训练流程审查

#### 环节一：样本收集

**完整性缺口**：
- **500-2000 条样本目标在当前数据管道下不现实**：
  - `collect_from_hooks()` 依赖 hooks 目录，但 `aris_cognitive_bridge.after_turn` 当前不向 hooks 目录写入训练样本
  - `collect_from_session_db()` 的 `cb_state_before` 全部相同（启发式返回固定默认值），训练信号无效
  - `collect_simulated()` 纯随机生成，无认知动力学
- "高质量"标准未定义：`training_plan.md:26-32` 分三级（钩子最高、session 启发式中、模拟最低），但当前钩子未落盘，高质量数据源为 0

#### 环节二：监督学习

**完整性缺口**：
- **损失函数 α1-α5 权重文档未给值**：`training_plan.md` 也未给出具体数值
- **隐空间一致性 Contrastive 项构造方式三处描述矛盾**：
  - 方案文档第 515 行：`Contrastive(persistent_state, ...)`
  - `training_plan.md` 提到"隐空间一致性"
  - `model.py` 无任何 contrastive loss 实现
- Contrastive 项的正样本/负样本如何构造未定义

#### 环节三：LoRA 在线微调

**完整性缺口**：
- **3 个承诺文件缺失**：`train.py`、`inference.py`、`online_update.py` 均未创建
- `training_plan.md:114-129` 仅给出 LoRA 参数表（r=16, alpha=32, dropout=0.05），无实现代码
- 每 10 次对话保存一版的版本管理：
  - 存储膨胀风险：~5MB/版本 × 365/年 ≈ 1.8GB/年
  - 版本清理策略未实现
  - 版本回滚机制缺失（`state_manager.py` 只有 `reset_state`，无版本回滚）

#### 环节四：评估方法

**完整性缺口**：
- **`test_self_model.py` 仅测骨架结构，无任何预测准确性评估**
- 在验证集上对比"预测 vs 真实状态"的指标定义不明确：
  - attention_focus 用 accuracy 还是 confusion matrix？
  - emotional_valence 用 accuracy 还是 regression MSE？
  - needs_delta 用什么指标？
- 无基线对比（如"恒定预测当前状态"基线）
- `training_plan.md` 未定义训练成功的标准（loss < 某阈值？指标 > 某阈值？）

---

## 第三章：实施计划评估

### 3.1 启动顺序与时间节点评估

#### Week 1-2：三路径基础框架搭建 — **判断：偏乐观（但有部分已落地）**

三路径目录均已存在并有完整实现，并非从零搭建：

| 路径 | 目录状态 | 实现完整度 |
|------|---------|-----------|
| Path 1 llm_tamer | ✅ 完整 | 偏置计算机 4 个 + 双集成器 + config.yaml + 8 个测试 |
| Path 2 guided_generator | ✅ 完整 | 4 个约束构建器 + 3 个验证器 + 4 个模板 + 14+ 测试 |
| Path 3 self_model | ✅ 骨架完整 | state_manager + data_pipeline + model + training_plan + 测试 |

**未识别的依赖**：
1. **CognitiveBus 类型名不一致**（隐性依赖断裂）：`tamer.py:53` 导入不存在的 `CognitiveBusState`，实际类名是 `CognitiveStateSnapshot`
2. **双 CognitiveBus 实现未在文档中区分**：三路径 import AGI 版，而 `aris_cognitive_bridge.py:71` 使用路由版
3. **`aris_brain/self_model/` 持久化目录不存在**：首次运行需自行创建

**依据**：框架代码已存在约 80%，但"基础框架搭建"在文档语义上是"从零开始"。实际 Week 1-2 应重新定义为"修复类型不一致 + 验证已有模块 + 完成集成 stub"。

#### Week 3-4：Path 1+2 认知集成 + Path 3 模型训练 — **判断：偏乐观（Path 3 训练过早）**

**Path 1+2 认知集成 — 合理**：`generator.py:280-319` 的 `infer_constraint_type()` 与 `tamer.py:129-180` 的 `compute_bias()` 已基本完成。

**Path 3 模型训练 — 偏乐观，数据收集不足以支撑**：
- `training_plan.md:18-22` 明确：最小可行训练 2000-5000 样本
- `aris_cognitive_bridge.py:515-516` 每 10 轮保存 bridge 状态，**不是 TrainingSample 格式**
- 数据钩子未接入，Week 1-2 的"数据收集管道"在源头没有数据流入
- 在钩子未落盘 + 真实数据量为 0 的情况下，Week 3-4 启动训练只能依赖 `collect_simulated()`（纯随机），训练出来的模型无意义

**建议**：将 Path 3 训练推迟到 Week 5-6，Week 3-4 专做钩子接入 + 真实数据积累。

#### Week 5-6：Path 3 上线 + 三路径闭环 — **判断：偏乐观（集成测试时间不足）**

**问题：三路径闭环无集成测试场景**
- `test_tamer.py`：仅测试 Path 1 单路径
- `test_generator.py:643-668`：仅测试 Path 2 单路径
- `test_self_model.py:546-594`：仅测试 Path 3 内部循环
- **没有任何测试覆盖"自我模型 → 认知总线 → logit bias + 约束"完整数据流**
- `SelfModelNN.forward()` 的输出 `SelfStateOutput` 与 `CognitiveStateSnapshot` 之间**没有转换函数**

**依据**：三路径协同的"接缝"代码尚未编写。两周内完成代码 + 测试 + 调优偏紧。

#### Week 7+：在线学习 + 持续改进 — **判断：合理（但缺少稳定性保障）**

**缺失的稳定性保障**：
1. **回滚机制**：`state_manager.py:283` 只有 `reset_state`（清零），无版本回滚
2. **版本管理**：`state_manager.py` 仅维护单一 state 文件，无版本快照
3. **在线学习监控**：`state_manager.py:375-400` 的 `_compute_coherence()` 是启发式，不是真正的漂移检测

### 3.2 产出物明确性评估

| 产出物 | 可验证性 | 证据 |
|--------|---------|------|
| "可实际调 logit_bias" | ✅ 可验证 | `test_tamer.py:290-340` test_06_llama_connection 有明确测试用例 |
| "训练数据积累" | ⚠️ 部分可验证 | 格式规范已定义（`data_pipeline.py:59-106`），但钩子未落盘，量不可验证 |
| "三路径初步集成" | ❌ 不可验证 | 无联合集成测试，无转换层 |
| "持久状态实现" | ✅ 可验证 | `test_self_model.py:91-131` test_state_manager_save_load 有跨会话验证 |

### 3.3 不依赖文本接口计划评估

**是否给出了具体接口定义？— 部分清晰 ⚠️**

三处散落的接口定义：
1. **logit_bias 接口**（文档第 115-127 行）：已实现
2. **grammar/json_schema 接口**（文档第 252-272 行）：已实现
3. **持久 state.pt 接口**（文档第 462-472 行）：部分实现（用 .npy 代替 .pt）

**问题**：没有一个"非文本接口总规范"说明它们如何组合。

**logit_bias / grammar / 持久 state.pt 是否构成"非文本接口"？— 构成 ✅（但程度不同）**

| 接口 | 非文本性 | 证据 |
|------|---------|------|
| logit_bias | ✅ 完全非文本 | `llama_cpp.py:91-97`：数值数组，直接作用于 logits |
| grammar / json_schema | ⚠️ 半非文本 | 约束本身是字符串，但作用机制是 llama.cpp 服务端采样时强制 |
| 持久 state.pt | ⚠️ 部分非文本 | 状态以 .npy 二进制持久化，但**注入回主 LLM 仍是文本** — `state_manager.py:291-335` 把 768 维向量转成 `"[Self Model] ..."` 文本块 |

**关键发现**：自我模型的"输出接口"在当前实现中**仍是文本**，只是其"持久化接口"是非文本的。这违背了文档"造一个不是文本的接口"的口号。

**与现有 `inject_cognitive_state_into_prompt` 的过渡方案 — 不清晰 ❌**

- 该方法位于 `laap/agi/cognitive_bus.py:793`，但 `aris_cognitive_bridge.py:71` 导入的是路由版，**根本不引用 AGI 版**
- 三路径也不调用它
- 文档无废弃计划、无迁移步骤、无 feature flag

**可行性判断**：技术可行但工程规划不清晰。

---

## 第四章：风险与挑战识别

### 4.1 风险一：logit_bias 实际支持效果风险

**风险等级：高**

**影响范围**：路径一的核心能力；方案文档"认知控制力 0.2 → 0.7"目标的实现基础。

#### 4.1.1 参数格式不一致风险
- 文档示例 `logit_bias dict ← {token_id: bias_value, ...}`（第 88 行）
- 代码实际传输格式 `[[token_id, bias], ...]`（`llama_cpp.py:90-97`）
- 开发者若按文档示例直接传 dict 给 llama.cpp HTTP API，会收到 400 错误

#### 4.1.2 bias 范围风险
- `tamer.py:175-178` clamp 到 `[-100, 100]`
- 实际偏置值 ±30~50，在 softmax 后仍是压倒性概率（exp(30) ≈ 10^13）
- 可能导致生成退化为"永远输出最高 bias 的 token"
- 偏置量级未经实测调参

#### 4.1.3 中文 token 风险
- `config.yaml:42-103` 的 token ID 标注为"Holo-3.1-9B 实际 token ID"
- 但 `tamer.py:114-118` 默认连接 :8082（Holo），fallback 到 :11520（Qwen2.5-7B）
- **两套模型的 token 映射混用同一份 config**
- 中文 token 在 BPE 分词中常被拆成多 token
- `tamer.py` **从未调用** `get_tokenizer_tokens` 进行校准

#### 4.1.4 降级控制力能否达 0.7 的风险
- DeepSeek 降级路径只有温度+前缀注入，控制力提升有限
- 本地路径虽有 logit_bias，但 token 映射准确性、偏置量级、与生成质量的实际关系均未实测
- 仓库中无任何评估脚本

### 4.2 风险二：DeepSeek 降级策略有效性风险

**风险等级：高**

**影响范围**：当 DeepSeek 作为"主声带"时，整个认知控制层失效。

#### 4.2.1 "三件套"实现状态

| 件套 | 文档声称 | 代码实际 | 状态 |
|---|---|---|---|
| 温度控制 | 可用 ✅ | `tamer.py:360` + `openai_api.py:82` | ✅ 已实现 |
| 前缀注入 | 可用 ✅ | `openai_api.py:104-143` | ✅ 已实现 |
| 输出后处理+重试 | 可用 ✅ | llm_tamer 路径**完全未实现** | ❌ 缺失 |

方案文档明确承诺的"后处理校验 + 重试"在 DeepSeek 路径上不存在。

#### 4.2.2 前缀注入与现有 inject 路径冲突风险
- `aris_cognitive_bridge.py:406-473` 的 `before_turn` 已构建 `cognitive_context` 文本
- `openai_api.py:104-143` 的 `apply_cognitive_prefix` 又会向 system message 追加 `[Cognitive State]` 块
- 若两套注入同时启用，system prompt 会出现**两个独立的认知状态块**，内容部分重叠

#### 4.2.3 重试延迟风险
- DeepSeek API 单次调用通常 2-8 秒
- 3 次重试最坏 24-30 秒，对交互式对话不可接受
- 重试策略无指数退避，无超时熔断

### 4.3 风险三：self_model_nn 训练样本风险

**风险等级：高**

**影响范围**：路径三的核心可行性；方案文档"自我连续性 0.3 → 0.9"目标。

#### 4.3.1 Hermes state.db 字段不足风险
- 实际 state.db schema 仅有 `messages(id, role, content, timestamp, session_id)` 与 `sessions(id, started_at)`
- 方案文档需要的 5 维 PSI 标签（attention_focus / emotional_valence / needs_delta / self_presence_delta / certainty）**state.db 中完全没有**
- `data_pipeline.py:673-728` 的启发式推断缺乏心理学依据（如"助手回复越长能力越强"）

#### 4.3.2 "500-2000 条高质量"标准风险
- 方案文档下限 500 与 `training_plan.md` 一致
- 上限 2000 < `training_plan.md` 的最小可行 5000，标准偏松
- 当前仓库没有任何钩子落盘 CognitiveBus 快照的代码
- "高质量"数据源完全不存在

#### 4.3.3 自动模拟对话分布偏差风险
- `data_pipeline.py:307-390` 用 `random.choice` 均匀采样
- 真实分布中 `user` focus 占比 > 50%，`neutral` valence 占比 > 60%
- 均匀采样的模拟数据会让模型过度预测少数类
- `training_plan.md:67` 提到"类别不平衡：使用加权 CrossEntropy"，但模拟数据恰恰消除了不平衡，使该缓解措施无效

### 4.4 风险四：跨会话状态持久化风险

**风险等级：中**

**影响范围**：路径三的"跨会话自我连续性"核心承诺。

#### 4.4.1 state.pt schema 风险
- 文档示例用 `torch.save({...}, "state.pt")`
- 实际实现用 `np.save` 存 `.npy` + `meta.json`
- schema 与文档不一致：实际是 `.npy + meta.json` 双文件
- `meta.json` 的 `StateMetadata` 包含 7+1 字段，比文档示例丰富，但 `current_conversation_id` 在 SelfModelNN 类中未维护

#### 4.4.2 EmergentSelfModel 无持久化阻碍风险
- `aris_cognitive_bridge.py:532-539` 的 `after_tool` 仍在调用 `EmergentSelfModel`
- 两套"自我模型"并存：EmergentSelfModel（被调用、无持久化）+ SelfModelNN（有持久化、未被调用）
- 若不明确"何时切换到 SelfModelNN"，会出现"自我分裂"

#### 4.4.3 模型权重+隐藏状态+LoRA 存储管理风险
- 仓库中**无 LoRA 实现代码**
- 一旦 Phase 2 训练完成，需管理：基础模型权重（~200MB）+ LoRA 适配器（~5MB/版本）+ 隐藏状态（3KB）+ meta.json
- "每 10 次对话保存一个版本"若不清理，一年累积 ~1.8GB
- 存储清理策略、版本回滚机制完全未实现

### 风险汇总表

| 风险编号 | 风险名称 | 等级 | 主要代码证据 |
|---|---|---|---|
| 4.1 | logit_bias 实际支持效果 | 高 | `llama_cpp.py:90-97` / `attention.py:68` / `config.yaml:42-103` / `tamer.py:132` |
| 4.2 | DeepSeek 降级策略有效性 | 高 | `tamer.py:337-389` / `openai_api.py:49-102` / `aris_cognitive_bridge.py:406-473` |
| 4.3 | self_model_nn 训练样本 | 高 | `aris_psi_self_train.py:75-83` / `data_pipeline.py:673-728` / `aris_cognitive_bridge.py:491-522` |
| 4.4 | 跨会话状态持久化 | 中 | `state_manager.py:121,158-159,218-226` / `aris_cognitive_bridge.py:532-539` |

---

## 第五章：整体架构一致性检查

### 5.1 三路径协同评估

#### 5.1.1 self_model_nn → CognitiveBus → tamer+generator 数据流 — ⚠️ 部分清晰

**已清晰部分**：
- tamer 和 generator 都接收 `CognitiveStateSnapshot` 作为输入（`tamer.py:129`、`generator.py:113`）
- 两者都能从 `state.attention.focus` 提取信息

**不清晰部分（关键断裂）**：
- `SelfModelNN.forward()` 输出 `SelfStateOutput`（attention_focus: str、emotional_valence: str、arousal: float、needs: dict、self_presence: float、new_hidden_state: np.ndarray）
- `CognitiveStateSnapshot` 字段是 `needs: NeedState`、`emotion: EmotionState`、`attention: AttentionState`、`self_presence: float`、`curiosity: float`
- **两者之间没有转换函数**。代码库中无任何函数把 `SelfStateOutput` 转为 `CognitiveStateSnapshot`
- `state_manager.py:291-335` 的 `to_cognitive_context()` 只输出文本，不输出 snapshot

#### 5.1.2 三路径同时作用于同一 LLM 请求时的优先级与冲突解决 — ❌ 不清晰

**问题场景**：同一次 LLM 请求中，若同时应用：
- Path 1：`logit_bias = {token_id: -100}` 禁止某些 token
- Path 2：`grammar = "root ::= ..."` 限制输出格式
- Path 3：`temperature = 0.3`

**未定义的冲突场景**：
1. Path 1 禁止 token X，但 Path 2 的 grammar 强制必须生成 X → 谁赢？
2. Path 3 推断 low certainty → 高 temperature，但 Path 1 注意力集中 → 低 temperature → 用哪个？
3. Path 2 验证失败重试时，Path 1 的 bias 是否随重试调整？

**代码证据**：没有任何"协调器"类决定三者的优先级、合并策略、冲突回退。文档目标架构图把三路径画在同一个 "COGNITIVE CONTROLLER" 框内，但代码中也没有 `CognitiveController` 类。

#### 5.1.3 闭环循环依赖风险 — ⚠️ 部分清晰（存在隐性循环）

**显性数据流**：
```
SelfModel → CognitiveBus → Tamer.compute_bias + Generator.build_constraint → LLM
```

**隐性循环风险**：
- `SelfModelNN.step()` 接收 `cb_state: CognitiveBusState` 作为输入
- 即 CognitiveBus 既是 self_model 的**输入源**，又是 self_model 输出的**消费者**

```
CognitiveBus ──→ SelfModel.step() ──→ SelfStateOutput ──→ ??? ──→ CognitiveBus
                                              ↑
                                              └── 这里缺转换层
```

`state_manager.py:254-265` 的限幅（delta_norm > 10 截断，state_norm > 100 归一化）是单向限幅，不是循环依赖解决。

### 5.2 与现有系统集成评估

#### 5.2.1 与 `ArisCognitiveBridge.before_turn/after_turn` 的接入点 — ❌ 不清晰

**当前 before_turn 流程**（`aris_cognitive_bridge.py:397-489`）：
1. `_perceive(user_message)` → 情感检测、目标检测
2. `_select_attention(user_message)` → 注意力选择
3. `_integrate()` → 整合
4. `_cb_route(user_message)` → 调用路由版 CognitiveBus → 输出文本 `cognitive_context`
5. 返回 dict，`cognitive_context` 是字符串

**问题**：三路径需要的输入是 `CognitiveStateSnapshot` 对象，但 before_turn 内部从未构造 snapshot，也没有调用 tamer/generator 的任何方法。**三路径与 before_turn 完全未接入**。

**after_turn 同样问题**：第 491-522 行只做 `_learn(response)`，**未调用** `self_model.save_state()` 或 `self_model.online_update()`。

**代码证据**：`aris_cognitive_bridge.py:71` 只导入路由版 cognitive_bus，无任何 `from laap.laap_tools.llm_tamer import LLMTamer` 或 `from laap.laap_tools.self_model import SelfStateManager` 的导入。

#### 5.2.2 与现有 `inject_cognitive_state_into_prompt`（第 793 行）文本注入路径 — ❌ 不清晰

- 该方法位于 `laap/agi/cognitive_bus.py:793`
- 但 `aris_cognitive_bridge.py:71` 导入的是 `aris_brain/cognitive_bus.py`（路由版），**根本不引用 AGI 版**
- 该方法当前**没有被 bridge 调用**
- 三路径也不调用它（tamer/generator 直接消费 `CognitiveStateSnapshot` 对象）
- 文档未说明并存/替代关系，无废弃计划、无迁移步骤

#### 5.2.3 与 `aris_brain/cognitive_bus.py`（路由版）的协同方案 — ❌ 不清晰

**路由版职责**：处理"是否让 LLM 生成"（qre/v12 短路 direct_response）
**三路径职责**：处理"LLM 生成时如何控制"

**协同场景未定义**：
1. 路由版返回 `qre_engine`（短路 direct_response）时，三路径是否还生效？
2. 路由版返回 `psi_only`（让 LLM 自由生成）时，三路径是否增强控制？
3. 路由版输出 `cognitive_context: str`，三路径需 `CognitiveStateSnapshot` 对象，**数据结构不兼容**

#### 5.2.4 与 `aris_brain/local_llm.py`（端口 8089）的关系 — ⚠️ 部分清晰

**三套 LLM 后端并存**：

| 后端 | 端口 | 模型 | 支持 logit_bias | 用途 |
|------|------|------|----------------|------|
| local_llm.py | 8089 | Qwythos-9B | ❌ 不支持 | Aris 主力（aris_brain） |
| llama_cpp.py integrator | 8082 / 11520 | Holo-3.1-9B / Qwen2.5-7B | ✅ 支持 | tamer/generator 目标 |
| openai_api.py integrator | api.deepseek.com | DeepSeek | ❌ 不支持（降级） | 远程降级 |

**关键问题**：三路径控制的是 :8082/:11520 上的模型，但 Aris 主力 LLM 在 :8089。文档**没有说明** :8089 上的 Qwythos-9B 是主声带还是子认知核。

- 如果 :8089 是主声带 → 三路径对它无效（local_llm.py 不接受 logit_bias），认知控制力仍是 0.2
- 如果 :8082/:11520 是主声带 → 需要修改 `aris_cognitive_bridge.py` 改用三路径的集成器

### 集成评估汇总表

| 评估维度 | 判断 | 关键证据 |
|---------|------|---------|
| self_model → CB → tamer+generator 数据流 | ⚠️ 部分清晰 | tamer/generator 接口已对齐，但 SelfStateOutput→Snapshot 转换缺失 |
| 三路径优先级与冲突解决 | ❌ 不清晰 | 无 `CognitiveController` 类，无冲突回退策略 |
| 闭环循环依赖 | ⚠️ 部分清晰 | `state_manager.py:254-265` 有限幅，但无推理时环路控制 |
| 与 before_turn/after_turn 接入 | ❌ 不清晰 | `aris_cognitive_bridge.py:457-468` 仅调用路由版，未导入三路径 |
| 与第 793 行文本注入路径并存 | ❌ 不清晰 | bridge 第 71 行导入路由版，不引用 AGI 版第 793 行 |
| 与路由版 cognitive_bus 协同 | ❌ 不清晰 | 路由版输出 `cognitive_context: str`，三路径需 `CognitiveStateSnapshot` 对象 |
| 与 local_llm.py(:8089) 关系 | ⚠️ 部分清晰 | local_llm 不支持 logit_bias；:8089 与三路径关系未定义 |

---

## 第六章：结论

### 6.1 方案优势

| # | 优势 | 证据 |
|---|------|------|
| 1 | **技术方向正确**：从文本注入升级到代码级控制（logit_bias/grammar/持久状态）是认知架构的正确演进方向 | 方案文档第 5 行"从递纸条到握方向盘" |
| 2 | **三路径已有实质性实现**：非空想方案，llm_tamer 与 guided_generator 框架完整，有测试覆盖 | `test_tamer.py` 8 个测试、`test_generator.py` 14+ 测试 |
| 3 | **DeepSeek 降级策略已部分实现**：温度控制+前缀注入可用，承认 API 限制并提供降级路径 | `openai_api.py:104-143` |
| 4 | **持久化设计健壮**：state_manager 多级回退（.npy → meta.json → 零向量），首次运行友好 | `state_manager.py:161-193` |
| 5 | **训练计划文档详实**：`training_plan.md` 覆盖数据需求、训练配置、风险缓解、评估指标 | `training_plan.md` 全文 261 行 |
| 6 | **接口设计与现有 CognitiveBus 对齐**：tamer/generator 都能接收 `CognitiveStateSnapshot` | `tamer.py:129`、`generator.py:113` |
| 7 | **JSON Schema 模板比文档示例更完整**：attention_focus enum 扩展为 8 个，与 `AttentionFocus` 枚举一致 | `json_schema.py:22` |

### 6.2 潜在问题

| # | 问题 | 严重等级 | 影响范围 | 代码证据 |
|---|------|---------|---------|---------|
| 1 | **CognitiveBusState 导入 bug**：导入不存在的类名，导致 CognitiveBus=None | 高 | llm_tamer 完全无法接收真实 CognitiveBus 实例 | `tamer.py:53-59` |
| 2 | **SelfStateOutput → CognitiveStateSnapshot 转换层缺失**：三路径闭环的关键断裂点 | 高 | 三路径无法协同 | 全仓库无此转换函数 |
| 3 | **三路径与 ArisCognitiveBridge 完全未接入**：before_turn/after_turn 不调用三路径任何模块 | 高 | 三路径是孤岛，无法影响实际对话 | `aris_cognitive_bridge.py:71` |
| 4 | **self_model_nn 不是神经网络**：当前是 numpy 启发式，无任何可训练参数 | 高 | "持久神经网络自我模型"宣称不成立 | `model.py:300-358`、`model.py:434-449` |
| 5 | **训练数据源未接通**：hooks 目录无数据，session 数据 cb_state_before 全部相同 | 高 | Path 3 训练无法启动 | `aris_cognitive_bridge.py:515-516`、`data_pipeline.py:673-728` |
| 6 | **DeepSeek 降级"后处理+重试"未实现**：方案承诺的三件套只完成 2/3 | 高 | DeepSeek 作为主声带时控制力不足 | `tamer.py:337-389`、`openai_api.py:49-102` |
| 7 | **三套 LLM 后端并存且关系未定义**：:8082/:8089/:11520+DeepSeek 无主声带归属 | 高 | 三路径可能控制错后端 | `local_llm.py:39-40`、`config.yaml:7-8` |
| 8 | **token 映射两套模型混用同一份 config**：Holo/Qwen token ID 不同 | 中 | fallback 模式下偏置打错 token | `config.yaml:42-103`、`tamer.py:114-118` |
| 9 | **state_manager 与 model 状态分段假设不一致**：6 段 vs 5 段切法 | 中 | 注入文本与模型输出语义脱节 | `state_manager.py:402-432`、`model.py:332-342` |
| 10 | **两套重试循环可能产生 N×M 次调用**：generator 外层 + content_validator 内层 | 中 | DeepSeek API 调用量翻倍 | `generator.py:165-217`、`content_validator.py:85-132` |
| 11 | **grammar 中文支持移除**：memory_ref grammar 移除 CJK，与文档 \u4e00-\u9fff 冲突 | 中 | 中文记忆引用无法工作 | `grammar_bnf.py:52-54` |
| 12 | **无 CognitiveController 协调器**：三路径冲突解决策略未定义 | 中 | 同时作用时可能互相矛盾 | 全仓库无此类 |
| 13 | **LoRA 版本管理未实现**：无清理策略、无回滚机制 | 中 | 存储膨胀、无法回滚退化 | `state_manager.py` 无版本快照 |
| 14 | **模拟数据分布偏差**：均匀采样与真实长尾分布相反 | 中 | 模型过度预测少数类 | `data_pipeline.py:307-390` |

### 6.3 改进建议

#### 针对问题 1（导入 bug）— P0 立即修复
```python
# tamer.py:53-59 修改为：
try:
    from laap.agi.cognitive_bus import (
        CognitiveBus,
        CognitiveStateSnapshot,  # ← 改为正确的类名
    )
except ImportError:
    CognitiveBus = None
    CognitiveStateSnapshot = None
```

#### 针对问题 2（转换层缺失）— P0 实现
在 `laap/laap_tools/self_model/` 新增 `adapter.py`：
```python
def self_state_output_to_snapshot(
    output: SelfStateOutput,
    base_snapshot: CognitiveStateSnapshot
) -> CognitiveStateSnapshot:
    """将 SelfModelNN 输出转换为 CognitiveStateSnapshot"""
    # 构造新的 NeedState/EmotionState/AttentionState
    # 保留 base_snapshot 的其他字段
```

#### 针对问题 3（未接入 bridge）— P0 实现
在 `aris_cognitive_bridge.py` 的 `before_turn` 中新增：
- 第 426 行 `_select_attention` 之后：调用 `self_model.step()`
- 第 458 行 `_cb_route` 之前/之后：调用 `tamer.compute_bias()` 和 `generator.build_constraint()`
- 返回 dict 增加 `logit_bias`、`grammar`、`temperature` 字段

#### 针对问题 4（self_model_nn 不是神经网络）— P1 重新实现
- 在 `model.py` 中引入 `torch.nn.Module` 基类
- 实现真正的 Transformer 主体（参考 SmolLM2 架构）
- 实现 `from_pretrained()` 加载 HuggingFace 权重
- 当前 numpy 启发式可作为"零样本基线"保留

#### 针对问题 5（训练数据源）— P1 接入钩子
在 `aris_cognitive_bridge.py:491` 的 `after_turn` 内新增：
- 落盘 `TrainingSample`（before_state + after_state + dialogue）到 hooks 目录
- 格式与 `data_pipeline.py:59-106` 的 `TrainingSample` dataclass 对齐

#### 针对问题 6（DeepSeek 后处理）— P1 实现
在 `tamer.py:337-389` 的 `apply_to_deepseek` 中新增：
- 调用 `ContentValidator.validate_with_retry`
- 实现指数退避重试（base=0.5s, max=3 次）
- 超时熔断（总等待 < 10s）

#### 针对问题 7（三套 LLM 后端）— P0 明确决策
建议方案：
- **:8082（Holo-3.1-9B）作为主声带**，享受完整 logit_bias 控制
- :8089（Qwythos-9B）降级为"长上下文处理专用"（512K context 优势）
- :11520（Qwen2.5-7B）作为 fallback
- DeepSeek 作为远程降级

### 6.4 实施优先级建议

#### P0 — 启动前必须完成（阻塞项）

| 优先级 | 任务 | 依据 | 预估工作量 |
|--------|------|------|-----------|
| P0-1 | 修复 `CognitiveBusState` → `CognitiveStateSnapshot` 导入 bug | 问题 1，阻塞 llm_tamer | 0.5 天 |
| P0-2 | 实现 `SelfStateOutput → CognitiveStateSnapshot` 转换层 | 问题 2，阻塞三路径闭环 | 1-2 天 |
| P0-3 | 明确 LLM 后端主声带归属（建议 :8082） | 问题 7，阻塞所有路径 | 决策 + 0.5 天 |
| P0-4 | 在 `ArisCognitiveBridge.before_turn` 中接入三路径调用 | 问题 3，三路径是孤岛 | 2-3 天 |

#### P1 — 第一阶段实施（Week 1-4 调整后）

| 优先级 | 任务 | 依据 | 预估工作量 |
|--------|------|------|-----------|
| P1-1 | 在 `after_turn` 中落盘 TrainingSample 到 hooks 目录 | 问题 5，训练数据源 | 1-2 天 |
| P1-2 | 实现 DeepSeek 降级的后处理+重试 | 问题 6，降级策略完整性 | 1-2 天 |
| P1-3 | 修复 grammar 中文支持（使用 \u4e00-\u9fff 区间） | 问题 11，中文记忆引用 | 0.5 天 |
| P1-4 | 统一两套重试循环 | 问题 10，API 调用量 | 0.5 天 |
| P1-5 | 修复 state_manager 与 model 状态分段不一致 | 问题 9，语义脱节 | 1 天 |

#### P2 — 第二阶段实施（Week 5+）

| 优先级 | 任务 | 依据 | 预估工作量 |
|--------|------|------|-----------|
| P2-1 | 实现 `CognitiveController` 协调器 | 问题 12，冲突解决 | 2-3 天 |
| P2-2 | 重新实现 self_model_nn 为真正的神经网络 | 问题 4，"神经网络"宣称 | 5-7 天 |
| P2-3 | 实现 LoRA 在线微调 + 版本管理 | 问题 13，存储膨胀 | 3-5 天 |
| P2-4 | 修正模拟数据分布（按真实长尾分布采样） | 问题 14，分布偏差 | 1 天 |
| P2-5 | 新增三路径联合集成测试 | 产出物不可验证 | 2-3 天 |

#### 路径优先级排序

**P0（立即启动）：Path 1（llm_tamer）+ Path 2（guided_generator）**
- 理由：框架已完整，修复导入 bug 后即可运行；本地路径有完整 logit_bias 支持；可独立验证

**P1（紧随其后）：Path 3 数据管道 + 真实数据积累**
- 理由：训练数据是 Path 3 的命脉，必须先接通钩子；模拟数据无意义

**P2（条件成熟后）：Path 3 模型训练 + 三路径闭环**
- 理由：依赖 P0-2 转换层、P1-1 真实数据、P2-2 真正神经网络实现

---

## 附录：代码证据索引

### llm_tamer 相关
| 证据 | 文件路径 | 行号 |
|------|---------|------|
| CognitiveBusState 导入 bug | `laap/laap_tools/llm_tamer/tamer.py` | 53-59 |
| compute_bias 接口 | `laap/laap_tools/llm_tamer/tamer.py` | 129-180 |
| 偏置 clamp 范围 | `laap/laap_tools/llm_tamer/tamer.py` | 175-178 |
| apply_to_deepseek 无重试 | `laap/laap_tools/llm_tamer/tamer.py` | 337-389 |
| LlamaCppIntegrator 端口配置 | `laap/laap_tools/llm_tamer/integrators/llama_cpp.py` | 37-39 |
| logit_bias 格式转换 | `laap/laap_tools/llm_tamer/integrators/llama_cpp.py` | 90-97 |
| DeepSeek 降级前缀注入 | `laap/laap_tools/llm_tamer/integrators/openai_api.py` | 104-143 |
| 偏置强度 15.0 倍数 | `laap/laap_tools/llm_tamer/bias_computers/attention.py` | 68 |
| Token 映射配置 | `laap/laap_tools/llm_tamer/config.yaml` | 42-103 |

### guided_generator 相关
| 证据 | 文件路径 | 行号 |
|------|---------|------|
| generate 同步而非异步 | `laap/laap_tools/guided_generator/generator.py` | 113 |
| 外层重试循环 | `laap/laap_tools/guided_generator/generator.py` | 165-217 |
| infer_constraint_type 未被自动调用 | `laap/laap_tools/guided_generator/generator.py` | 280-349 |
| JSON Schema 转义 bug | `laap/laap_tools/guided_generator/constraints/json_schema.py` | 164 |
| 中文 grammar 兼容性问题 | `laap/laap_tools/guided_generator/constraints/grammar_bnf.py` | 52-54 |
| ContentValidator 独立重试 | `laap/laap_tools/guided_generator/validators/content_validator.py` | 85-132 |

### self_model 相关
| 证据 | 文件路径 | 行号 |
|------|---------|------|
| forward 是纯启发式 | `laap/laap_tools/self_model/model.py` | 300-358 |
| from_pretrained 抛 NotImplementedError | `laap/laap_tools/self_model/model.py` | 434-449 |
| 状态分段 5 段切法 | `laap/laap_tools/self_model/model.py` | 332-342 |
| 状态分段 6 段切法（不一致） | `laap/laap_tools/self_model/state_manager.py` | 402-432 |
| .npy 而非 .pt 持久化 | `laap/laap_tools/self_model/state_manager.py` | 121, 158-159, 218-226 |
| to_cognitive_context 文本注入 | `laap/laap_tools/self_model/state_manager.py` | 291-335 |
| 状态限幅 | `laap/laap_tools/self_model/state_manager.py` | 254-265 |
| 启发式标签推断 | `laap/laap_tools/self_model/data_pipeline.py` | 673-728 |
| 均匀采样模拟数据 | `laap/laap_tools/self_model/data_pipeline.py` | 307-390 |
| 训练计划 | `laap/laap_tools/self_model/training_plan.md` | 全文 |

### 现有基础设施相关
| 证据 | 文件路径 | 行号 |
|------|---------|------|
| CognitiveStateSnapshot 定义 | `laap/agi/cognitive_bus.py` | 169 |
| inject_cognitive_state_into_prompt | `laap/agi/cognitive_bus.py` | 793 |
| before_turn 主实现 | `aris_brain/aris_cognitive_bridge.py` | 397-489 |
| after_turn 主实现 | `aris_brain/aris_cognitive_bridge.py` | 491-522 |
| bridge 导入路由版 cognitive_bus | `aris_brain/aris_cognitive_bridge.py` | 71 |
| bridge 仍用 EmergentSelfModel | `aris_brain/aris_cognitive_bridge.py` | 532-539 |
| 路由版 CognitiveBus | `aris_brain/cognitive_bus.py` | 45, 141 |
| local_llm 端口 8089 | `aris_brain/local_llm.py` | 39-40 |
| local_llm 不支持 logit_bias | `aris_brain/local_llm.py` | 190-251 |
| MemoryStore 嵌入 384 维 | `aris_brain/memory_store.py` | 49, 152 |
| state.db schema | `aris_brain/aris_psi_self_train.py` | 75-83 |
| EmergentSelfModel 无持久化 | `laap/agi/self_model.py` | 178 |

---

> **评估结论**：方案技术方向正确，三路径已有实质性实现，但存在 4 个高严重度阻塞问题（导入 bug、转换层缺失、未接入 bridge、self_model 不是神经网络）和 3 个高严重度风险（训练数据源、DeepSeek 降级、三套后端）。建议按 P0→P1→P2 顺序推进，调整 Week 3-4 的 Path 3 训练时间节点至 Week 5-6，先完成数据钩子接入与真实数据积累。
