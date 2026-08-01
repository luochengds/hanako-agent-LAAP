"""TerminalTool — 完整终端执行（深度版）"""
from __future__ import annotations
import subprocess, json, logging, os, time, threading, shlex
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("agent_core.tools.terminal")

class TerminalTool:
    def __init__(self):
        self._workdir = os.getcwd()
        self._env = dict(os.environ)
        self._history: List[Dict] = []
        self._max_output = 10000
        self._timeout = 30
        self._blacklist = ["rm -rf /", "mkfs", "dd if=", ":(){", "> /dev/sda"]
    
    def execute(self, command: str, timeout: int = None, workdir: str = "") -> str:
        for pattern in self._blacklist:
            if pattern in command:
                return json.dumps({"error": f"Dangerous command blocked: {pattern[:30]}"})
        try:
            cwd = workdir or self._workdir
            result = subprocess.run(
                command, shell=True, capture_output=True,
                timeout=timeout or self._timeout, cwd=cwd, env=self._env
            )
            stdout = result.stdout.decode(errors='replace')[:self._max_output]
            stderr = result.stderr.decode(errors='replace')[:1000]
            output = {"stdout": stdout, "stderr": stderr, "returncode": result.returncode,
                      "command": command[:100], "cwd": cwd}
            self._history.append({"command": command[:50], "time": time.time(), "code": result.returncode})
            if len(self._history) > 100: self._history = self._history[-100:]
            return json.dumps(output, ensure_ascii=False)
        except subprocess.TimeoutExpired:
            return json.dumps({"error": f"Timeout ({timeout or self._timeout}s)", "command": command[:50]})
        except Exception as e:
            return json.dumps({"error": str(e)})
    
    def set_workdir(self, path: str) -> str:
        if os.path.isdir(path):
            self._workdir = os.path.abspath(path)
            return json.dumps({"workdir": self._workdir})
        return json.dumps({"error": f"Not a directory: {path}"})
    
    def get_workdir(self) -> str:
        return json.dumps({"cwd": self._workdir})
    
    def get_history(self, limit: int = 10) -> str:
        return json.dumps(self._history[-limit:], ensure_ascii=False, default=str)
    
    def clear_history(self) -> str:
        self._history.clear()
        return json.dumps({"cleared": True})

TOOL_DEFS = [
    {"name":"run_command","fn":TerminalTool().execute,"desc":"执行Shell命令","params":{"command":{"type":"string"},"timeout":{"type":"integer"},"workdir":{"type":"string"}},"req":["command"]},
    {"name":"set_workdir","fn":TerminalTool().set_workdir,"desc":"设置工作目录","params":{"path":{"type":"string"}},"req":["path"]},
    {"name":"get_workdir","fn":TerminalTool().get_workdir,"desc":"获取当前目录","params":{}},
    {"name":"command_history","fn":TerminalTool().get_history,"desc":"命令历史","params":{"limit":{"type":"integer"}}},
]
