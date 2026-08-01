"""
self_model_nn — Model Skeleton (模型骨架定义)
=============================================

当前版本只定义模型架构的骨架，不进行训练。
为后续连接真实 PyTorch 模型做准备。

模型架构选择 (注释说明):
  推荐方案: SmolLM2-360M + custom 持久状态头
  备选方案: Qwen2.5-0.5B (与现有 Qwen 系列模型同族)
  轻量方案: BERT-tiny + MLP head (仅 4M 参数，不适合复杂自我)

设计原则:
  - 无 torch/transformers 依赖 (只用 numpy + 标准库)
  - forward() 返回模拟输出 (骨架阶段)
  - 所有接口与未来 torch 实现 API 兼容
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np

logger = logging.getLogger("laap.self_model.model")


# ═══════════════════════════════════════════════════════════════
# 模型配置
# ═══════════════════════════════════════════════════════════════

@dataclass
class SelfModelConfig:
    """
    self_model_nn 配置 dataclass。

    未来会直接传递给 HuggingFace AutoConfig 或自定义 Transformer 构造器。

    Attributes:
        model_type: 模型类型 ("smol_lm2" | "qwen2.5" | "bert" | "dummy")
        hidden_dim: Transformer hidden 维度
        num_layers: Transformer 层数
        num_heads: 注意力头数
        vocab_size: 词表大小
        state_dim: 持久状态向量维度
        use_persistent_state: 是否使用跨会话持久状态
        dropout: Dropout 比率
        max_seq_len: 最大序列长度
    """
    model_type: str = "smol_lm2"
    hidden_dim: int = 768
    num_layers: int = 6
    num_heads: int = 8
    vocab_size: int = 49152       # SmolLM2 词表大小
    state_dim: int = 768          # 持久状态维度 (与 hidden_dim 一致)
    use_persistent_state: bool = True
    dropout: float = 0.1
    max_seq_len: int = 512

    # 输出头配置
    num_attention_foci: int = 8   # 注意力焦点类别数
    num_emotional_valences: int = 7  # 情感效价类别数
    num_needs: int = 5            # PSI 需求维度数

    def to_dict(self) -> Dict[str, Any]:
        return {
            "model_type": self.model_type,
            "hidden_dim": self.hidden_dim,
            "num_layers": self.num_layers,
            "num_heads": self.num_heads,
            "vocab_size": self.vocab_size,
            "state_dim": self.state_dim,
            "use_persistent_state": self.use_persistent_state,
            "dropout": self.dropout,
            "max_seq_len": self.max_seq_len,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SelfModelConfig":
        return cls(**{k: v for k, v in data.items()
                      if k in cls.__dataclass_fields__})


# ═══════════════════════════════════════════════════════════════
# 模型输出类型
# ═══════════════════════════════════════════════════════════════

@dataclass
class SelfStateOutput:
    """
    self_model 前向传播的完整输出。

    这是 NN 输出的结构化表示，包含了预测的认知状态。

    Attributes:
        attention_focus: 预测的注意力焦点
        emotional_valence: 预测的情感效价
        arousal: 预测的唤醒度 [0, 1]
        needs: 预测的 PSI 需求值
        self_presence: 预测的自我存在感 [0, 1]
        certainty: 预测的确定性 [0, 1]
        new_hidden_state: 更新后的持久隐藏状态 (state_dim,)
        narrative_token: 简短自我叙事文本（可选）
    """
    attention_focus: str = "idle"
    emotional_valence: str = "neutral"
    arousal: float = 0.5
    needs: Dict[str, float] = field(default_factory=lambda: {
        "competence": 0.5, "autonomy": 0.5,
        "relatedness": 0.5, "certainty": 0.5, "growth": 0.5,
    })
    self_presence: float = 0.5
    certainty: float = 0.5
    new_hidden_state: Optional[np.ndarray] = None
    narrative_token: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "attention_focus": self.attention_focus,
            "emotional_valence": self.emotional_valence,
            "arousal": round(self.arousal, 4),
            "needs": {k: round(v, 4) for k, v in self.needs.items()},
            "self_presence": round(self.self_presence, 4),
            "certainty": round(self.certainty, 4),
            "new_hidden_state_norm": round(
                float(np.linalg.norm(self.new_hidden_state)), 4
            ) if self.new_hidden_state is not None else None,
            "narrative_token": self.narrative_token,
        }


# ═══════════════════════════════════════════════════════════════
# 输出头配置 (供训练脚本使用)
# ═══════════════════════════════════════════════════════════════

class OutputHeadConfig:
    """
    输出头配置 — 描述模型的输出头结构。

    每个输出头有:
      - name: 名称
      - type: "classifier" (分类) | "regressor" (回归)
      - input_dim: 输入维度
      - output_dim: 输出维度
      - loss: 推荐损失函数
      - weight: 多任务损失权重
    """
    def __init__(self):
        self.heads = [
            {"name": "attention_focus",
             "type": "classifier",
             "input_dim": 768,
             "output_dim": 8,      # 8 种注意力焦点
             "loss": "cross_entropy",
             "weight": 1.0},
            {"name": "emotional_valence",
             "type": "classifier",
             "input_dim": 768,
             "output_dim": 7,      # 7 种情感效价
             "loss": "cross_entropy",
             "weight": 1.0},
            {"name": "arousal",
             "type": "regressor",
             "input_dim": 768,
             "output_dim": 1,
             "loss": "mse",
             "weight": 0.5},
            {"name": "needs",
             "type": "regressor",
             "input_dim": 768,
             "output_dim": 5,      # 5 种 PSI 需求
             "loss": "mse",
             "weight": 1.0},
            {"name": "self_presence",
             "type": "regressor",
             "input_dim": 768,
             "output_dim": 1,
             "loss": "mse",
             "weight": 0.5},
            {"name": "certainty",
             "type": "regressor",
             "input_dim": 768,
             "output_dim": 1,
             "loss": "mse",
             "weight": 0.5},
            {"name": "state_update",
             "type": "state_update",
             "input_dim": 768,
             "output_dim": 768,   # 新的隐藏状态
             "loss": "cosine_similarity",
             "weight": 2.0},
        ]

    def to_dict(self) -> List[Dict[str, Any]]:
        return self.heads

    def total_loss_weight(self) -> float:
        return sum(h["weight"] for h in self.heads)


# ═══════════════════════════════════════════════════════════════
# 模型骨架
# ═══════════════════════════════════════════════════════════════

class SelfModelNN:
    """
    小型 Transformer 自我模型骨架。

    架构描述:
        Input: [persistent_state(768) + cb_state_embedding(128) + memory_context(128)]
               → concatenated vector (1024,)
        Processing: Transformer × N layers (未来实现)
        Output heads:
          - attention_classifier → 8 classes
          - emotion_classifier → 7 classes
          - needs_regressor → 5 dims
          - presence_regressor → 1 dim
          - certainty_regressor → 1 dim
          - state_update → 768 dim (新隐藏状态)

    注意:
      当前版本是骨架定义。forward() 返回模拟输出。
      训练在第二阶段进行。

    Usage:
        config = SelfModelConfig(hidden_dim=768)
        model = SelfModelNN(config)

        # 模拟输入
        state_vec = np.random.randn(768).astype(np.float32)
        cb_emb = np.random.randn(128).astype(np.float32)
        mem_emb = np.random.randn(128).astype(np.float32)
        dia_emb = np.random.randn(768).astype(np.float32)

        output = model.forward(state_vec, cb_emb, mem_emb, dia_emb)
        print(output.attention_focus)
    """

    def __init__(self, config: SelfModelConfig):
        """
        Args:
            config: 模型配置
        """
        self.config = config
        self.output_heads = OutputHeadConfig()
        self._training: bool = False

        # 输出头名称索引 (供输出头配置查询)
        self._head_names = [h["name"] for h in self.output_heads.heads]

        # 统计
        self.total_parameters: int = self._estimate_params()

        logger.info(
            f"SelfModelNN initialized (type={config.model_type}, "
            f"hidden_dim={config.hidden_dim}, "
            f"layers={config.num_layers}, "
            f"states={config.state_dim}, "
            f"estimated_params={self.total_parameters:,})"
        )

    @property
    def is_training(self) -> bool:
        return self._training

    def train(self, mode: bool = True):
        """设置训练/评估模式。"""
        self._training = mode
        logger.debug(f"SelfModelNN {'training' if mode else 'eval'} mode")

    def eval(self):
        """设置评估模式。"""
        self.train(False)

    def forward(self, state_vec: np.ndarray, cb_state_emb: np.ndarray,
                mem_emb: np.ndarray, dialogue_emb: np.ndarray) -> SelfStateOutput:
        """
        前向传播。

        当前版本返回基于输入的随机/规则驱动模拟输出。
        真实实现将在 Phase 2 (模型训练) 中提供。

        Args:
            state_vec: 持久隐藏状态向量 (state_dim,)
            cb_state_emb: 认知总线状态嵌入 (128,)
            mem_emb: 记忆上下文嵌入 (128,)
            dialogue_emb: 对话上下文嵌入 (768,)

        Returns:
            SelfStateOutput: 预测的认知状态
        """
        # 确保输入为 numpy 数组
        state_vec = np.asarray(state_vec, dtype=np.float32)
        cb_state_emb = np.asarray(cb_state_emb, dtype=np.float32)
        mem_emb = np.asarray(mem_emb, dtype=np.float32)
        dialogue_emb = np.asarray(dialogue_emb, dtype=np.float32)

        # ── Phase 1 骨架行为: 启发式规则输出 ──

        # 1. 从 dialogue_emb 推断注意力
        state_norm = float(np.linalg.norm(state_vec))
        if self._training:
            # 训练模式: 添加一些随机性
            rng = np.random.default_rng()
            attention_probs = rng.dirichlet(np.ones(8))  # 随机分布
            attention_focus = ["user", "task", "self", "environment",
                               "memory", "planning", "learning", "idle"][
                int(np.argmax(attention_probs))
            ]
        else:
            # 评估模式: 使用规则推断
            attention_focus = self._heuristic_attention(state_vec, dialogue_emb)

        # 2. 推断情感
        if self._training:
            valences = ["positive_high", "positive_mild", "neutral",
                        "negative_mild", "negative_high", "curious", "confused"]
            emotional_valence = str(np.random.default_rng().choice(valences))
        else:
            emotional_valence = self._heuristic_emotion(state_vec, dialogue_emb)

        # 3. 推断数值输出
        arousal = float(np.clip(
            np.mean(np.abs(dialogue_emb)) * 0.5 + 0.3 +
            (0.1 * (np.random.random() - 0.5) if self._training else 0.0),
            0.0, 1.0
        ))

        needs = {
            "competence": float(np.clip(
                np.mean(np.abs(state_vec[0:160])) * 0.5 + 0.3, 0.0, 1.0)),
            "autonomy": float(np.clip(
                np.mean(np.abs(state_vec[160:320])) * 0.5 + 0.3, 0.0, 1.0)),
            "relatedness": float(np.clip(
                np.mean(np.abs(state_vec[320:480])) * 0.5 + 0.3, 0.0, 1.0)),
            "certainty": float(np.clip(
                np.mean(np.abs(state_vec[480:640])) * 0.5 + 0.3, 0.0, 1.0)),
            "growth": float(np.clip(
                np.mean(np.abs(state_vec[640:768])) * 0.5 + 0.3, 0.0, 1.0)),
        }

        self_presence = float(np.clip(
            np.mean(np.abs(state_vec)) * 0.3 + 0.4, 0.0, 1.0))
        certainty = float(np.clip(
            1.0 - np.std(state_vec) * 0.5, 0.2, 0.95))

        # 4. 计算新隐藏状态 (加法更新 + 非线性)
        # 模拟: 对话嵌入 + 状态衰减 + 噪声
        state_decay = state_vec * 0.05  # 缓慢衰减
        dialogue_influence = dialogue_emb * np.tanh(np.linalg.norm(dialogue_emb)) * 0.1
        if self._training:
            noise = np.random.randn(self.config.state_dim).astype(np.float32) * 0.01
        else:
            noise = np.zeros(self.config.state_dim, dtype=np.float32)

        new_hidden_state = state_vec - state_decay + dialogue_influence + noise
        # 归一化: 保持状态稳定
        new_norm = np.linalg.norm(new_hidden_state)
        if new_norm > 50.0:
            new_hidden_state *= (50.0 / new_norm)

        # 5. 简短叙事 (规则生成)
        if attention_focus == "user":
            narrative = "I am engaged with the user."
        elif attention_focus == "self":
            narrative = "I am reflecting on myself."
        elif attention_focus == "task":
            narrative = "I am focused on the task."
        elif attention_focus == "memory":
            narrative = "I am recalling past experiences."
        else:
            narrative = "I am present and aware."

        output = SelfStateOutput(
            attention_focus=attention_focus,
            emotional_valence=emotional_valence,
            arousal=arousal,
            needs=needs,
            self_presence=self_presence,
            certainty=certainty,
            new_hidden_state=new_hidden_state,
            narrative_token=narrative,
        )

        logger.debug(
            f"Forward pass: attn={output.attention_focus}, "
            f"emotion={output.emotional_valence}, "
            f"state_norm={np.linalg.norm(new_hidden_state):.4f}"
        )

        return output

    def get_output_heads_config(self) -> Dict[str, Any]:
        """
        返回输出头的配置信息。

        Returns:
            {
                "heads": [...],
                "total_loss_weight": float,
                "num_heads": int,
            }
        """
        return {
            "heads": self.output_heads.to_dict(),
            "total_loss_weight": self.output_heads.total_loss_weight(),
            "num_heads": len(self.output_heads.heads),
        }

    def get_parameter_count(self) -> Dict[str, int]:
        """
        返回估算的参数计数。

        Returns:
            {
                "total": int,
                "transformer": int,
                "output_heads": int,
                "embeddings": int,
            }
        """
        return {
            "total": self.total_parameters,
            "transformer": int(self.total_parameters * 0.85),
            "output_heads": int(self.total_parameters * 0.05),
            "embeddings": int(self.total_parameters * 0.10),
        }

    # ── 训练目标与损失函数 ────────────────────────────────────

    def compute_loss(self, output: SelfStateOutput, target: Dict[str, Any]) -> Dict[str, float]:
        """
        计算多任务损失。
        
        损失组成:
          1. 情感一致性损失: self_model 预测的情感应与 PSI 循环实际情感一致
          2. 注意力预测损失: 预测的注意力焦点应反映实际对话模式
          3. 需求预测损失: PSI 需求预测误差
          4. 自我存在感损失: 自我存在感预测误差
          5. 状态连贯性损失: 隐藏状态更新应保持语义连贯
        
        Args:
            output: self_model 前向传播输出
            target: 目标标签字典，包含:
                - "emotional_valence": 目标情感标签
                - "attention_focus": 目标注意力焦点
                - "needs": 目标需求值 dict
                - "self_presence": 目标自我存在感
                - "arousal": 目标唤醒度
                - "prev_state": 上一轮隐藏状态 (用于连贯性损失)
        
        Returns:
            损失字典，包含各任务损失和总损失
        """
        losses = {}
        total_loss = 0.0

        # 1. 情感一致性损失 (Cross-Entropy)
        if "emotional_valence" in target:
            valence_classes = ["positive_high", "positive_mild", "neutral",
                              "negative_mild", "negative_high", "curious", "confused"]
            target_idx = valence_classes.index(target["emotional_valence"]) if target["emotional_valence"] in valence_classes else 2
            pred_idx = valence_classes.index(output.emotional_valence) if output.emotional_valence in valence_classes else 2
            
            # 简化的交叉熵: 正确类概率的负对数
            loss_emotion = -np.log(0.9 if target_idx == pred_idx else 0.1) * 1.0
            losses["emotion_consistency"] = float(loss_emotion)
            total_loss += loss_emotion

        # 2. 注意力预测损失 (Cross-Entropy)
        if "attention_focus" in target:
            attention_classes = ["user", "task", "self", "environment",
                               "memory", "planning", "learning", "idle"]
            target_idx = attention_classes.index(target["attention_focus"]) if target["attention_focus"] in attention_classes else 7
            pred_idx = attention_classes.index(output.attention_focus) if output.attention_focus in attention_classes else 7
            
            loss_attention = -np.log(0.85 if target_idx == pred_idx else 0.15 / 7) * 0.8
            losses["attention_prediction"] = float(loss_attention)
            total_loss += loss_attention

        # 3. 需求预测损失 (MSE)
        if "needs" in target and isinstance(target["needs"], dict):
            target_needs = target["needs"]
            pred_needs = output.needs
            mse_sum = 0.0
            count = 0
            for key in ["competence", "autonomy", "relatedness", "certainty", "growth"]:
                if key in target_needs and key in pred_needs:
                    mse_sum += (float(target_needs[key]) - float(pred_needs[key])) ** 2
                    count += 1
            if count > 0:
                loss_needs = (mse_sum / count) * 1.0
                losses["needs_prediction"] = float(loss_needs)
                total_loss += loss_needs

        # 4. 自我存在感损失 (MSE)
        if "self_presence" in target:
            loss_presence = (float(target["self_presence"]) - float(output.self_presence)) ** 2 * 0.5
            losses["self_presence"] = float(loss_presence)
            total_loss += loss_presence

        # 5. 唤醒度损失 (MSE)
        if "arousal" in target:
            loss_arousal = (float(target["arousal"]) - float(output.arousal)) ** 2 * 0.5
            losses["arousal"] = float(loss_arousal)
            total_loss += loss_arousal

        # 6. 状态连贯性损失 (Cosine Distance)
        # 新状态应与旧状态保持一定的余弦相似度
        if "prev_state" in target and output.new_hidden_state is not None:
            prev_state = np.asarray(target["prev_state"], dtype=np.float32)
            new_state = output.new_hidden_state
            
            prev_norm = np.linalg.norm(prev_state)
            new_norm = np.linalg.norm(new_state)
            
            if prev_norm > 0.01 and new_norm > 0.01:
                cos_sim = float(np.dot(prev_state, new_state) / (prev_norm * new_norm))
                # 目标余弦相似度: 0.9 (高连贯性)
                loss_coherence = (1.0 - cos_sim) * 2.0
                losses["state_coherence"] = float(loss_coherence)
                total_loss += loss_coherence

        # 7. 价值取向损失 (需求稳定性正则化)
        # 需求向量不应剧烈波动
        if "prev_needs" in target and isinstance(target["prev_needs"], dict):
            prev_needs = target["prev_needs"]
            pred_needs = output.needs
            stability_sum = 0.0
            count = 0
            for key in ["competence", "autonomy", "relatedness", "certainty", "growth"]:
                if key in prev_needs and key in pred_needs:
                    stability_sum += abs(float(prev_needs[key]) - float(pred_needs[key]))
                    count += 1
            if count > 0:
                loss_stability = (stability_sum / count) * 0.3
                losses["value_stability"] = float(loss_stability)
                total_loss += loss_stability

        losses["total"] = float(total_loss)
        
        logger.debug(f"Loss computed: {losses}")
        return losses

    def update_with_loss(self, output: SelfStateOutput, target: Dict[str, Any],
                        learning_rate: float = 0.001) -> Dict[str, float]:
        """
        基于损失更新模型参数（模拟梯度下降）。
        
        当前版本使用规则驱动的状态更新，真实梯度下降将在 Phase 2 实现。
        
        Args:
            output: self_model 前向传播输出
            target: 目标标签字典
            learning_rate: 学习率
        
        Returns:
            损失字典
        """
        losses = self.compute_loss(output, target)
        
        if self._training and output.new_hidden_state is not None:
            # 模拟梯度更新: 根据损失调整状态更新幅度
            total_loss = losses["total"]
            
            if total_loss > 1.0:
                output.new_hidden_state *= (1.0 - learning_rate * total_loss * 0.1)
            elif total_loss < 0.1:
                output.new_hidden_state *= (1.0 + learning_rate * 0.05)
        
        return losses

    # ── 工厂方法 ────────────────────────────────────────────

    @classmethod
    def from_pretrained(cls, model_name: str) -> "SelfModelNN":
        """
        从 HuggingFace 加载预训练模型（占位 — 第二阶段实现）。

        Args:
            model_name: HuggingFace 模型名称 (如 "HuggingFaceTB/SmolLM2-360M-Instruct")

        Returns:
            SelfModelNN 实例

        Raises:
            NotImplementedError: Phase 1 未实现
        """
        raise NotImplementedError(
            "从预训练模型加载将在 Phase 2 (模型训练) 中实现。"
        )

    # ── 内部方法 ────────────────────────────────────────────

    def _estimate_params(self) -> int:
        """估算模型参数总数。"""
        cfg = self.config
        # Transformer 参数估算:
        #   embeddings: vocab_size * hidden_dim
        #   per layer: 4 * hidden_dim^2 + 2 * hidden_dim * 4 * hidden_dim
        #   total: embeddings + layers * per_layer + output_heads
        emb_params = cfg.vocab_size * cfg.hidden_dim
        per_layer = 4 * cfg.hidden_dim * cfg.hidden_dim + \
                    2 * cfg.hidden_dim * (4 * cfg.hidden_dim)
        transformer_params = cfg.num_layers * per_layer
        head_params = cfg.hidden_dim * (cfg.num_attention_foci +
                                         cfg.num_emotional_valences +
                                         cfg.num_needs + 3)
        return emb_params + transformer_params + head_params

    def _heuristic_attention(
        self, state_vec: np.ndarray, dialogue_emb: np.ndarray
    ) -> str:
        """基于规则的注意力焦点推断。"""
        # 使用状态向量的不同段加权
        scores = {
            "user": float(np.mean(np.abs(state_vec[0:96]))),
            "task": float(np.mean(np.abs(state_vec[96:192]))),
            "self": float(np.mean(np.abs(state_vec[192:288]))),
            "memory": float(np.mean(np.abs(state_vec[288:384]))),
            "planning": float(np.mean(np.abs(state_vec[384:480]))),
            "learning": float(np.mean(np.abs(state_vec[480:576]))),
            "environment": float(np.mean(np.abs(state_vec[576:672]))),
            "idle": float(np.mean(np.abs(state_vec[672:768]))),
        }
        # 加入对话嵌入的微弱影响
        dialogue_energy = float(np.linalg.norm(dialogue_emb))
        if dialogue_energy > 5.0:
            scores["user"] *= 1.2
        if dialogue_energy < 1.0:
            scores["idle"] *= 1.5

        return max(scores, key=scores.get)

    def _heuristic_emotion(
        self, state_vec: np.ndarray, dialogue_emb: np.ndarray
    ) -> str:
        """基于规则的情感推断。"""
        valence_region = state_vec[384:512]
        valence_score = float(np.mean(valence_region))

        if valence_score > 0.4:
            return "positive_mild"
        elif valence_score < -0.4:
            return "negative_mild"
        else:
            return "neutral"


# ═══════════════════════════════════════════════════════════════
# 工厂函数
# ═══════════════════════════════════════════════════════════════

def create_model(config: Optional[SelfModelConfig] = None,
                 model_type: str = "dummy") -> SelfModelNN:
    """
    创建 self_model 实例的工厂函数。

    Args:
        config: 模型配置 (可选，默认使用标准配置)
        model_type: 模型类型快捷选择

    Returns:
        SelfModelNN 实例

    示例:
        model = create_model(model_type="dummy")
        model = create_model(SelfModelConfig(hidden_dim=512))
    """
    if config is None:
        config = SelfModelConfig(model_type=model_type)

    return SelfModelNN(config)


# ═══════════════════════════════════════════════════════════════
# 输入嵌入辅助 (供数据管道使用)
# ═══════════════════════════════════════════════════════════════

class SelfModelInputEncoder:
    """
    将非结构化数据编码为模型输入嵌入。

    在 Phase 1，这只是大小/形状占位。
    Phase 2 会使用实际的 tokenizer + embedder。
    """

    def __init__(self, state_dim: int = 768, cb_emb_dim: int = 128,
                 mem_emb_dim: int = 128, dial_emb_dim: int = 768):
        self.state_dim = state_dim
        self.cb_emb_dim = cb_emb_dim
        self.mem_emb_dim = mem_emb_dim
        self.dial_emb_dim = dial_emb_dim

    def encode_cb_state(self, cb_state: Dict[str, Any]) -> np.ndarray:
        """
        将 CognitiveBus 状态编码为嵌入向量。

        Args:
            cb_state: 认知状态字典

        Returns:
            嵌入向量 (cb_emb_dim,)
        """
        emb = np.zeros(self.cb_emb_dim, dtype=np.float32)
        if not cb_state:
            return emb

        # 从状态字典中提取数值特征
        idx = 0
        for key in ["attention", "emotion", "needs", "self_presence",
                     "curiosity", "arousal"]:
            if key in cb_state:
                val = cb_state[key]
                if isinstance(val, (int, float)):
                    emb[idx % self.cb_emb_dim] = float(val)
                elif isinstance(val, dict):
                    for sub_key, sub_val in val.items():
                        if isinstance(sub_val, (int, float)):
                            emb[(idx + hash(sub_key)) % self.cb_emb_dim] = float(sub_val)
                            idx += 1
                idx += 1

        return emb / max(1.0, float(np.linalg.norm(emb)))

    def encode_memory_context(self, memories: List[str]) -> np.ndarray:
        """
        将记忆上下文编码为嵌入向量。

        Args:
            memories: 记忆文本列表

        Returns:
            嵌入向量 (mem_emb_dim,)
        """
        emb = np.zeros(self.mem_emb_dim, dtype=np.float32)
        if not memories:
            return emb

        # 占位: 用平均哈希编码
        for i, mem in enumerate(memories[:10]):
            mem_hash = hash(mem) % 1000
            emb[i % self.mem_emb_dim] += (mem_hash / 1000.0)

        return emb / max(1.0, float(np.linalg.norm(emb)))

    def encode_dialogue(self, summary: str, turns: int) -> np.ndarray:
        """
        将对话上下文编码为嵌入向量。

        Args:
            summary: 对话摘要文本
            turns: 对话轮次

        Returns:
            嵌入向量 (dial_emb_dim,)
        """
        emb = np.zeros(self.dial_emb_dim, dtype=np.float32)
        # 轮次编码
        emb[0] = min(1.0, turns / 50.0)
        # 摘要长度编码
        emb[1] = min(1.0, len(summary) / 1000.0)
        # 文本内容占位
        if summary:
            for i, c in enumerate(summary[:100]):
                emb[2 + (i % (self.dial_emb_dim - 2))] += ord(c) / 256.0

        return emb / max(1.0, float(np.linalg.norm(emb)))
