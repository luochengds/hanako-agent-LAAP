"""SendMessageTool — 发送消息到平台"""
import json
TOOL_DEFS = [{"name":"send_message","fn":"pending","desc":"发送消息","params":{"platform":{"type":"string"},"to":{"type":"string"},"text":{"type":"string"}},"req":["platform","to","text"]}]
