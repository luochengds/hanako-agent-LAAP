"""SchemaSanitizerTool — Schema验证净化"""
import json
class SchemaSanitizerTool:
    def validate(self, data, schema):
        data = json.loads(data) if isinstance(data, str) else data
        schema = json.loads(schema) if isinstance(schema, str) else schema
        errors = []
        for key, rules in schema.items():
            if rules.get("required") and key not in data:
                errors.append(f"Missing: {key}")
            if key in data and "type" in rules:
                actual = type(data[key]).__name__
                if actual != rules["type"]:
                    errors.append(f"Type mismatch: {key} should be {rules['type']}, got {actual}")
        return json.dumps({"valid": len(errors)==0, "errors": errors})
TOOL_DEFS = [{"name":"validate_schema","fn":SchemaSanitizerTool().validate,"desc":"Schema验证","params":{"data":{"type":"object"},"schema":{"type":"object"}},"req":["data","schema"]}]
