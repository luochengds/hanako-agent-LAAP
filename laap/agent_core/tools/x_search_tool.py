"""XSearchTool — X/Twitter搜索"""
import json
class XSearchTool:
    def search(self, query, limit=10):
        return json.dumps({"results": [{"text": f"Result {i}", "user": "user{i}"} for i in range(min(limit,5))]})
TOOL_DEFS = [{"name":"x_search","fn":XSearchTool().search,"desc":"X搜索","params":{"query":{"type":"string"},"limit":{"type":"integer"}},"req":["query"]}]
