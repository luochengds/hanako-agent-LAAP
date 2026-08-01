"""
LlamaCppIntegrator — llama.cpp server completion API 封装

封装对 llama.cpp HTTP server 的 completion API 调用。
支持：logit_bias, temperature, grammar, json_schema, max_tokens 等核心参数。

llama.cpp completion API:
  POST /completion
  {
    "prompt": "...",
    "n_predict": 2048,
    "temperature": 0.7,
    "logit_bias": [[token_id, bias], ...],
    "grammar": "...",
    "json_schema": {...},
    "cache_prompt": true
  }
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

try:
    import requests
except ImportError:
    requests = None  # type: ignore

logger = logging.getLogger("laap.llm_tamer.llama_cpp")


class LlamaCppIntegrator:
    """llama.cpp server completion API 客户端。"""

    def __init__(self, base_url: str = "http://localhost:8082",
                 fallback_url: str = "http://localhost:11520",
                 timeout: int = 30):
        """
        Args:
            base_url: 主 llama.cpp server 地址
            fallback_url: 备用 server 地址
            timeout: 请求超时（秒）
        """
        self.base_url = base_url.rstrip("/")
        self.fallback_url = fallback_url.rstrip("/")
        self.timeout = timeout
        self._active_url = self.base_url

    def send_completion(
        self,
        prompt: str,
        logit_bias: Optional[Dict[int, float]] = None,
        temperature: float = 0.7,
        grammar: Optional[str] = None,
        json_schema: Optional[Dict[str, Any]] = None,
        max_tokens: int = 2048,
        use_fallback: bool = False,
    ) -> Dict[str, Any]:
        """
        发送 completion 请求到 llama.cpp server。

        Args:
            prompt: 输入提示
            logit_bias: {token_id: bias_value} 映射
            temperature: 采样温度 (0.0 ~ 2.0)
            grammar: GBNF 语法约束
            json_schema: JSON Schema 约束（llama.cpp 支持）
            max_tokens: 最大生成 token 数
            use_fallback: 是否使用备用 server

        Returns:
            llama.cpp API 响应字典（包含 content, tokens_predicted, generation_settings 等）
        """
        if requests is None:
            raise ImportError("'requests' library is required. Install with: pip install requests")

        url = self.fallback_url if use_fallback else self._active_url
        endpoint = f"{url}/completion"

        # 构建请求体
        payload: Dict[str, Any] = {
            "prompt": prompt,
            "n_predict": max_tokens,
            "temperature": temperature,
            "cache_prompt": True,
        }

        # logit_bias: llama.cpp 接受 [[token_id, bias], ...] 数组格式
        if logit_bias:
            logit_bias_list = [
                [int(tid), float(bias)] for tid, bias in logit_bias.items()
                if abs(bias) > 0.5  # 过滤掉过小的偏置值
            ]
            if logit_bias_list:
                payload["logit_bias"] = logit_bias_list

        if grammar:
            payload["grammar"] = grammar

        if json_schema:
            payload["json_schema"] = json_schema

        try:
            logger.debug(f"Sending completion to {endpoint} "
                         f"(temperature={temperature}, "
                         f"logit_bias_tokens={len(logit_bias or {})})")
            resp = requests.post(
                endpoint,
                headers={"Content-Type": "application/json"},
                json=payload,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.ConnectionError as e:
            logger.error(f"Connection failed to {endpoint}: {e}")
            # 如果主 URL 失败且没有指定 use_fallback，自动 fallback
            if not use_fallback and self._active_url == self.base_url:
                logger.info(f"Falling back to {self.fallback_url}")
                self._active_url = self.fallback_url
                return self.send_completion(
                    prompt=prompt,
                    logit_bias=logit_bias,
                    temperature=temperature,
                    grammar=grammar,
                    json_schema=json_schema,
                    max_tokens=max_tokens,
                    use_fallback=True,
                )
            raise
        except requests.exceptions.Timeout as e:
            logger.error(f"Timeout from {endpoint}: {e}")
            raise
        except requests.exceptions.RequestException as e:
            logger.error(f"Request failed: {e}")
            raise

    def get_tokenizer_tokens(self, text: str) -> List[int]:
        """
        通过 llama.cpp 的 tokenize API 获取 token IDs。

        GET /tokenize?content=...
        返回 {"tokens": [id1, id2, ...]}
        """
        if requests is None:
            raise ImportError("'requests' library is required")

        endpoint = f"{self._active_url}/tokenize"
        try:
            resp = requests.post(
                endpoint,
                headers={"Content-Type": "application/json"},
                json={"content": text},
                timeout=self.timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("tokens", [])
        except Exception as e:
            logger.error(f"Tokenize failed: {e}")
            return []

    def detokenize(self, token_ids: List[int]) -> str:
        """
        通过 llama.cpp 的 detokenize API 将 token IDs 转换回文本。

        POST /detokenize
        返回 {"text": "..."}
        """
        if requests is None:
            raise ImportError("'requests' library is required")

        endpoint = f"{self._active_url}/detokenize"
        try:
            resp = requests.post(
                endpoint,
                headers={"Content-Type": "application/json"},
                json={"tokens": token_ids},
                timeout=self.timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("text", "")
        except Exception as e:
            logger.error(f"Detokenize failed: {e}")
            return ""

    def test_connection(self) -> bool:
        """测试与 llama.cpp server 的连接是否正常。"""
        if requests is None:
            return False
        try:
            resp = requests.get(f"{self._active_url}/health",
                                timeout=self.timeout)
            return resp.status_code == 200
        except Exception:
            # 尝试简单的 completion 测试
            try:
                result = self.send_completion(
                    prompt="test",
                    max_tokens=1,
                )
                return "content" in result
            except Exception:
                return False

    def reset_active_url(self) -> None:
        """将活动 URL 重置为主 URL。"""
        self._active_url = self.base_url
