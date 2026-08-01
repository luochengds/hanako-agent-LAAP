"""TodoTool"""
import json,os
class TodoTool:
    def add(self,t,p="m"): return json.dumps({"id":1,"t":t})
    def complete(self,i): return json.dumps({"done":i})
    def list(self,s=""): return json.dumps([])
TOOL_DEFS = []
