"""MemoryTool"""
import json
class MemoryTool:
    def store(self, k, v): return json.dumps({"stored":k})
    def recall(self, k): return json.dumps({"key":k})
    def search(self, q): return json.dumps([])
TOOL_DEFS = []
