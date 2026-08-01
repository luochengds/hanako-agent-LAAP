"""CheckpointTool — 检查点管理"""
import json, time, os
from typing import Any, Dict, List, Optional

class CheckpointTool:
    def __init__(self):
        self._dir = os.path.expanduser("~/.laap/checkpoints")
        os.makedirs(self._dir, exist_ok=True)
    def save(self, name: str, data: Dict) -> str:
        path = os.path.join(self._dir, f"{name}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"saved_at": time.time(), "data": data}, f, ensure_ascii=False, default=str)
        return json.dumps({"saved": name, "path": path})
    def load(self, name: str) -> str:
        path = os.path.join(self._dir, f"{name}.json")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.dumps(json.load(f), ensure_ascii=False, default=str)
        return json.dumps({"error": f"Checkpoint not found: {name}"})
    def list_checkpoints(self) -> str:
        files = [f.replace(".json","") for f in os.listdir(self._dir) if f.endswith(".json")]
        return json.dumps(files)

TOOL_DEFS = [
    {"name":"checkpoint_save","fn":CheckpointTool().save,"desc":"Save checkpoint","params":{"name":{"type":"string"},"data":{"type":"object"}},"req":["name","data"]},
    {"name":"checkpoint_load","fn":CheckpointTool().load,"desc":"Load checkpoint","params":{"name":{"type":"string"}},"req":["name"]},
    {"name":"checkpoint_list","fn":CheckpointTool().list_checkpoints,"desc":"List checkpoints","params":{}},
]
