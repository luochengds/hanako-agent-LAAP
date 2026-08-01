"""
JSON Schema validator — validates output against a JSON Schema.

Uses Python's json module for parsing and a custom schema checker
(no external dependencies).
"""

import json
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass, field


@dataclass
class ValidationResult:
    """Result of validating generated output."""
    is_valid: bool = True
    errors: List[str] = field(default_factory=list)
    parsed: Optional[Any] = None


def validate_against_schema(
    output: str,
    schema: Optional[Dict[str, Any]] = None,
) -> ValidationResult:
    """
    Validate a string output against a JSON Schema.

    Args:
        output: The raw string output from the LLM.
        schema: JSON Schema dict, or None to just check JSON validity.

    Returns:
        ValidationResult with is_valid, errors, and parsed data.
    """
    errors: List[str] = []

    # 1. Try to parse as JSON
    try:
        parsed = json.loads(output)
    except json.JSONDecodeError as e:
        return ValidationResult(
            is_valid=False,
            errors=[f"Invalid JSON: {e}"],
            parsed=None,
        )

    # 2. If no schema, JSON validity is enough
    if schema is None:
        return ValidationResult(is_valid=True, errors=[], parsed=parsed)

    # 3. Validate against schema
    schema_type = schema.get("type", "object")

    if schema_type == "object":
        result = _validate_object(parsed, schema)
        errors.extend(result)

    elif schema_type == "array":
        result = _validate_array(parsed, schema)
        errors.extend(result)

    elif schema_type in ("string", "number", "integer", "boolean"):
        result = _validate_primitive(parsed, schema)
        errors.extend(result)

    return ValidationResult(
        is_valid=len(errors) == 0,
        errors=errors,
        parsed=parsed,
    )


def _validate_object(obj: Any, schema: Dict[str, Any]) -> List[str]:
    """Validate an object against an object schema."""
    errors: List[str] = []

    if not isinstance(obj, dict):
        return [f"Expected object, got {type(obj).__name__}"]

    props = schema.get("properties", {})
    required = schema.get("required", [])

    # Check required fields
    for field_name in required:
        if field_name not in obj:
            errors.append(f"Missing required field: '{field_name}'")

    # Check each property
    for field_name, value in obj.items():
        if field_name in props:
            prop_schema = props[field_name]
            prop_errors = _validate_value(value, prop_schema, field_name)
            errors.extend(prop_errors)
        # Allow additional properties

    return errors


def _validate_array(arr: Any, schema: Dict[str, Any]) -> List[str]:
    """Validate an array against an array schema."""
    errors: List[str] = []

    if not isinstance(arr, list):
        return [f"Expected array, got {type(arr).__name__}"]

    items_schema = schema.get("items", {})
    min_items = schema.get("minItems", 0)
    max_items = schema.get("maxItems", len(arr) + 1)

    if len(arr) < min_items:
        errors.append(
            f"Array has {len(arr)} items, minimum is {min_items}"
        )
    if len(arr) > max_items:
        errors.append(
            f"Array has {len(arr)} items, maximum is {max_items}"
        )

    for i, item in enumerate(arr):
        item_errors = _validate_value(item, items_schema, f"[{i}]")
        errors.extend(item_errors)

    return errors


def _validate_primitive(val: Any, schema: Dict[str, Any]) -> List[str]:
    """Validate a primitive value."""
    return _validate_value(val, schema, "value")


def _validate_value(
    val: Any, schema: Dict[str, Any], path: str = ""
) -> List[str]:
    """Validate a single value against its schema definition."""
    errors: List[str] = []
    typ = schema.get("type")
    type_map = {
        "string": str,
        "number": (int, float),
        "integer": int,
        "boolean": bool,
        "object": dict,
        "array": list,
    }

    # Type check
    if typ in type_map:
        expected = type_map[typ]
        if not isinstance(val, expected):
            errors.append(
                f"'{path}': expected type '{typ}', "
                f"got {type(val).__name__}"
            )
            return errors  # Can't check further constraints

    # Enum check
    enum_vals = schema.get("enum")
    if enum_vals is not None and val not in enum_vals:
        errors.append(
            f"'{path}': value '{val}' not in enum {enum_vals}"
        )

    # Number range
    if isinstance(val, (int, float)):
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        if minimum is not None and val < minimum:
            errors.append(
                f"'{path}': {val} is less than minimum {minimum}"
            )
        if maximum is not None and val > maximum:
            errors.append(
                f"'{path}': {val} is greater than maximum {maximum}"
            )

    # Nested objects
    if typ == "object" and isinstance(val, dict):
        errors.extend(_validate_object(val, schema))

    # Nested arrays
    if typ == "array" and isinstance(val, list):
        errors.extend(_validate_array(val, schema))

    return errors


class SchemaValidator:
    """Validator that checks output against a JSON Schema."""

    def __init__(self, schema: Optional[Dict[str, Any]] = None):
        self.schema = schema

    def validate(self, output: str) -> ValidationResult:
        """Validate output string against the stored schema."""
        return validate_against_schema(output, self.schema)
