"""
Chain-of-Thought constraint — enforces a structured reasoning format.

Forces the model to follow a 思考→分析→结论 (Think→Analyze→Conclude)
structure in its output.
"""

from typing import Dict, Optional


# BNF Grammar for structured reasoning: 思考 → 分析 → 结论
# Uses Chinese markers with standard punctuation

REASONING_GRAMMAR_BASIC = """root ::= think-section analysis-section conclusion-section
think-section ::= "思考：" [^。]+ "。"
analysis-section ::= "分析：" [^。]+ "。"
conclusion-section ::= "结论：" [^。]+ "。"
"""

# Extended version with confidence and alternatives
REASONING_GRAMMAR_EXTENDED = """root ::= think-section analysis-section conclusion-section confidence-section
think-section ::= "思考：" [^。]+ "。"
analysis-section ::= "分析：" [^。]+ "。"
conclusion-section ::= "结论：" [^。]+ "。"
confidence-section ::= "置信度：" [0-9]+ "." [0-9]+
"""

# Multi-step reasoning (think → step1 → step2 → ... → conclusion)
REASONING_GRAMMAR_MULTI = """root ::= think-section step+ conclusion-section
think-section ::= "思考：" [^。]+ "。"
step ::= "步骤" [0-9]+ "：" [^。]+ "。"
conclusion-section ::= "结论：" [^。]+ "。"
"""

# English version
REASONING_GRAMMAR_ENGLISH = """root ::= think-section analysis-section conclusion-section
think-section ::= "Thought:" [^.]+ "."
analysis-section ::= "Analysis:" [^.]+ "."
conclusion-section ::= "Conclusion:" [^.]+ "."
"""


class ChainOfThoughtConstraintBuilder:
    """Builds grammar constraints for structured reasoning chains."""

    PRESETS = {
        "basic": REASONING_GRAMMAR_BASIC,
        "extended": REASONING_GRAMMAR_EXTENDED,
        "multi_step": REASONING_GRAMMAR_MULTI,
        "english": REASONING_GRAMMAR_ENGLISH,
    }

    def __init__(self, mode: str = "basic"):
        if mode not in self.PRESETS:
            raise ValueError(
                f"Unknown reasoning mode '{mode}'. "
                f"Available: {list(self.PRESETS.keys())}"
            )
        self.mode = mode
        self.grammar = self.PRESETS[mode]

    def build(self) -> Dict[str, str]:
        """Build the constraint parameter dict for llama.cpp."""
        return {"grammar": self.grammar}

    def to_string(self) -> str:
        return f"ChainOfThoughtConstraint(mode='{self.mode}')\n{self.grammar}"
