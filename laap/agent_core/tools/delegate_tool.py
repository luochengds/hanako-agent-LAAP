"""DelegateTool — 委托任务给子Agent"""
TOOL_DEFS = [{"name":"delegate_task","fn":"pending","desc":"委托子任务","params":{"goal":{"type":"string"},"context":{"type":"string"}},"req":["goal"]}]
def init(): pass
