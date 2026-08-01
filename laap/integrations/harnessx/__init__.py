"""LAAP integration for HarnessX.

This package bridges the HarnessX behavior foundry with the LAAP PSI/Harness
architecture. It is optional: if HarnessX is not present at ``HARNESSX_ROOT``,
imports remain valid but runtime calls raise ``ImportError``.
"""

from laap.integrations.harnessx.config import (
    HARNESSX_ROOT,
    ensure_harnessx_importable,
)
from laap.integrations.harnessx.evolution import TrajectoryAdapter
from laap.integrations.harnessx.processors import PsiContextProcessor
from laap.integrations.harnessx.runtime import HarnessXRuntime
from laap.integrations.harnessx.verify import healthcheck

__all__ = [
    "ensure_harnessx_importable",
    "HARNESSX_ROOT",
    "healthcheck",
    "HarnessXRuntime",
    "PsiContextProcessor",
    "TrajectoryAdapter",
]
