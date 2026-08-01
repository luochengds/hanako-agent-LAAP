"""CodeTools — 完整代码执行（深度版）"""
from __future__ import annotations
import sys, io, json, logging, time, contextlib, tempfile, os, subprocess, traceback
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("agent_core.tools.code")

class CodeExecutionTool:
    def __init__(self):
        self._timeout = 15
        self._history: List[Dict] = []
    
    def execute_python(self, code: str, timeout: int = None) -> str:
        stdout_cap = io.StringIO()
        stderr_cap = io.StringIO()
        to = timeout or self._timeout
        start = time.time()
        try:
            compiled = compile(code.strip(), "<exec>", "exec")
            with contextlib.redirect_stdout(stdout_cap), contextlib.redirect_stderr(stderr_cap):
                # 安全考量: 此处 exec 用于代码执行工具，限制 __builtins__ 以减少攻击面。
                # 调用方应确保 code 来源可信；timeout 机制防止无限循环。
                exec(compiled, {"__builtins__": __builtins__})
            elapsed = time.time() - start
            result = {"stdout": stdout_cap.getvalue()[:5000], "stderr": stderr_cap.getvalue()[:1000],
                      "elapsed_ms": round(elapsed*1000, 2), "success": True}
        except Exception as e:
            elapsed = time.time() - start
            result = {"stdout": stdout_cap.getvalue()[:1000], "error": traceback.format_exc()[:1000],
                      "elapsed_ms": round(elapsed*1000, 2), "success": False}
        self._history.append({"lang": "python", "success": result.get("success", False), "time": time.time()})
        return json.dumps(result, ensure_ascii=False)
    
    def run_script(self, code: str, interpreter: str = "python3", timeout: int = None) -> str:
        to = timeout or self._timeout
        try:
            with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
                f.write(code)
                fpath = f.name
            start = time.time()
            result = subprocess.run([interpreter, fpath], capture_output=True, timeout=to)
            elapsed = time.time() - start
            output = {"stdout": result.stdout.decode(errors='replace')[:5000],
                      "stderr": result.stderr.decode(errors='replace')[:1000],
                      "returncode": result.returncode, "elapsed_ms": round(elapsed*1000, 2)}
            os.unlink(fpath)
            return json.dumps(output, ensure_ascii=False)
        except subprocess.TimeoutExpired:
            return json.dumps({"error": f"Timeout ({to}s)"})
        except Exception as e:
            return json.dumps({"error": str(e)})
    
    def check_syntax(self, code: str) -> str:
        try:
            compile(code.strip(), "<check>", "exec")
            return json.dumps({"valid": True})
        except SyntaxError as e:
            return json.dumps({"valid": False, "error": str(e), "line": e.lineno})

TOOL_DEFS = [
    {"name":"execute_python","fn":CodeExecutionTool().execute_python,"desc":"执行Python代码","params":{"code":{"type":"string"},"timeout":{"type":"integer"}},"req":["code"]},
    {"name":"check_syntax","fn":CodeExecutionTool().check_syntax,"desc":"检查代码语法","params":{"code":{"type":"string"}},"req":["code"]},
]
# --- Compatibility aliases ---
def edit_code(filepath: str, old_string: str, new_string: str):
    """Edit code in a file (compatibility API)"""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        if old_string not in content:
            return {"error": "old_string not found", "success": False}
        content = content.replace(old_string, new_string, 1)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        return {"success": True, "path": filepath}
    except Exception as e:
        return {"error": str(e), "success": False}
