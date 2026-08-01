"""PromptOptimizer — 提示优化(最小化token消耗)"""
from __future__ import annotations
import re, json, logging
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("agent_core.prompt_optimizer")

class PromptOptimizer:
    """
    提示优化器 — 在保持效果的前提下最小化token消耗
    
    技术:
    1. 去除冗余词汇
    2. 缩短指令
    3. 合并重复
    4. 使用紧凑格式
    5. 移除不必要的格式要求
    """
    
    REDUNDANT = [
        r"(?i)please", r"(?i)could you", r"(?i)would you",
        r"(?i)i would like you to", r"(?i)can you",
        r"(?i)thank you", r"(?i)thanks",
        r"\s{2,}",  # 多余空格
    ]
    
    def optimize(self, prompt: str, max_tokens: int = None) -> str:
        """优化提示文本"""
        original = prompt
        if not prompt:
            return prompt
        
        # 1. 去冗余
        for pattern in self.REDUNDANT:
            prompt = re.sub(pattern, "", prompt)
        
        # 2. 压缩多余空白
        prompt = re.sub(r"\n{3,}", "\n\n", prompt)
        prompt = re.sub(r" {2,}", " ", prompt)
        prompt = prompt.strip()
        
        # 3. 缩短过长段落
        if max_tokens and len(prompt) > max_tokens * 2:
            lines = prompt.split("\n")
            shortened = []
            for line in lines:
                if len(line) > 200:
                    line = line[:150] + "..."
                shortened.append(line)
            prompt = "\n".join(shortened)
        
        saved = len(original) - len(prompt)
        if saved > 0:
            logger.info(f"Optimized prompt: {saved} chars saved ({saved/len(original)*100:.0f}%)")
        
        return prompt
    
    def estimate_savings(self, original: str, optimized: str) -> dict:
        orig_tokens = len(original)//2
        opt_tokens = len(optimized)//2
        return {"original_tokens": orig_tokens, "optimized_tokens": opt_tokens,
                "saved_tokens": orig_tokens - opt_tokens,
                "savings_pct": f"{(1-opt_tokens/max(orig_tokens,1))*100:.0f}%"}
    
    def get_stats(self) -> dict:
        return {"status": "ready"}
