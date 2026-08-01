# -*- coding: utf-8 -*-
"""国产模型供应商预设配置.

所有预设均使用 OpenAI Chat 兼容格式（openai_chat），因为国产模型
基本都提供了 OpenAI 兼容的 /v1/chat/completions 端点。

用户只需填入 API Key 即可使用。Base URL 和默认模型已预置。
"""

from __future__ import annotations

from typing import Any, Dict, List

# 三种协议格式常量（与扩展内 custom-provider-models.js 对齐）
ANTHROPIC_FORMAT = "anthropic"
OPENAI_CHAT_FORMAT = "openai_chat"
OPENAI_RESPONSES_FORMAT = "openai_responses"

# 国产模型供应商预设
# 每个预设包含：name, format, baseUrl, defaultModel, fastModel,
#               contextWindow, maxOutputTokens, reasoningEffort, vendor
PROVIDER_PRESETS: List[Dict[str, Any]] = [
    # ── DeepSeek ──────────────────────────────────────────────
    {
        "name": "DeepSeek",
        "format": OPENAI_CHAT_FORMAT,
        "baseUrl": "https://api.deepseek.com/v1",
        "defaultModel": "deepseek-chat",
        "fastModel": "deepseek-chat",
        "contextWindow": 64000,
        "maxOutputTokens": 8192,
        "reasoningEffort": "medium",
        "vendor": "deepseek",
        "models": ["deepseek-chat", "deepseek-reasoner", "deepseek-coder"],
    },
    # ── 通义千问 (Qwen / 阿里云百炼) ──────────────────────────
    {
        "name": "通义千问 (Qwen)",
        "format": OPENAI_CHAT_FORMAT,
        "baseUrl": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "defaultModel": "qwen-plus",
        "fastModel": "qwen-turbo",
        "contextWindow": 128000,
        "maxOutputTokens": 8192,
        "reasoningEffort": "medium",
        "vendor": "alibaba",
        "models": [
            "qwen-turbo", "qwen-plus", "qwen-max",
            "qwen-long", "qwen2.5-72b-instruct", "qwen2.5-32b-instruct",
            "qwen2.5-14b-instruct", "qwen2.5-7b-instruct", "qwen2.5-coder-32b-instruct",
            "qwen-vl-max", "qwen-vl-plus",
        ],
    },
    # ── 智谱 AI (GLM) ────────────────────────────────────────
    {
        "name": "智谱 AI (GLM)",
        "format": OPENAI_CHAT_FORMAT,
        "baseUrl": "https://open.bigmodel.cn/api/paas/v4",
        "defaultModel": "glm-4-plus",
        "fastModel": "glm-4-flash",
        "contextWindow": 128000,
        "maxOutputTokens": 4096,
        "reasoningEffort": "medium",
        "vendor": "zhipu",
        "models": [
            "glm-4-plus", "glm-4-0520", "glm-4-air", "glm-4-flash",
            "glm-4v", "glm-4-long", "codegeex-4",
        ],
    },
    # ── 月之暗面 (Kimi / Moonshot) ────────────────────────────
    {
        "name": "Kimi (Moonshot)",
        "format": OPENAI_CHAT_FORMAT,
        "baseUrl": "https://api.moonshot.cn/v1",
        "defaultModel": "moonshot-v1-32k",
        "fastModel": "moonshot-v1-8k",
        "contextWindow": 128000,
        "maxOutputTokens": 8192,
        "reasoningEffort": "medium",
        "vendor": "moonshot",
        "models": [
            "moonshot-v1-8k", "moonshot-v1-32k", "moonshot-v1-128k",
            "kimi-latest",
        ],
    },
    # ── 百川 (Baichuan) ──────────────────────────────────────
    {
        "name": "百川 (Baichuan)",
        "format": OPENAI_CHAT_FORMAT,
        "baseUrl": "https://api.baichuan-ai.com/v1",
        "defaultModel": "Baichuan4-Turbo",
        "fastModel": "Baichuan3-Turbo",
        "contextWindow": 32000,
        "maxOutputTokens": 4096,
        "reasoningEffort": "medium",
        "vendor": "baichuan",
        "models": [
            "Baichuan4-Turbo", "Baichuan4-Air", "Baichuan3-Turbo",
            "Baichuan3-Turbo-128k", "Baichuan-13B-Chat",
        ],
    },
    # ── 零一万物 (01.AI / Yi) ────────────────────────────────
    {
        "name": "零一万物 (Yi)",
        "format": OPENAI_CHAT_FORMAT,
        "baseUrl": "https://api.lingyiwanwu.com/v1",
        "defaultModel": "yi-large",
        "fastModel": "yi-medium",
        "contextWindow": 32000,
        "maxOutputTokens": 4096,
        "reasoningEffort": "medium",
        "vendor": "lingyiwanwu",
        "models": [
            "yi-large", "yi-medium", "yi-small", "yi-large-turbo",
            "yi-large-fc", "yi-vision",
        ],
    },
    # ── MiniMax ──────────────────────────────────────────────
    {
        "name": "MiniMax",
        "format": OPENAI_CHAT_FORMAT,
        "baseUrl": "https://api.minimax.chat/v1",
        "defaultModel": "abab6.5s-chat",
        "fastModel": "abab6.5s-chat",
        "contextWindow": 245760,
        "maxOutputTokens": 4096,
        "reasoningEffort": "medium",
        "vendor": "minimax",
        "models": [
            "abab6.5s-chat", "abab6.5-chat", "abab6-chat",
            "minimax-text-01",
        ],
    },
    # ── 百度文心一言 (ERNIE / 千帆) ───────────────────────────
    {
        "name": "文心一言 (ERNIE)",
        "format": OPENAI_CHAT_FORMAT,
        "baseUrl": "https://qianfan.baidubce.com/v2",
        "defaultModel": "ernie-4.0-8k-latest",
        "fastModel": "ernie-speed-8k",
        "contextWindow": 128000,
        "maxOutputTokens": 4096,
        "reasoningEffort": "medium",
        "vendor": "baidu",
        "models": [
            "ernie-4.0-8k-latest", "ernie-4.0-turbo-8k", "ernie-3.5-128k",
            "ernie-speed-128k", "ernie-speed-8k", "ernie-lite-8k",
            "ernie-character-8k", "ernie-novel-8k",
        ],
    },
    # ── 讯飞星火 (Spark / 一站式接口) ─────────────────────────
    {
        "name": "讯飞星火 (Spark)",
        "format": OPENAI_CHAT_FORMAT,
        "baseUrl": "https://spark-api-open.xf-yun.com/v1",
        "defaultModel": "4.0Ultra",
        "fastModel": "lite",
        "contextWindow": 32000,
        "maxOutputTokens": 4096,
        "reasoningEffort": "medium",
        "vendor": "iflytek",
        "models": [
            "4.0Ultra", "generalv3.5", "generalv3", "pro-128k",
            "lite", "spark-v4",
        ],
    },
    # ── 商汤日日新 (SenseNova) ───────────────────────────────
    {
        "name": "商汤日日新 (SenseNova)",
        "format": OPENAI_CHAT_FORMAT,
        "baseUrl": "https://api.sensenova.cn/compatible-mode/v1",
        "defaultModel": "SenseChat-5",
        "fastModel": "SenseChat-5-Lite",
        "contextWindow": 32000,
        "maxOutputTokens": 4096,
        "reasoningEffort": "medium",
        "vendor": "sensetime",
        "models": [
            "SenseChat-5", "SenseChat-5-Lite", "SenseChat-Turbo",
            "SenseChat-5-Code",
        ],
    },
    # ── 阶跃星辰 (StepFun) ───────────────────────────────────
    {
        "name": "阶跃星辰 (StepFun)",
        "format": OPENAI_CHAT_FORMAT,
        "baseUrl": "https://api.stepfun.com/v1",
        "defaultModel": "step-2-16k",
        "fastModel": "step-1-8k",
        "contextWindow": 32000,
        "maxOutputTokens": 4096,
        "reasoningEffort": "medium",
        "vendor": "stepfun",
        "models": [
            "step-2-16k", "step-1-8k", "step-1-32k", "step-1-128k",
            "step-1v-8k", "step-1v-32k",
        ],
    },
    # ── 本地 Ollama (可选，用于本地模型) ──────────────────────
    {
        "name": "Ollama (本地)",
        "format": OPENAI_CHAT_FORMAT,
        "baseUrl": "http://localhost:11434/v1",
        "defaultModel": "llama3.1",
        "fastModel": "qwen2.5:7b",
        "contextWindow": 32000,
        "maxOutputTokens": 4096,
        "reasoningEffort": "medium",
        "vendor": "ollama",
        "models": [
            "llama3.1", "llama3.2", "qwen2.5", "qwen2.5-coder",
            "deepseek-r1", "phi3", "gemma2",
        ],
    },
    # ── 硅基流动 (SiliconFlow / 一站式聚合) ───────────────────
    {
        "name": "硅基流动 (SiliconFlow)",
        "format": OPENAI_CHAT_FORMAT,
        "baseUrl": "https://api.siliconflow.cn/v1",
        "defaultModel": "deepseek-ai/DeepSeek-V3",
        "fastModel": "Qwen/Qwen2.5-7B-Instruct",
        "contextWindow": 64000,
        "maxOutputTokens": 4096,
        "reasoningEffort": "medium",
        "vendor": "siliconflow",
        "models": [
            "deepseek-ai/DeepSeek-V3", "deepseek-ai/DeepSeek-R1",
            "Qwen/Qwen2.5-72B-Instruct", "Qwen/Qwen2.5-7B-Instruct",
            "Qwen/Qwen2.5-Coder-32B-Instruct",
            "meta-llama/Llama-3.3-70B-Instruct",
            "Pro/Qwen/Qwen2.5-14B-Instruct",
        ],
    },
    # ── OpenRouter (聚合平台，含国产模型) ─────────────────────
    {
        "name": "OpenRouter (聚合)",
        "format": OPENAI_CHAT_FORMAT,
        "baseUrl": "https://openrouter.ai/api/v1",
        "defaultModel": "deepseek/deepseek-chat",
        "fastModel": "qwen/qwen-2.5-7b-instruct",
        "contextWindow": 64000,
        "maxOutputTokens": 4096,
        "reasoningEffort": "medium",
        "vendor": "openrouter",
        "models": [
            "deepseek/deepseek-chat", "deepseek/deepseek-r1",
            "qwen/qwen-2.5-72b-instruct", "qwen/qwen-2.5-7b-instruct",
            "01-ai/yi-large", "minimax/minimax-01",
            "anthropic/claude-3.5-sonnet", "openai/gpt-4o",
        ],
    },
]


def list_presets() -> List[str]:
    """返回所有预设供应商名称列表."""
    return [p["name"] for p in PROVIDER_PRESETS]


def get_preset(name: str) -> Dict[str, Any] | None:
    """按名称获取预设配置（支持模糊匹配）."""
    name_lower = name.lower().strip()
    for p in PROVIDER_PRESETS:
        if p["name"].lower() == name_lower or p["vendor"].lower() == name_lower:
            return p
    # 模糊匹配
    for p in PROVIDER_PRESETS:
        if name_lower in p["name"].lower() or name_lower in p["vendor"].lower():
            return p
    return None


def build_profile(preset_name: str, api_key: str) -> Dict[str, Any]:
    """根据预设名和 API Key 构建一个可写入扩展存储的 profile.

    返回的 dict 符合 claw-in-chrome custom-provider-models.js 的
    normalizeProfile() 输入格式。
    """
    preset = get_preset(preset_name)
    if not preset:
        raise ValueError(
            f"未找到预设 '{preset_name}'。可用预设: {list_presets()}"
        )
    if not api_key.strip():
        raise ValueError("API Key 不能为空")

    import time, secrets
    profile_id = f"provider_{int(time.time()):x}_{secrets.token_hex(3)}"

    return {
        "id": profile_id,
        "name": preset["name"],
        "format": preset["format"],
        "baseUrl": preset["baseUrl"],
        "apiKey": api_key.strip(),
        "defaultModel": preset["defaultModel"],
        "fastModel": preset.get("fastModel", preset["defaultModel"]),
        "reasoningEffort": preset.get("reasoningEffort", "medium"),
        "maxOutputTokens": preset.get("maxOutputTokens", 8192),
        "contextWindow": preset.get("contextWindow", 128000),
        "fetchedModels": [
            {"value": m, "label": m, "manual": True}
            for m in preset.get("models", [])
        ],
    }


def list_all_models() -> Dict[str, List[str]]:
    """返回 {供应商名: [模型列表]} 的字典."""
    return {p["name"]: p.get("models", []) for p in PROVIDER_PRESETS}
