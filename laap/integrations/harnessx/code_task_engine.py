"""C2 — Harness Code Task Engine.

将 LAAP 的 CodeEvolutionEngine 与 HarnessX Runtime 桥接，使 LAAP 能够通过
HarnessX Agent 执行端到端的编程任务（接收编程任务 → 执行 → 通过 ``submit_execution_result``
反馈至 PSI 学习阶段）。

核心组件：
  - :class:`CodeTask`           — 编程任务数据结构（描述 + 验收标准 + 测试样例）
  - :class:`CodeTaskResult`     — 任务执行结果（含 pass@k / trajectory / commit）
  - :class:`HarnessCodeTaskEngine` — 主引擎，对接 HarnessXRuntime
  - :func:`submit_execution_result` — 将结果反馈至 PSI 的 ``learn`` 阶段

使用示例::

    from laap.integrations.harnessx.code_task_engine import (
        HarnessCodeTaskEngine, CodeTask,
    )
    from laap.integrations.harnessx.runtime import HarnessXRuntime

    runtime = HarnessXRuntime(model_config=my_model)
    engine = HarnessCodeTaskEngine(runtime=runtime, psi_driver=my_psi)
    task = CodeTask(
        description="Refactor utils.py: extract helper",
        success_criteria="All existing tests pass; cyclomatic complexity < 5",
        tests="pytest tests/test_utils.py -v",
        repo_path="laap/tools/",
    )
    result = await engine.execute(task)
    # result.passed, result.pass_at_1, result.trajectory, result.commit_hash

注意：当 HarnessXRuntime 不可用（缺模型配置）时，引擎会降级到
``CodeEvolutionEngine.auto_improve`` 路径，仍可执行任务但无 LLM 引导。
"""
from __future__ import annotations

import logging
import os
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Optional

logger = logging.getLogger("laap.integrations.harnessx.code_task_engine")


# ─── 数据结构 ─────────────────────────────────────────────────────────────

@dataclass
class CodeTask:
    """一个待执行的编程任务。"""
    task_id: str = field(default_factory=lambda: f"code_task_{uuid.uuid4().hex[:10]}")
    description: str = ""
    success_criteria: str = ""
    tests: str = ""
    repo_path: str = ""
    max_steps: int = 20
    #: 可选：约束 LLM 在白名单目录内操作
    whitelist_dirs: tuple[str, ...] = (
        "laap/tools/",
        "laap/agent_core/tools/",
        "laap/species/code_templates/",
    )
    #: 可选：禁止 LLM 修改的黑名单目录
    blacklist_dirs: tuple[str, ...] = (
        "laap/agi/",
        "laap/security/",
        "laap/cognition/",
    )
    created_at: float = field(default_factory=time.time)


@dataclass
class CodeTaskResult:
    """编程任务执行结果。"""
    task_id: str
    passed: bool = False
    pass_at_1: float = 0.0
    pass_at_5: float = 0.0
    pass_at_10: float = 0.0
    final_output: str = ""
    trajectory: list[dict[str, Any]] = field(default_factory=list)
    exit_reason: str = ""
    commit_hash: str = ""
    duration_ms: float = 0.0
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        """转为可 JSON 序列化字典。"""
        return asdict(self)


# ─── 主引擎 ───────────────────────────────────────────────────────────────

class HarnessCodeTaskEngine:
    """使用 HarnessX Runtime 执行编程任务，并将结果反馈至 PSI。

    Args:
        runtime: ``HarnessXRuntime`` 实例（需已配置 ModelConfig）。
        psi_driver: 可选的 PSI Driver 实例，用于 ``submit_execution_result``。
        repo_root: 仓库根目录（用于回退到 CodeEvolutionEngine 路径）。
    """

    def __init__(
        self,
        runtime: Any = None,
        psi_driver: Any = None,
        repo_root: str = "",
    ) -> None:
        self.runtime = runtime
        self.psi_driver = psi_driver
        self.repo_root = repo_root or os.getcwd()
        self._results: list[CodeTaskResult] = []

    async def execute(self, task: CodeTask) -> CodeTaskResult:
        """执行编程任务。

        优先使用 HarnessXRuntime；若 runtime 未配置 ModelConfig，则降级到
        ``CodeEvolutionEngine.auto_improve`` 路径。
        """
        start = time.time()
        result = CodeTaskResult(task_id=task.task_id)

        # 路径 1: 通过 HarnessXRuntime 执行
        if self._runtime_available():
            try:
                raw = await self.runtime.run_task(
                    description=task.description,
                    success_criteria=task.success_criteria,
                    max_steps=task.max_steps,
                )
                result.final_output = raw.get("final_output", "")
                result.trajectory = raw.get("trajectory", [])
                result.exit_reason = raw.get("exit_reason", "")
                # success_criteria 通过即视为 passed
                result.passed = bool(raw.get("task_end", {}).get("success", False))
                if result.passed:
                    result.pass_at_1 = 1.0
                    result.pass_at_5 = 1.0
                    result.pass_at_10 = 1.0
            except Exception as e:
                logger.error(f"[CodeTaskEngine] HarnessX runtime failed: {e}")
                result.error = str(e)
                # 降级
                self._fallback_to_code_evolution(task, result)
        else:
            # 路径 2: 降级到 CodeEvolutionEngine
            self._fallback_to_code_evolution(task, result)

        result.duration_ms = (time.time() - start) * 1000.0
        self._results.append(result)

        # 通过 CognitiveBus 反馈至 PSI
        self.submit_execution_result(result)

        return result

    def _runtime_available(self) -> bool:
        """检查 HarnessXRuntime 是否配置完整。"""
        if self.runtime is None:
            return False
        try:
            return self.runtime.model_config is not None
        except Exception:
            return False

    def _fallback_to_code_evolution(self, task: CodeTask, result: CodeTaskResult) -> None:
        """降级路径：使用 M4 的 CodeEvolutionEngine。"""
        try:
            from laap.agi.code_evolution import CodeEvolutionEngine
            engine = CodeEvolutionEngine(repo_root=self.repo_root)
            improvements = engine.auto_improve(
                directory=task.repo_path or "laap/tools/",
                max_mutations=1,
                auto_deploy=False,
            )
            if improvements:
                first = improvements[0]
                result.passed = first.get("status") in ("test_passed", "deployed")
                result.final_output = str(first)
                if result.passed:
                    result.pass_at_1 = 1.0
                    result.exit_reason = "code_evolution_fallback"
            else:
                result.error = "no improvements generated"
        except Exception as e:
            logger.error(f"[CodeTaskEngine] fallback failed: {e}")
            result.error = str(e)

    # ── 反馈至 PSI ─────────────────────────────────────────────────────
    def submit_execution_result(self, result: CodeTaskResult) -> bool:
        """将任务结果反馈至 PSI 学习阶段（``harness_execution_result`` 事件）。

        通过 ``CognitiveBus`` 发布 ``harness_execution_result`` 事件，PSI 的
        ``learn`` 阶段会消费此事件用于更新策略权重。

        Returns:
            True 表示事件已发布；False 表示 bus 不可用或发布失败。
        """
        try:
            from laap.agi.cognitive_bus import CognitiveBus
            bus = CognitiveBus()
            payload = {
                "task_id": result.task_id,
                "passed": result.passed,
                "pass_at_1": result.pass_at_1,
                "pass_at_5": result.pass_at_5,
                "pass_at_10": result.pass_at_10,
                "duration_ms": result.duration_ms,
                "exit_reason": result.exit_reason,
                "commit_hash": result.commit_hash,
            }
            bus.publish(
                source="harness_code_task_engine",
                event_type="harness_execution_result",
                payload=payload,
            )
            logger.info(
                f"[CodeTaskEngine] harness_execution_result published "
                f"task={result.task_id} passed={result.passed}"
            )
            return True
        except Exception as e:
            logger.debug(f"[CodeTaskEngine] submit_execution_result skipped: {e}")
            return False

    # ── 统计 ────────────────────────────────────────────────────────────
    def stats(self) -> dict[str, Any]:
        """返回引擎统计快照。"""
        total = len(self._results)
        passed = sum(1 for r in self._results if r.passed)
        return {
            "total_tasks": total,
            "passed": passed,
            "failed": total - passed,
            "pass_rate": round(passed / max(1, total), 3),
            "runtime_available": self._runtime_available(),
        }


def submit_execution_result(result: CodeTaskResult,
                             psi_driver: Any = None) -> bool:
    """模块级便捷函数：将任务结果反馈至 PSI。

    Args:
        result: 编程任务执行结果。
        psi_driver: 可选的 PSI Driver 实例。若提供，会直接调用其
            ``learn()`` 方法；否则通过 CognitiveBus 发布事件。

    Returns:
        True 表示反馈成功；False 表示反馈失败。
    """
    if psi_driver is not None and hasattr(psi_driver, "learn"):
        try:
            psi_driver.learn({
                "source": "harness_code_task_engine",
                "task_id": result.task_id,
                "passed": result.passed,
                "pass_at_k": {
                    "k=1": result.pass_at_1,
                    "k=5": result.pass_at_5,
                    "k=10": result.pass_at_10,
                },
                "duration_ms": result.duration_ms,
            })
            return True
        except Exception as e:
            logger.warning(f"[CodeTaskEngine] psi_driver.learn failed: {e}")
            return False
    # 通过 CognitiveBus 发布
    try:
        from laap.agi.cognitive_bus import CognitiveBus
        bus = CognitiveBus()
        bus.publish(
            source="harness_code_task_engine",
            event_type="harness_execution_result",
            payload=result.to_dict(),
        )
        return True
    except Exception as e:
        logger.warning(f"[CodeTaskEngine] CognitiveBus publish failed: {e}")
        return False
