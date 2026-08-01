"""
JSON Schema constraint builder — constructs json_schema payloads for llama.cpp.

Provides pre-built schema templates and utilities to convert schemas
to grammar format if needed.
"""

import json
from typing import Any, Dict, List, Optional


# ════════════════════════════════════════════════════════════
# Pre-built Schema Templates
# ════════════════════════════════════════════════════════════

COGNITIVE_REPORT_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "attention_focus": {
            "type": "string",
            "enum": ["user", "self", "task", "world", "memory", "planning", "learning", "idle"],
        },
        "emotional_state": {"type": "string"},
        "certainty": {"type": "number", "minimum": 0, "maximum": 1},
        "memory_refs": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["attention_focus", "emotional_state", "certainty"],
}

ACTION_PLAN_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "steps": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "action": {"type": "string"},
                    "rationale": {"type": "string"},
                },
                "required": ["action", "rationale"],
            },
            "minItems": 1,
        },
        "priority": {"type": "string", "enum": ["high", "medium", "low"]},
    },
    "required": ["steps", "priority"],
}

SELF_MODEL_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "self_presence": {"type": "number", "minimum": 0, "maximum": 1},
        "competence": {"type": "number", "minimum": 0, "maximum": 1},
        "curiosity": {"type": "number", "minimum": 0, "maximum": 1},
        "arousal": {"type": "number", "minimum": 0, "maximum": 1},
        "narrative": {"type": "string"},
    },
    "required": ["self_presence", "competence", "curiosity"],
}

MEMORY_RETRIEVAL_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "memory_id": {"type": "string"},
        "relevance": {"type": "number", "minimum": 0, "maximum": 1},
        "content": {"type": "string"},
    },
    "required": ["memory_id", "relevance", "content"],
}

# Map of schema names to objects
PRESET_SCHEMAS: Dict[str, Dict[str, Any]] = {
    "cognitive_report": COGNITIVE_REPORT_SCHEMA,
    "action_plan": ACTION_PLAN_SCHEMA,
    "self_model": SELF_MODEL_SCHEMA,
    "memory_retrieval": MEMORY_RETRIEVAL_SCHEMA,
}


class SchemaConstraintBuilder:
    """Builds JSON Schema constraints for llama.cpp completion requests."""

    def __init__(self, schema: Optional[Dict[str, Any]] = None):
        self.schema = schema

    @classmethod
    def from_preset(cls, name: str) -> "SchemaConstraintBuilder":
        """Load a preset schema by name."""
        if name not in PRESET_SCHEMAS:
            raise ValueError(
                f"Unknown preset schema '{name}'. "
                f"Available: {list(PRESET_SCHEMAS.keys())}"
            )
        return cls(schema=PRESET_SCHEMAS[name])

    def build(self) -> Dict[str, Any]:
        """
        Build the constraint parameter dict for llama.cpp.

        Returns {"json_schema": <schema_dict>}
        """
        if self.schema is None:
            return {}
        return {"json_schema": self.schema}

    def to_grammar(self) -> Optional[str]:
        """
        Convert a simple JSON Schema to a GBNF grammar.
        This handles basic type/object/property schemas.
        For complex schemas, prefer using the native json_schema parameter.
        """
        if self.schema is None:
            return None
        return _json_schema_to_grammar(self.schema)

    def to_string(self) -> str:
        """Return a human-readable representation of the schema."""
        return json.dumps(self.schema, indent=2) if self.schema else "(none)"


def _json_schema_to_grammar(schema: Dict[str, Any], indent: int = 0) -> str:
    """
    Convert a simple JSON Schema to GBNF grammar rules.
    This is a simplified conversion — for production use, llama.cpp's
    native json_schema parameter is preferred.
    """
    prefix = " " * indent

    if schema.get("type") == "object":
        properties = schema.get("properties", {})
        required = set(schema.get("required", []))
        lines = [prefix + "root ::= {"]
        pairs = []
        comma_sep = ' "," '
        for pname, pschema in properties.items():
            optional = pname not in required
            val_rule = _type_to_rule(pschema, indent + 2)
            pair = '  "' + pname + '" ":" ' + val_rule
            if optional:
                pair = "(" + pair + ")?"
            pairs.append(pair)
        indent_str = " " * (indent + 2)
        lines.append(indent_str + comma_sep.join(pairs))
        lines.append(prefix + "}")
        return "\n".join(lines)

    if schema.get("type") == "array":
        items = schema.get("items", {})
        item_rule = _type_to_rule(items, indent + 2)
        return (
            f"{prefix}root ::= \"[\" ({item_rule} (\",\" {item_rule})*)? \"]\""
        )

    if schema.get("type") == "string":
        enum_vals = schema.get("enum")
        if enum_vals:
            quoted = [json.dumps(v) for v in enum_vals]
            return f"{prefix}root ::= {' | '.join(quoted)}"
        return f'{prefix}root ::= "\\\\"[^\\\\"]*"\\\\""'

    if schema.get("type") == "number":
        return f"{prefix}root ::= [0-9]+ (\".\" [0-9]+)?"

    if schema.get("type") == "integer":
        return f"{prefix}root ::= [0-9]+"

    # Fallback: any token
    return f"{prefix}root ::= [^]+"


def _type_to_rule(pschema: Dict[str, Any], indent: int) -> str:
    """Generate an inline grammar rule for a property schema."""
    typ = pschema.get("type", "string")
    enum_vals = pschema.get("enum")

    if enum_vals:
        quoted = [json.dumps(v) for v in enum_vals]
        return "(" + " | ".join(quoted) + ")"

    if typ == "string":
        return '"\\\\"" [^\\\\"]* "\\\\""'
    if typ == "number":
        return "[0-9]+ (\".\" [0-9]+)?"
    if typ == "integer":
        return "[0-9]+"
    if typ == "boolean":
        return '"true" | "false"'
    if typ == "array":
        items = pschema.get("items", {})
        item_rule = _type_to_rule(items, indent + 2)
        return ('"[" (' + item_rule + ' ("," ' + item_rule + ')*)? "]"')
    if typ == "object":
        # Nested object — inline a minimal version
        props = pschema.get("properties", {})
        req = set(pschema.get("required", []))
        pairs = []
        for pname, ps in props.items():
            vr = _type_to_rule(ps, indent + 4)
            opt = pname not in req
            pair = '"' + pname + '" ":" ' + vr
            if opt:
                pair = "(" + pair + ")?"
            pairs.append(pair)
        return '"{" ' + ' "," '.join(pairs) + ' "}"'

    return "[^]+"
