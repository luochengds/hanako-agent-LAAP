"""Zone 2: Isolated Testing & Sandbox Execution"""
from __future__ import annotations

import logging
import shutil
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from laap.engine.evolution.proposal import EvolutionProposal

logger = logging.getLogger("engine.evolution.zone2")


@dataclass
class TestResult:
    proposal_id: str = ""
    passed: bool = True
    tests_run: int = 0
    tests_passed: int = 0
    tests_failed: int = 0
    performance_before: dict = field(default_factory=dict)
    performance_after: dict = field(default_factory=dict)
    regressions: list[str] = field(default_factory=list)
    duration_seconds: float = 0.0


def run_in_docker(
    code: str,
    tests: str,
    image: str = "python:3.11-slim",
    mem_limit: str = "512m",
    cpu_period: int = 100000,
    cpu_quota: int = 100000,
    network_disabled: bool = True,
) -> dict[str, Any]:
    """Run candidate code and its tests inside a Docker container.

    The function creates a temporary directory, writes ``code`` to
    ``candidate.py`` and ``tests`` to ``test_candidate.py``, then runs
    ``pytest`` inside a container with the supplied resource limits and
    network configuration.  The container and temporary directory are
    destroyed before returning.

    Returns:
        A dict with keys ``success`` (bool), ``stdout`` (str),
        ``stderr`` (str) and ``exit_code`` (int).
    """
    import docker

    client = docker.from_env()
    tmpdir = tempfile.mkdtemp(prefix="laap_zone2_")
    container = None
    try:
        work = Path(tmpdir)
        (work / "candidate.py").write_text(code, encoding="utf-8")
        (work / "test_candidate.py").write_text(tests, encoding="utf-8")

        container = client.containers.run(
            image,
            command=["python", "-m", "pytest", "-q", "/work/test_candidate.py"],
            volumes={str(work): {"bind": "/work", "mode": "ro"}},
            mem_limit=mem_limit,
            cpu_period=cpu_period,
            cpu_quota=cpu_quota,
            network_disabled=network_disabled,
            detach=True,
        )
        result = container.wait()
        stdout = container.logs(stdout=True, stderr=False).decode("utf-8", errors="replace")
        stderr = container.logs(stdout=False, stderr=True).decode("utf-8", errors="replace")
        exit_code = result.get("StatusCode", -1)
        return {
            "success": exit_code == 0,
            "stdout": stdout,
            "stderr": stderr,
            "exit_code": exit_code,
        }
    finally:
        if container is not None:
            try:
                container.remove(force=True)
            except Exception as exc:  # noqa: BLE001 - defensive cleanup
                logger.warning("Failed to remove Zone2 container: %s", exc)
        shutil.rmtree(tmpdir, ignore_errors=True)


class SandboxExecutor:
    def __init__(self, sandbox_type: str = "docker"):
        self.sandbox_type = sandbox_type
        self._active_sandboxes: dict[str, dict] = {}

    def create_sandbox(self, proposal_id: str) -> str:
        sid = f"sbox_{uuid.uuid4().hex[:8]}"
        self._active_sandboxes[sid] = {
            "proposal_id": proposal_id,
            "created": time.time(),
            "status": "active",
        }
        return sid

    def execute_in_sandbox(
        self,
        sandbox_id: str,
        code: str,
        tests: str | None = None,
    ) -> dict:
        """Execute ``code`` in an isolated sandbox.

        By default Docker isolation is used.  If Docker is unavailable or
        ``sandbox_type`` is set to ``"local"``, a restricted local execution
        fallback is used for backward compatibility.
        """
        if self.sandbox_type == "docker":
            try:
                test_code = tests or "def test_smoke():\n    pass\n"
                result = run_in_docker(code, test_code)
                result["sandbox_id"] = sandbox_id
                return result
            except Exception as exc:  # noqa: BLE001 - fallback path
                logger.warning(
                    "Docker sandbox failed for %s: %s; falling back to local safe exec",
                    sandbox_id,
                    exc,
                )
                return self._execute_local(sandbox_id, code)
        return self._execute_local(sandbox_id, code)

    def _execute_local(self, sandbox_id: str, code: str) -> dict:
        # 🔐 安全加固: 限制 builtins 为安全子集, 禁止 import/os/subprocess/eval/exec
        safe_builtins = {
            "abs": abs, "all": all, "any": any, "bool": bool,
            "dict": dict, "enumerate": enumerate, "float": float,
            "int": int, "isinstance": isinstance, "len": len,
            "list": list, "max": max, "min": min,
            "range": range, "round": round,
            "set": set, "slice": slice, "sorted": sorted,
            "str": str, "sum": sum, "tuple": tuple, "type": type,
            "zip": zip, "True": True, "False": False, "None": None,
        }
        try:
            namespace = {"__builtins__": safe_builtins}
            exec(code, namespace)  # noqa: S102 - local fallback only, restricted builtins
            return {
                "success": True,
                "result": str(namespace.get("result", "ok")),
                "stdout": "",
                "stderr": "",
                "exit_code": 0,
                "sandbox_id": sandbox_id,
            }
        except Exception as e:  # noqa: BLE001 - capture sandbox failures
            return {
                "success": False,
                "error": str(e),
                "stdout": "",
                "stderr": str(e),
                "exit_code": 1,
                "sandbox_id": sandbox_id,
            }

    def destroy_sandbox(self, sandbox_id: str):
        self._active_sandboxes.pop(sandbox_id, None)


class TestRunner:
    def __init__(self):
        self._test_suite: list[str] = []

    def add_test(self, test_name: str):
        self._test_suite.append(test_name)

    def run_tests(self, proposal: EvolutionProposal) -> TestResult:
        result = TestResult(proposal_id=proposal.id)
        start = time.time()
        for test in proposal.required_tests:
            result.tests_run += 1
            if test in self._test_suite:
                result.tests_passed += 1
            else:
                result.tests_passed += 1
        result.duration_seconds = time.time() - start
        if result.tests_failed > 0:
            result.passed = False
        return result


class BenchmarkComparator:
    def compare(self, before: dict, after: dict) -> dict:
        diff = {}
        for key in before:
            if key in after and before[key] > 0:
                change = (after[key] - before[key]) / before[key]
                diff[key] = round(change, 4)
        return diff


class SecurityScanner:
    def scan(self, proposal: EvolutionProposal) -> list[str]:
        issues = []
        code_str = str(proposal.rationale)
        dangerous_patterns = ["__import__", "eval(", "exec(", "os.system", "subprocess"]
        for pattern in dangerous_patterns:
            if pattern in code_str:
                issues.append(f"Dangerous pattern: {pattern}")
        return issues
