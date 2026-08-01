"""
BNF Grammar constraint builder — constructs GBNF grammar strings for llama.cpp.

Provides pre-built grammar templates and utilities for building
custom grammar rules.
"""

from typing import Dict, List, Optional


# ════════════════════════════════════════════════════════════
# Pre-built Grammar Templates (GBNF format)
# ════════════════════════════════════════════════════════════

# Pure digit sequence
DIGITS_GRAMMAR = """root ::= [0-9]+"""

# Integer (optional negative sign)
INTEGER_GRAMMAR = """root ::= "-"? [0-9]+"""

# Floating point number
FLOAT_GRAMMAR = """root ::= "-"? [0-9]+ "." [0-9]+"""

# Single word (letters only)
WORD_GRAMMAR = """root ::= [a-zA-Z]+"""

# Yes / No enum
YES_NO_GRAMMAR = """root ::= "yes" | "no" | "maybe"
"""

# Boolean
BOOLEAN_GRAMMAR = """root ::= "true" | "false"
"""

# A single sentence ending with period
SENTENCE_GRAMMAR = """root ::= sentence "."
sentence ::= [^.!?]+ ([^.!?]+)*
"""

# Simple key-value pair
KEY_VALUE_GRAMMAR = """root ::= key ":" value
key ::= [a-zA-Z_][a-zA-Z0-9_]*
value ::= [a-zA-Z0-9_ ]+
"""

# Short list format: item1, item2, item3
COMMA_LIST_GRAMMAR = """root ::= item ("," item)*
item ::= [a-zA-Z0-9_ ]+
"""

# Chinese-friendly: any non-punctuation characters
CHINESE_TEXT_GRAMMAR = """root ::= chinese-chars+
chinese-chars ::= [^。！？，、：；""''（）【】《》\n]+
"""

# Map of preset names to grammar strings
PRESET_GRAMMARS: Dict[str, str] = {
    "digits": DIGITS_GRAMMAR,
    "integer": INTEGER_GRAMMAR,
    "float": FLOAT_GRAMMAR,
    "word": WORD_GRAMMAR,
    "yes_no": YES_NO_GRAMMAR,
    "boolean": BOOLEAN_GRAMMAR,
    "sentence": SENTENCE_GRAMMAR,
    "key_value": KEY_VALUE_GRAMMAR,
    "comma_list": COMMA_LIST_GRAMMAR,
    "chinese_text": CHINESE_TEXT_GRAMMAR,
}


class GrammarConstraintBuilder:
    """Builds GBNF grammar constraints for llama.cpp completion requests."""

    def __init__(self, grammar: Optional[str] = None):
        self.grammar = grammar

    @classmethod
    def from_preset(cls, name: str) -> "GrammarConstraintBuilder":
        """Load a preset grammar by name."""
        if name not in PRESET_GRAMMARS:
            raise ValueError(
                f"Unknown preset grammar '{name}'. "
                f"Available: {list(PRESET_GRAMMARS.keys())}"
            )
        return cls(grammar=PRESET_GRAMMARS[name])

    @classmethod
    def enum(cls, values: List[str]) -> "GrammarConstraintBuilder":
        """
        Build a grammar from a list of enum values.
        E.g. enum(["red", "green", "blue"]) → root ::= "red" | "green" | "blue"
        """
        quoted = [f'"{v}"' for v in values]
        grammar = "root ::= " + " |\n    ".join(quoted)
        return cls(grammar=grammar)

    @classmethod
    def sequence(cls, *elements: str) -> "GrammarConstraintBuilder":
        """
        Build a grammar as a sequence of named elements.
        Each element is a rule name.
        E.g. sequence("greeting", "name") →
            root ::= greeting name
            greeting ::= "hello" | "hi"
            name ::= [a-zA-Z]+
        But elements are just rule references; user fills in body separately.
        """
        body = " ".join(elements)
        grammar = f"root ::= {body}"
        return cls(grammar=grammar)

    def build(self) -> Dict[str, str]:
        """
        Build the constraint parameter dict for llama.cpp.

        Returns {"grammar": <grammar_string>}
        """
        if self.grammar is None:
            return {}
        return {"grammar": self.grammar}

    def to_string(self) -> str:
        return self.grammar or "(none)"
