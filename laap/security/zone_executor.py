"""Zone-aware code executor (M4 Task C4).

Bridges :class:`laap.security.zones.SafetyZone` to concrete execution
backends:

- ``SafetyZone.SANDBOX`` (Zone1): use ``RestrictedPython`` when available
  to compile/execute the code with a restricted global namespace. Fall
  back to ``ast.literal_eval`` for safe expression-only snippets. If
  neither path can handle the code, raise a clear error.
- ``SafetyZone.QUARANTINE`` and above (Zone2+): run inside a Docker
  container (``python:3.11-slim``, 512MB mem, 1 CPU, no network). The
  container mounts a temp dir, executes ``pytest`` (when ``tests`` is
  provided) or a one-shot ``python`` run, and is destroyed afterwards.

If Docker is not installed we degrade gracefully with an informative
error message; callers (and tests) can use :func:`pytest.skip` to
handle this.
"""
from __future__ import annotations

import ast
import logging
import os
import shutil
import tempfile
import time
import uuid
from typing import Any

from laap.security.zones import DEFAULT_POLICIES, SafetyZone

logger = logging.getLogger("laap.security.zone_executor")


class ZoneExecutor:
    """Execute code under a given :class:`SafetyZone`.

    Public API:
      - :meth:`execute` — run ``code`` (and optional ``tests``) in the zone
      - :meth:`validate_code_safety` — reuse :class:`SafetyGuard` from
        ``laap.agi.code_evolution`` to check the code is safe
    """

    DOCKER_IMAGE = "python:3.11-slim"
    DOCKER_MEM_LIMIT = "512m"
    DOCKER_CPU_LIMIT = "1.0"
    DOCKER_NETWORK_DISABLED = True

    # ── public API ─────────────────────────────────────────────────
    def execute(
        self,
        zone: SafetyZone,
        code: str,
        tests: str = "",
    ) -> dict[str, Any]:
        """Execute ``code`` (and ``tests`` if provided) in ``zone``.

        Returns a dict::

            {
                "success": bool,
                "stdout": str,
                "stderr": str,
                "exit_code": int,
                "duration_ms": float,
            }
        """
        start = time.time()
        if zone == SafetyZone.SANDBOX:
            result = self._execute_sandbox(code, tests)
        else:
            result = self._execute_docker(zone, code, tests)
        result["duration_ms"] = (time.time() - start) * 1000.0
        return result

    def validate_code_safety(self, code: str) -> tuple[bool, str]:
        """Validate ``code`` against :class:`SafetyGuard` patterns.

        Returns ``(is_safe, reason)``. We synthesize a throwaway
        :class:`CodeMutation` so we can reuse the existing guard logic
        without duplicating the pattern list.
        """
        try:
            from laap.agi.code_evolution import (
                CodeMutation,
                CodeTarget,
                MutationStatus,
                SafetyGuard,
            )
        except ImportError as e:
            return False, f"SafetyGuard unavailable: {e}"

        target = CodeTarget(
            file_path="laap/tools/_inline.py",
            target_type="module",
            current_code=code,
        )
        mutation = CodeMutation(
            id=f"validate_{uuid.uuid4().hex[:8]}",
            target=target,
            original_code=code,
            mutated_code=code,
            status=MutationStatus.DRAFT,
        )
        return SafetyGuard.validate_mutation(mutation)

    # ── Zone1 (Sandbox) ────────────────────────────────────────────
    def _execute_sandbox(self, code: str, tests: str) -> dict[str, Any]:
        """Zone1 — restricted in-process execution.

        Strategy:
          1. Try ``RestrictedPython`` (compile_restricted + restricted
             globals) if installed.
          2. Otherwise, accept only pure expression snippets and eval
             them via ``ast.literal_eval``.
          3. If neither path works, return ``success=False`` with a
             clear stderr explaining the limitation.
        """
        if tests:
            return {
                "success": False,
                "stdout": "",
                "stderr": (
                    "Zone1 (SANDBOX) does not support running pytest tests "
                    "in-process; promote to Zone2 (QUARANTINE) or above."
                ),
                "exit_code": 1,
            }

        # Attempt 1: RestrictedPython
        try:
            from RestrictedPython import compile_restricted
            from RestrictedPython.Guards import guarded_setattr, safer_getattr
        except ImportError:
            restricted = None
        else:
            restricted = self._run_with_restricted(code, compile_restricted,
                                                   safer_getattr, guarded_setattr)
            if restricted is not None:
                return restricted

        # Attempt 2: ast.literal_eval (expressions only)
        try:
            tree = ast.parse(code, mode="eval")
        except SyntaxError:
            return {
                "success": False,
                "stdout": "",
                "stderr": (
                    "RestrictedPython is not installed and the supplied "
                    "code is not a single literal expression; cannot run "
                    "in Zone1 SANDBOX. Install RestrictedPython "
                    "(`pip install RestrictedPython`) or promote to Zone2."
                ),
                "exit_code": 1,
            }
        try:
            value = ast.literal_eval(tree)
            return {
                "success": True,
                "stdout": repr(value),
                "stderr": "",
                "exit_code": 0,
            }
        except (ValueError, SyntaxError, MemoryError) as e:
            return {
                "success": False,
                "stdout": "",
                "stderr": f"ast.literal_eval rejected code: {e}",
                "exit_code": 1,
            }

    @staticmethod
    def _run_with_restricted(
        code: str,
        compile_restricted,
        safer_getattr,
        guarded_setattr,
    ) -> dict[str, Any] | None:
        """Run ``code`` under RestrictedPython. Returns ``None`` if it
        cannot be safely compiled/evaluated.
        """
        try:
            byte_code = compile_restricted(code, "<zone1>", "exec")
        except SyntaxError as e:
            return {
                "success": False,
                "stdout": "",
                "stderr": f"RestrictedPython rejected code: {e}",
                "exit_code": 1,
            }
        safe_globals: dict[str, Any] = {
            "__builtins__": {
                "abs": abs, "bool": bool, "dict": dict, "float": float,
                "int": int, "len": len, "list": list, "max": max, "min": min,
                "print": print, "range": range, "round": round, "set": set,
                "str": str, "sum": sum, "tuple": tuple, "zip": zip,
                "True": True, "False": False, "None": None,
            },
            "_getattr_": safer_getattr,
            "_setattr_": guarded_setattr,
            "_write_": lambda obj: obj,
            "_getitem_": lambda obj, key: obj[key],
        }
        try:
            exec(byte_code, safe_globals)  # noqa: S102 — RestrictedPython sandbox
        except Exception as e:  # noqa: BLE001 — sandboxed code may raise anything
            return {
                "success": False,
                "stdout": "",
                "stderr": f"RestrictedPython runtime error: {e}",
                "exit_code": 1,
            }
        return {
            "success": True,
            "stdout": "",
            "stderr": "",
            "exit_code": 0,
        }

    # ── Zone2+ (Docker) ────────────────────────────────────────────
    def _execute_docker(
        self,
        zone: SafetyZone,
        code: str,
        tests: str,
    ) -> dict[str, Any]:
        """Zone2+ — run inside a constrained Docker container."""
        try:
            import docker  # noqa: F401 — used to detect availability
            from docker import DockerClient
        except ImportError:
            return {
                "success": False,
                "stdout": "",
                "stderr": (
                    "Docker SDK not installed. Install with "
                    "`pip install docker` and ensure the Docker daemon is "
                    "running to execute code in Zone2+."
                ),
                "exit_code": 1,
            }

        policy = DEFAULT_POLICIES.get(zone)
        timeout = policy.execution_timeout_sec if policy else 300

        try:
            client: DockerClient = docker.from_env()
        except Exception as e:  # noqa: BLE001 — daemon may be down/unreachable
            return {
                "success": False,
                "stdout": "",
                "stderr": f"Docker daemon unavailable: {e}",
                "exit_code": 1,
            }

        with tempfile.TemporaryDirectory(prefix="laap_zone_") as workdir:
            code_path = os.path.join(workdir, "solution.py")
            with open(code_path, "w", encoding="utf-8") as f:
                f.write(code)

            run_cmd: list[str]
            if tests:
                test_path = os.path.join(workdir, "test_solution.py")
                with open(test_path, "w", encoding="utf-8") as f:
                    f.write(tests)
                run_cmd = ["pytest", "-q", "test_solution.py"]
            else:
                run_cmd = ["python", "solution.py"]

            try:
                container = client.containers.run(
                    self.DOCKER_IMAGE,
                    command=run_cmd,
                    working_dir="/work",
                    volumes={workdir: {"bind": "/work", "mode": "rw"}},
                    mem_limit=self.DOCKER_MEM_LIMIT,
                    nano_cpus=int(float(self.DOCKER_CPU_LIMIT) * 1e9),
                    network_disabled=self.DOCKER_NETWORK_DISABLED,
                    detach=True,
                    stdout=True,
                    stderr=True,
                )
            except Exception as e:  # noqa: BLE001 — docker errors are heterogeneous
                return {
                    "success": False,
                    "stdout": "",
                    "stderr": f"Failed to start container: {e}",
                    "exit_code": 1,
                }

            try:
                result = container.wait(timeout=timeout)
                exit_code = int(result.get("StatusCode", 1))
                logs = container.logs(stdout=True, stderr=True).decode(
                    "utf-8", errors="replace"
                )
                err_logs = container.logs(stdout=False, stderr=True).decode(
                    "utf-8", errors="replace"
                )
                out_logs = container.logs(stdout=True, stderr=False).decode(
                    "utf-8", errors="replace"
                )
            except Exception as e:  # noqa: BLE001 — container.wait may raise many errors
                container.kill()
                return {
                    "success": False,
                    "stdout": "",
                    "stderr": f"Container execution failed: {e}",
                    "exit_code": 1,
                }
            finally:
                try:
                    container.remove(force=True)
                except Exception:  # noqa: S110,BLE001 — best-effort cleanup
                    pass

            return {
                "success": exit_code == 0,
                "stdout": out_logs if out_logs else logs,
                "stderr": err_logs,
                "exit_code": exit_code,
            }


def is_docker_available() -> bool:
    """Return True if the Docker SDK and daemon are reachable."""
    if shutil.which("docker") is None:
        return False
    try:
        import docker
        docker.from_env().ping()
        return True
    except Exception:  # noqa: BLE001 — daemon may be missing/unreachable
        return False
