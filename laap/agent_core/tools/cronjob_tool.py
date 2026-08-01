"""CronjobTool"""
import json
class CronjobTool:
    def create(self,n,i,c): return json.dumps({"name":n})
    def list(self): return json.dumps([])
TOOL_DEFS = []
