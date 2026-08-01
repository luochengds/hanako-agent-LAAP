"""ToolSearchTool — 工具搜索"""
import json
class ToolSearchTool:
    def search(self, query):
        from laap.agent_core.agent import Agent
        agent = Agent()
        tools = agent.tool_mgr.list_tools()
        q = query.lower()
        results = [{"name": t.name, "desc": t.description} for t in tools if q in t.name.lower() or q in t.description.lower()]
        return json.dumps(results[:10], ensure_ascii=False)
TOOL_DEFS = [{"name":"tool_search","fn":ToolSearchTool().search,"desc":"搜索可用工具","params":{"query":{"type":"string"}},"req":["query"]}]
