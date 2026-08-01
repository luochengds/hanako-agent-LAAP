"""
OpenAIIntegrator — OpenAI 兼容 API 适配器（DeepSeek 降级策略）

DeepSeek API 不暴露 logit_bias 参数，所以降级为：
  - 温度控制（可用 ✅）
  - 前缀注入（通过 prompt 工程近似 bias 效果）
  - 输出后处理

API 端点: https://api.deepseek.com/v1/chat/completions
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

try:
    import requests
except ImportError:
    requests = None  # type: ignore

logger = logging.getLogger("laap.llm_tamer.openai_api")


class OpenAIIntegrator:
    """OpenAI 兼容 Chat API 客户端（用于 DeepSeek 降级适配）。"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = "https://api.deepseek.com/v1",
        default_model: str = "deepseek-chat",
        timeout: int = 60,
    ):
        """
        Args:
            api_key: API 密钥（默认从 DEEPSEEK_API_KEY 环境变量读取）
            base_url: API 基础 URL
            default_model: 默认模型名称
            timeout: 请求超时（秒）
        """
        self.api_key = api_key or os.environ.get("DEEPSEEK_API_KEY", "")
        self.base_url = base_url.rstrip("/")
        self.default_model = default_model
        self.timeout = timeout

    def send_chat_completion(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        model: Optional[str] = None,
        response_format: Optional[Dict[str, str]] = None,
        max_tokens: int = 2048,
        max_retries: int = 3,
        validate_fn: Optional[callable] = None,
    ) -> Dict[str, Any]:
        """
        发送 chat completion 请求（含重试 + 后处理验证）。

        Args:
            messages: OpenAI 格式消息列表
            temperature: 采样温度
            model: 模型名称（默认使用 default_model）
            response_format: 响应格式，如 {"type": "json_object"}
            max_tokens: 最大生成 token 数
            max_retries: 失败时最大重试次数
            validate_fn: 可选的输出验证函数，接收 content(str) → bool

        Returns:
            OpenAI API 响应字典

        Raises:
            RuntimeError: 所有重试均失败时抛出
        """
        if requests is None:
            raise ImportError("'requests' library is required")

        endpoint = f"{self.base_url}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

        base_payload: Dict[str, Any] = {
            "model": model or self.default_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        if response_format:
            base_payload["response_format"] = response_format

        last_error = None
        for attempt in range(max_retries):
            try:
                payload = dict(base_payload)
                # 退避重试时略微调高 temperature 增加多样性
                if attempt > 0:
                    payload["temperature"] = min(temperature + attempt * 0.15, 1.5)
                    logger.info(f"DeepSeek retry attempt {attempt + 1}/{max_retries}, "
                                f"temperature={payload['temperature']:.2f}")

                resp = requests.post(
                    endpoint,
                    headers=headers,
                    json=payload,
                    timeout=self.timeout,
                )
                resp.raise_for_status()
                result = resp.json()

                # ── 后处理验证 ──
                content = (result.get("choices", [{}])[0]
                           .get("message", {}).get("content", ""))

                if not content or not content.strip():
                    last_error = "Empty response content"
                    logger.warning(f"Attempt {attempt + 1}: {last_error}")
                    continue

                if validate_fn and not validate_fn(content):
                    last_error = f"Validation failed for response: {content[:100]}..."
                    logger.warning(f"Attempt {attempt + 1}: {last_error}")
                    continue

                return result

            except requests.exceptions.RequestException as e:
                last_error = str(e)
                logger.warning(f"DeepSeek attempt {attempt + 1}/{max_retries} failed: {e}")
                if hasattr(e, "response") and e.response is not None:
                    logger.warning(f"Response body: {e.response.text}")
                if attempt < max_retries - 1:
                    import time
                    time.sleep((attempt + 1) * 2)  # 退避 2s, 4s, 6s

        raise RuntimeError(
            f"DeepSeek API failed after {max_retries} retries. Last error: {last_error}"
        )

    def apply_cognitive_prefix(self, messages: List[Dict[str, str]],
                               cognitive_state_text: str) -> List[Dict[str, str]]:
        """
        通过前缀注入将认知状态嵌入系统消息。
        这是 DeepSeek 降级策略的核心：用文本替代 logit_bias。

        Args:
            messages: 原始消息列表
            cognitive_state_text: 认知状态文本（如 CognitiveBus 的注入块）

        Returns:
            增强后的消息列表
        """
        if not messages:
            return messages

        # 找到系统消息，追加认知状态
        enhanced = list(messages)
        system_idx = None
        for i, msg in enumerate(enhanced):
            if msg.get("role") == "system":
                system_idx = i
                break

        cognitive_block = f"\n\n[Cognitive State]\n{cognitive_state_text}"

        if system_idx is not None:
            original = enhanced[system_idx]["content"]
            enhanced[system_idx] = {
                "role": "system",
                "content": original + cognitive_block,
            }
        else:
            # 没有系统消息时插入
            enhanced.insert(0, {
                "role": "system",
                "content": cognitive_block.strip(),
            })

        return enhanced

    def build_cognitive_prompt_prefix(
        self,
        emotion_valence: str,
        attention_focus: str,
        certainty: float,
        competence: float,
        template: str = "",
    ) -> str:
        """
        从认知状态构建提示前缀（降级替换 logit_bias）。

        Args:
            emotion_valence: 情感效价字符串
            attention_focus: 注意力焦点字符串
            certainty: 确定性程度 (0-1)
            competence: 胜任度 (0-1)

        Returns:
            格式化后的认知状态文本
        """
        if template:
            return template.format(
                emotion=emotion_valence,
                attention=attention_focus,
                certainty=certainty,
                competence=competence,
            )
        return (
            f"[Cognitive Context]\n"
            f"Current emotion: {emotion_valence}\n"
            f"Attention: {attention_focus}\n"
            f"Certainty: {certainty:.2f}\n"
            f"Competence: {competence:.2f}"
        )
