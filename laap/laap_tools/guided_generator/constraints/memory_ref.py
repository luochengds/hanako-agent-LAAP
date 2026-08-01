"""
Memory reference constraint — enforces output format with memory reference markers.

Forces the model to generate statements that reference memory records
using the format: statement [keyword]
"""

from typing import Dict, Optional

# BNF Grammar: statement with optional memory reference
#
# NOTE: llama.cpp grammar parser does NOT support multi-byte Unicode ranges
# inside character classes ([\\u4e00-\\u9fff] fails). For CJK support, use
# a simpler approach: match any non-bracket/non-newline character, since
# llama.cpp's grammar is token-level and the model naturally produces CJK.
#
# Keyword chars: letters, digits, underscore, hyphen (no CJK range).
# For statements: match everything except the closing boundary chars.

# Grammar: statement with optional memory reference
# statement matches anything except 。\[ \ ] # \n
MEMORY_REF_GRAMMAR = (
    'root ::= statement memref \n'
    'statement ::= [^。\\[\\]#\\n]{1,80} \n'
    'memref ::= " [" keyword "]"\n'
    'keyword ::= [-a-zA-Z0-9_]+\n'
)

# Strict alias (same — memref is always required in this grammar)
MEMORY_REF_STRICT_GRAMMAR = MEMORY_REF_GRAMMAR

# Multi-statement: one or more statement+memref pairs
MEMORY_REF_MULTI_GRAMMAR = (
    'root ::= pair+\n'
    'pair ::= statement memref\n'
    'statement ::= [^。\\[\\]#\\n]{1,80}\n'
    'memref ::= " [" keyword "]"\n'
    'keyword ::= [-a-zA-Z0-9_]+\n'
)

# JSON format with memory references
MEMORY_REF_JSON_GRAMMAR = (
    'root ::= "{" "\\"content\\"" ":" string "," "\\"refs\\"" ":" "[" ref-list? "]" "}"\n'
    'string ::= "\\"" [^\\"]* "\\""\n'
    'ref-list ::= ref ("," ref)*\n'
    'ref ::= "\\"" keyword "\\""\n'
    'keyword ::= [-a-zA-Z0-9_]+\n'
)


class MemoryRefConstraintBuilder:
    """Builds grammar constraints that enforce memory reference format."""

    PRESETS = {
        "optional": MEMORY_REF_GRAMMAR,
        "strict": MEMORY_REF_STRICT_GRAMMAR,
        "multi": MEMORY_REF_MULTI_GRAMMAR,
        "json": MEMORY_REF_JSON_GRAMMAR,
    }

    def __init__(self, mode: str = "optional"):
        if mode not in self.PRESETS:
            raise ValueError(
                f"Unknown memory ref mode '{mode}'. "
                f"Available: {list(self.PRESETS.keys())}"
            )
        self.mode = mode
        self.grammar = self.PRESETS[mode]

    def build(self) -> Dict[str, str]:
        """Build the constraint parameter dict for llama.cpp."""
        return {"grammar": self.grammar}

    def to_string(self) -> str:
        return f"MemoryRefConstraint(mode='{self.mode}')\n{self.grammar}"
