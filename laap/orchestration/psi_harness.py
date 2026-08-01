"""PSI-Harness loop integration for LAAP Aether orchestration.

DEPRECATED — 本模块已废弃
=========================
废弃原因：PSI-Harness 实现已统一至 laap.orchestration.psi_harness_bridge
替代实现：laap/orchestration/psi_harness_bridge.py
废弃时间：2026-07-11
登记位置：legacy/INDEX.md

代码保留目的：保持向后兼容，所有历史导入与符号名继续可用；
实际实现已委托给 psi_harness_bridge。
"""

from __future__ import annotations

import warnings

warnings.warn(
    "laap.orchestration.psi_harness is deprecated; "
    "use laap.orchestration.psi_harness_bridge instead.",
    DeprecationWarning,
    stacklevel=2,
)

from laap.orchestration.psi_harness_bridge import (
    HarnessActor,
    PSIActor,
    PSIHarnessOrchestrator,
    build_psi_harness_net,
)

__all__ = [
    "HarnessActor",
    "PSIActor",
    "PSIHarnessOrchestrator",
    "build_psi_harness_net",
    "build_psi_harness_kernel",
]


def build_psi_harness_kernel(psi_actor=None, harness_actor=None, kernel_id=None):
    """兼容性入口：构造一个基于 psi_harness_bridge 的 OrchestrationKernel。

    历史签名保留，但底层已统一为 PSIHarnessOrchestrator。
    返回 ``orchestrator.kernel`` 以便旧代码继续调用 ``kernel.run()``。
    """
    orchestrator = PSIHarnessOrchestrator(kernel_id=kernel_id)
    if psi_actor is not None:
        orchestrator.psi_actor = psi_actor
    if harness_actor is not None:
        orchestrator.harness_actor = harness_actor
    return orchestrator.kernel
