"""HomeAssistantTool — 智能家居控制"""
import json
class HomeAssistantTool:
    def __init__(self):
        self._devices = {"light.living_room": "off", "light.bedroom": "on", "temp.living_room": "22.5"}
    def control(self, entity, state):
        if entity in self._devices:
            self._devices[entity] = state
            return json.dumps({"entity": entity, "state": state, "success": True})
        return json.dumps({"error": f"Unknown entity: {entity}"})
    def list_devices(self):
        return json.dumps(self._devices)
TOOL_DEFS = [
    {"name":"homeassistant_control","fn":HomeAssistantTool().control,"desc":"控制智能设备","params":{"entity":{"type":"string"},"state":{"type":"string"}},"req":["entity","state"]},
    {"name":"homeassistant_list","fn":HomeAssistantTool().list_devices,"desc":"列出设备","params":{}},
]
