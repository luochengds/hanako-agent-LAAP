"""
LLM Tamer — 认知驱动的 LLM 生成控制主入口
=========================================

路径一：logit bias 控制 + 动态温度 + token 禁止

从 CognitiveBus 认知状态直接计算 logit_bias 字典，
传递给 llama.cpp 的 completion API，实现对生成过程的实时控制。

典型用法：
    from llm_tamer import LLMTamer

    tamer = LLMTamer()
    state = cognitive_bus.snapshot()

    # 1) 计算偏置
    bias = tamer.compute_bias(state, context="user_query")
    temp = tamer.compute_temperature(state)
    banned = tamer.banned_tokens(state)

    # 2) 发送到本地模型
    result = tamer.apply_to_local(prompt="你好", state=state)

    # 3) 或者降级到 DeepSeek
    result = tamer.apply_to_deepseek(
        prompt="你好",
        state=state,
        messages=[{"role": "user", "content": "你好"}]
    )
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore

from .bias_computers import (
    AttentionBiasComputer,
    EmotionBiasComputer,
    NeedsBiasComputer,
    MetaBiasComputer,
    CognitiveBiasComputer,
)
from .integrators import LlamaCppIntegrator, OpenAIIntegrator

# 尝试导入 CognitiveBus 类型
# 注意：实际类名是 CognitiveStateSnapshot（laap/agi/cognitive_bus.py:169），
#       而非 CognitiveBusState。早期文档误用 CognitiveBusState，已修正。
try:
    from laap.agi.cognitive_bus import (
        CognitiveBus,
        CognitiveStateSnapshot,
    )
except ImportError:
    CognitiveBus = None  # type: ignore
    CognitiveStateSnapshot = None  # type: ignore

logger = logging.getLogger("laap.llm_tamer.tamer")


class LLMTamer:
    """
    LLM Tamer 主入口。

    从 CognitiveBus 认知状态计算 logit_bias、动态温度、
    token 禁止列表，并发送到不同的 LLM provider。

    核心流程：
        状态 → 四个偏置计算机 → 合并 bias → 计算温度 → 发送请求
    """

    def __init__(self, config_path: Optional[str] = None):
        """
        Args:
            config_path: YAML 配置文件路径。
                         默认查找 llm_tamer/config.yaml
        """
        self.config: Dict[str, Any] = {}
        self._load_config(config_path)

        # 从配置中提取参数
        self._bias_strengths = self.config.get("bias_strength", {
            "attention": 1.0,
            "emotion": 0.7,
            "needs": 0.5,
            "meta": 0.8,
            "cognitive": 0.5,
        })
        self._temp_config = self.config.get("temperature", {})

        # 加载模型感知的 token 映射
        # config.yaml 中 token_mappings 有 holo / qwen 两个子字典
        all_mappings = self.config.get("token_mappings", {})
        if isinstance(all_mappings, dict) and "holo" in all_mappings:
            # 新格式：按模型分拆
            self._active_model = "holo"  # 默认 Holo，可通过 switch_token_mapping 切换
            self._token_mappings = all_mappings.get(self._active_model, {})
            self._all_token_mappings = all_mappings
        else:
            # 兼容旧格式：扁平映射
            self._active_model = "legacy"
            self._token_mappings = all_mappings
            self._all_token_mappings = {}

        # 初始化偏置计算机
        self._attention_computer = AttentionBiasComputer(
            bias_strength=self._bias_strengths.get("attention", 1.0)
        )
        self._emotion_computer = EmotionBiasComputer(
            bias_strength=self._bias_strengths.get("emotion", 0.7)
        )
        self._needs_computer = NeedsBiasComputer(
            bias_strength=self._bias_strengths.get("needs", 0.5)
        )
        self._meta_computer = MetaBiasComputer(
            bias_strength=self._bias_strengths.get("meta", 0.8)
        )
        self._cognitive_computer = CognitiveBiasComputer(
            bias_strength=self._bias_strengths.get("cognitive", 0.5)
        )

        # 加载 token 映射到各计算机
        for comp in [self._attention_computer, self._emotion_computer,
                     self._needs_computer, self._meta_computer,
                     self._cognitive_computer]:
            comp.load_token_groups(self._token_mappings)

        # 初始化集成器
        llama_config = self.config.get("llama_cpp", {})
        self._llama = LlamaCppIntegrator(
            base_url=llama_config.get("default_url", "http://localhost:8082"),
            fallback_url=llama_config.get("fallback_url", "http://localhost:11520"),
        )

        deepseek_config = self.config.get("deepseek", {})
        self._deepseek = OpenAIIntegrator(
            base_url=deepseek_config.get("base_url", "https://api.deepseek.com/v1"),
        )

        logger.info(f"LLMTamer initialized (bias strengths: {self._bias_strengths})")

    # ── Public API ──────────────────────────────────────────

    def compute_bias(self,
                     state: "CognitiveStateSnapshot",
                     context: str = "",
                     target_provider: str = "local") -> Dict[int, float]:
        """
        从认知状态计算完整的 logit_bias 字典。

        合并四个偏置计算机的输出：
            1. 注意力引导偏置
            2. 情感调节偏置
            3. 需求驱动偏置
            4. 元认知偏置

        Args:
            state: CognitiveBus 状态快照
            context: 当前上下文（预留，可用于基于上下文的偏置调整）
            target_provider: "local" 或 "deepseek"（deepseek 不支持 bias）

        Returns:
            {token_id: bias_value} 字典
        """
        if target_provider == "deepseek":
            # DeepSeek 不支持 logit_bias
            return {}

        # 收集所有偏置
        all_bias: Dict[int, float] = {}

        computers = [
            ("attention", [self._attention_computer]),
            ("emotion", [self._emotion_computer]),
            ("needs", [self._needs_computer]),
            ("meta", [self._meta_computer]),
            ("cognitive", [self._cognitive_computer]),
        ]

        for name, comps in computers:
            for comp in comps:
                partial = comp.compute(state)
                self._merge_bias(all_bias, partial)

        # 可选：基于上下文的调整（预留）

        # 去重合并：同一个 token 的多个偏置取和
        # （_merge_bias 已做累加）

        # 限制偏置范围 [-100, 100]
        clamped = {
            tid: max(-100.0, min(100.0, round(bias, 1)))
            for tid, bias in all_bias.items()
        }

        return clamped

    def compute_temperature(self, state: "CognitiveStateSnapshot") -> float:
        """
        根据认知状态动态计算 temperature。

        策略：
          - 注意力集中（intensity >= threshold）→ 低温 (0.3-0.5)
          - 探索模式（高 curiosity / 低 certainty）→ 高温 (0.8-1.2)
          - 默认温度

        Args:
            state: 认知状态快照

        Returns:
            建议的 temperature 值 (0.2 ~ 1.5)
        """
        intensity = state.attention.intensity
        curiosity = state.curiosity
        certainty = state.needs.certainty

        min_temp = self._temp_config.get("min", 0.2)
        max_temp = self._temp_config.get("max", 1.5)
        focused_threshold = self._temp_config.get("focused_threshold", 0.7)
        focused_temp = self._temp_config.get("focused_temp", 0.4)
        normal_temp = self._temp_config.get("normal_temp", 0.7)
        exploratory_temp = self._temp_config.get("exploratory_temp", 1.0)

        # 1. 注意力高度集中 → 低温
        if intensity >= focused_threshold:
            # 强度越高温度越低
            focus_ratio = (intensity - focused_threshold) / (1.0 - focused_threshold)
            temp = focused_temp + (normal_temp - focused_temp) * (1.0 - focus_ratio)
        # 2. 探索模式（高 curiosity + 低 certainty）
        elif curiosity > 0.6 and certainty < 0.4:
            # 探索程度越高温度越高
            explore_strength = (curiosity - 0.6) / 0.4 * (0.4 - certainty) / 0.4
            temp = normal_temp + (exploratory_temp - normal_temp) * explore_strength
        # 3. 注意力涣散 → 略高温（鼓励随机探索以重新聚焦）
        elif intensity < 0.3:
            scatter = (0.3 - intensity) / 0.3
            temp = normal_temp + scatter * 0.3
            temp = min(temp, exploratory_temp)
        else:
            temp = normal_temp

        # 用 emotional arousal 微调
        arousal = state.emotion.arousal
        temp += (arousal - 0.5) * 0.15  # ±0.075 范围微调

        return round(max(min_temp, min(max_temp, temp)), 2)

    def banned_tokens(self, state: "CognitiveStateSnapshot") -> List[int]:
        """
        根据当前状态计算应禁止的 token 列表。

        策略：
          - 注意力在 USER 且 certainty 极低 → 禁止敷衍回复 token
          - NEGATIVE_HIGH 情感 → 禁止极端负面 token
          - 高 self-presence → 禁止过度谦虚 token

        Args:
            state: 认知状态快照

        Returns:
            要绝对禁止的 token_id 列表（bias = -100）
        """
        banned: List[int] = []

        # 1. 注意力在 USER 且 certainty < 0.2 → 禁止敷衍回复
        if (state.attention.focus.value == "user"
                and state.needs.certainty < 0.2):
            # 这里需要从 token_mappings 获取"敷衍" token
            # 暂时返回空，实际使用需从模型 tokenizer 获取
            pass

        # 2. NEGATIVE_HIGH → 禁止极端负面词汇（bias = -100 级别）
        if state.emotion.valence.value == "negative_high":
            negative_tokens = self._token_mappings.get("negative_tokens", {})
            for tid in negative_tokens:
                banned.append(tid)

        # 3. 注意力高度集中且非 SELF → 禁止自省 token
        if (state.attention.intensity > 0.85
                and state.attention.focus.value != "self"):
            intro_tokens = self._token_mappings.get("introspection_tokens", {})
            for tid in intro_tokens:
                if tid not in banned:
                    banned.append(tid)

        return list(set(banned))

    def apply_to_local(self,
                       prompt: str,
                       state: "CognitiveStateSnapshot",
                       llama_url: Optional[str] = None,
                       max_tokens: int = 2048,
                       grammar: Optional[str] = None,
                       json_schema: Optional[Dict[str, Any]] = None,
                       ) -> Dict[str, Any]:
        """
        整合 bias + temperature 发送到 llama.cpp completion API。

        这是主要使用路径：将认知状态完全编码到 LLM 请求参数中。

        Args:
            prompt: 发送给模型的提示文本
            state: 当前认知状态
            llama_url: 可选的覆盖 URL
            max_tokens: 最大生成 token 数
            grammar: GBNF 语法约束
            json_schema: JSON Schema 约束

        Returns:
            llama.cpp API 响应（包含 content, tokens_predicted 等）
        """
        # 1. 计算控制参数
        bias = self.compute_bias(state, context=prompt, target_provider="local")
        temperature = self.compute_temperature(state)
        banned = self.banned_tokens(state)

        # 被禁止的 token 设置 -100 偏置
        for tid in banned:
            bias[tid] = -100.0

        logger.info(
            f"apply_to_local: bias_tokens={len(bias)}, "
            f"temperature={temperature}, "
            f"banned_tokens={len(banned)}"
        )

        # 2. 使用 llama.cpp 集成器发送
        if llama_url:
            # 临时覆盖 URL
            old_url = self._llama._active_url
            self._llama._active_url = llama_url.rstrip("/")
            try:
                return self._llama.send_completion(
                    prompt=prompt,
                    logit_bias=bias if bias else None,
                    temperature=temperature,
                    grammar=grammar,
                    json_schema=json_schema,
                    max_tokens=max_tokens,
                )
            finally:
                self._llama._active_url = old_url
        else:
            return self._llama.send_completion(
                prompt=prompt,
                logit_bias=bias if bias else None,
                temperature=temperature,
                grammar=grammar,
                json_schema=json_schema,
                max_tokens=max_tokens,
            )

    def apply_to_deepseek(self,
                          prompt: str,
                          state: "CognitiveStateSnapshot",
                          messages: Optional[List[Dict[str, str]]] = None,
                          max_tokens: int = 2048,
                          ) -> Dict[str, Any]:
        """
        降级适配 DeepSeek API：只传 temperature，bias 通过 prompt 工程近似。

        DeepSeek 不支持 logit_bias，因此使用：
          - 温度控制（可用）
          - 前缀注入（通过系统消息嵌入认知状态）
          - 输出后处理

        Args:
            prompt: 用户消息
            state: 当前认知状态
            messages: 可选的完整消息历史（用于前缀注入）
            max_tokens: 最大生成 token 数

        Returns:
            OpenAI 格式 API 响应
        """
        temperature = self.compute_temperature(state)

        # 构建消息列表
        if messages is None:
            messages = [{"role": "user", "content": prompt}]

        # 构建认知前缀
        prefix = self._deepseek.build_cognitive_prompt_prefix(
            emotion_valence=state.emotion.valence.value,
            attention_focus=state.attention.focus.value,
            certainty=state.needs.certainty,
            competence=state.needs.competence,
            template=self.config.get("deepseek", {}).get(
                "prompt_prefix_template", ""),
        )

        # 注入前缀到系统消息
        enhanced_messages = self._deepseek.apply_cognitive_prefix(
            messages, prefix)

        logger.info(
            f"apply_to_deepseek: temperature={temperature}, "
            f"cognitive_prefix_injected=True"
        )

        return self._deepseek.send_chat_completion(
            messages=enhanced_messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    # ── Internal ────────────────────────────────────────────

    def _load_config(self, config_path: Optional[str] = None) -> None:
        """加载配置文件。"""
        if config_path is None:
            # 默认查找与 tamer.py 同目录的 config.yaml
            base_dir = os.path.dirname(os.path.abspath(__file__))
            config_path = os.path.join(base_dir, "config.yaml")

        if os.path.exists(config_path):
            try:
                if yaml is None:
                    raise ImportError("PyYAML is required. Install with: pip install pyyaml")
                with open(config_path, "r", encoding="utf-8") as f:
                    self.config = yaml.safe_load(f) or {}
                logger.info(f"Loaded config from {config_path}")
            except Exception as e:
                logger.warning(f"Failed to load config from {config_path}: {e}")
                self.config = {}
        else:
            logger.warning(f"Config not found at {config_path}, using defaults")
            self.config = {}

    def _merge_bias(self, target: Dict[int, float],
                    source: Dict[int, float]) -> None:
        """合并偏置字典（累加值）。"""
        for tid, bias in source.items():
            target[tid] = target.get(tid, 0.0) + bias

    def switch_token_mapping(self, model_name: str) -> bool:
        """
        根据模型名称切换 token 映射。

        支持: "holo", "qwen", "deepseek"（无本地 token 映射时清空）
        其他未知模型名回到 "holo"。

        Args:
            model_name: 目标模型名称 ("holo", "qwen", "deepseek", ...)

        Returns:
            True 切换成功, False 无变化或失败
        """
        if not self._all_token_mappings:
            return False

        normalized = model_name.lower().replace("-", "_")
        if normalized == "deepseek" or normalized == "deepseek_v4_flash":
            self._active_model = "deepseek"
            self._token_mappings = {}
            logger.info("DeepSeek 模式：清空本地 token 映射")
            self._reload_computers()
            return True

        if normalized in self._all_token_mappings:
            self._active_model = normalized
            self._token_mappings = self._all_token_mappings[normalized]
            logger.info(f"切换 token 映射为: {normalized}")
            self._reload_computers()
            return True

        # 未知模型 → 回退 Holo
        if "holo" in self._all_token_mappings:
            logger.warning(f"未知模型 {model_name}，回退 Holo token 映射")
            self._active_model = "holo"
            self._token_mappings = self._all_token_mappings["holo"]
            self._reload_computers()
            return True

        return False

    def _reload_computers(self) -> None:
        """重新加载 token 映射到所有偏置计算机。"""
        for comp in [self._attention_computer, self._emotion_computer,
                     self._needs_computer, self._meta_computer,
                     self._cognitive_computer]:
            comp.load_token_groups(self._token_mappings)

    # ── Properties ──────────────────────────────────────────

    @property
    def llama(self) -> LlamaCppIntegrator:
        """获取 llama.cpp 集成器实例。"""
        return self._llama

    @property
    def deepseek(self) -> OpenAIIntegrator:
        """获取 DeepSeek 集成器实例。"""
        return self._deepseek

    @property
    def token_mappings(self) -> Dict[str, Dict[int, str]]:
        """获取当前活跃模型的 token 映射。"""
        return self._token_mappings

    @property
    def active_model(self) -> str:
        """获取当前活跃模型名称。"""
        return self._active_model
