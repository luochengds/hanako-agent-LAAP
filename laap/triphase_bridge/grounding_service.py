"""Triphase Grounding Bridge — 将 PCG 反幻觉接地封装为 LAAP 服务。"""

from __future__ import annotations

import logging
from typing import Any

from triphase.grounding import (
    Claim,
    ClaimKind,
    GroundingHarness,
    GroundingPolicy,
    BioMedicalKernel,
    FinanceKernel,
)
from triphase.memory import ComplexResonantMemory

from .codec import triphase_to_dict
from .memory_service import TriphaseMemoryService

logger = logging.getLogger(__name__)


# 内置领域核注册表（PoC 阶段内置参考核）
DOMAIN_KERNELS = {
    "biomedical": BioMedicalKernel,
    "finance": FinanceKernel,
}


class TriphaseGroundingService:
    """PCG 接地服务封装。

    职责：
    - 接收文本/声明，调用领域核进行三值裁决
    - 将证伪声明沉淀为负相位抗体
    - 返回 JSON-safe 的 GroundingReport
    """

    # GroundingHarness 内部抗体向量默认维度为 16，需独立抗体记忆库
    ANTIBODY_DIM = 16

    def __init__(
        self,
        memory_service: TriphaseMemoryService,
        default_domain: str = "biomedical",
        policy: GroundingPolicy | None = None,
    ) -> None:
        self.memory_service = memory_service
        self.default_domain = default_domain
        self.policy = policy or GroundingPolicy()
        self._harnesses: dict[str, GroundingHarness] = {}
        # 与 GroundingHarness.claim_vector 默认维度对齐的抗体记忆库
        self._antibody_memory = ComplexResonantMemory(dim=self.ANTIBODY_DIM)

    def _get_harness(self, domain: str) -> GroundingHarness:
        """延迟创建并缓存领域核 harness。"""
        if domain not in self._harnesses:
            kernel_cls = DOMAIN_KERNELS.get(domain)
            if kernel_cls is None:
                raise ValueError(f"未知领域核: {domain}，可用: {list(DOMAIN_KERNELS)}")
            self._harnesses[domain] = GroundingHarness(
                kernel=kernel_cls(),
                memory=self._antibody_memory,
                policy=self.policy,
            )
        return self._harnesses[domain]

    # ------------------------------------------------------------------ 声明解析

    @staticmethod
    def build_claim(
        text: str,
        kind: str = "fact",
        slots: dict[str, Any] | None = None,
    ) -> Claim:
        """从原始数据构造 Claim。"""
        try:
            claim_kind = ClaimKind(kind)
        except ValueError:
            claim_kind = ClaimKind.FACT
        return Claim(text=text, kind=claim_kind, slots=slots or {})

    # ------------------------------------------------------------------ 接地验证

    def verify(
        self,
        text: str,
        domain: str | None = None,
        kind: str = "fact",
        slots: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """对单条声明执行接地验证，返回 JSON-safe 报告。"""
        domain = domain or self.default_domain
        claim = self.build_claim(text, kind=kind, slots=slots)
        harness = self._get_harness(domain)
        report = harness.ground([claim])
        return triphase_to_dict(report)

    def verify_batch(
        self,
        items: list[dict[str, Any]],
        domain: str | None = None,
    ) -> dict[str, Any]:
        """对多条声明批量接地验证。"""
        domain = domain or self.default_domain
        claims = [self.build_claim(**item) for item in items]
        harness = self._get_harness(domain)
        report = harness.ground(claims)
        return triphase_to_dict(report)

    # ------------------------------------------------------------------ 抗体管理

    def record_hallucination(
        self,
        text: str,
        kind: str = "fact",
        slots: dict[str, Any] | None = None,
        reason: str = "manual",
        domain: str | None = None,
    ) -> dict[str, Any]:
        """手动将某条声明沉淀为负相位抗体（用于用户反馈或测试）。"""
        domain = domain or self.default_domain
        claim = self.build_claim(text, kind=kind, slots=slots)
        harness = self._get_harness(domain)
        vec = GroundingHarness.claim_vector(claim, dim=self.ANTIBODY_DIM)
        key = GroundingHarness._antibody_key(claim)
        item = harness.memory.store(
            vector=vec,
            payload=f"hallucination:{reason}:{text[:80]}",
            key=key,
            initial_evidence=-0.9,
        )
        logger.info("沉淀幻觉抗体: %s (%s)", text[:60], item.state.name)
        return {
            "key": item.key,
            "state": triphase_to_dict(item.state),
            "strength": float(item.strength),
        }

    def stats(self, domain: str | None = None) -> dict[str, Any]:
        """返回接地服务统计。"""
        if domain:
            harness = self._harnesses.get(domain)
            return harness.stats if harness else {}
        return {d: h.stats for d, h in self._harnesses.items()}
