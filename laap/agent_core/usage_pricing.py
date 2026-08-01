"""UsagePricing — 使用定价"""
from dataclasses import dataclass
from typing import Dict, Optional

@dataclass
class PricingEntry:
    model: str = ""; input_per_1k: float = 0.0; output_per_1k: float = 0.0

PRICING = {
    "deepseek-v4-flash": PricingEntry("deepseek-v4-flash", 0.0001, 0.0004),
    "gpt-4": PricingEntry("gpt-4", 0.003, 0.006),
    "gpt-4-turbo": PricingEntry("gpt-4-turbo", 0.001, 0.003),
    "claude-3-sonnet": PricingEntry("claude-3-sonnet", 0.003, 0.015),
}

class UsagePricing:
    @classmethod
    def calculate(cls, model: str, input_tokens: int, output_tokens: int) -> float:
        p = PRICING.get(model, PricingEntry("", 0.001, 0.002))
        return (input_tokens * p.input_per_1k + output_tokens * p.output_per_1k) / 1000
    @classmethod
    def get_pricing(cls, model: str) -> Optional[PricingEntry]:
        return PRICING.get(model)
