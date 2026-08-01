"""Onboarding — 引导流程"""
import time, json, os
from typing import Dict, Optional

STEPS = [
    {"id": "welcome", "title": "Welcome to LAAP!", "done": False},
    {"id": "config_llm", "title": "Configure your LLM provider", "done": False},
    {"id": "test_chat", "title": "Send your first message", "done": False},
    {"id": "explore_tools", "title": "Explore available tools", "done": False},
    {"id": "complete", "title": "All done!", "done": False},
]

class Onboarding:
    def __init__(self):
        self._path = os.path.expanduser("~/.laap/onboarding.json")
        self._steps = list(STEPS)
        self._load()
    def _load(self):
        if os.path.exists(self._path):
            try:
                with open(self._path) as f:
                    data = json.load(f)
                    for step in self._steps:
                        if step["id"] in data:
                            step["done"] = data[step["id"]]
            except: pass
    def _save(self):
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        with open(self._path, 'w') as f:
            json.dump({s["id"]: s["done"] for s in self._steps}, f)
    def complete(self, step_id: str):
        for step in self._steps:
            if step["id"] == step_id:
                step["done"] = True
                self._save()
                break
    def is_complete(self) -> bool:
        return all(s["done"] for s in self._steps)
    def next_step(self) -> Optional[Dict]:
        for step in self._steps:
            if not step["done"]:
                return step
        return None
    def progress(self) -> str:
        done = sum(1 for s in self._steps if s["done"])
        return f"{done}/{len(self._steps)}"
