"""Preset constraint templates for guided generation."""

import json
import os

_TEMPLATE_DIR = os.path.dirname(__file__)


def load_template(name: str) -> str:
    """Load a template JSON or grammar file by name (without extension)."""
    # Try .json first
    json_path = os.path.join(_TEMPLATE_DIR, f"{name}.json")
    if os.path.exists(json_path):
        with open(json_path, "r", encoding="utf-8") as f:
            return f.read()
    # Try .bnf
    bnf_path = os.path.join(_TEMPLATE_DIR, f"{name}.bnf")
    if os.path.exists(bnf_path):
        with open(bnf_path, "r", encoding="utf-8") as f:
            return f.read()
    raise FileNotFoundError(f"Template '{name}' not found (tried .json and .bnf)")


def load_template_as_dict(name: str) -> dict:
    """Load a JSON template and parse it."""
    raw = load_template(name)
    return json.loads(raw)
