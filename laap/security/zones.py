"""四区安全分级 — LAAP Security Zones

实现 LAAP 四区安全架构：Sandbox → Quarantine → Test → Production。
所有自演化代码、外部依赖、未审计变更必须按此流程晋升，确保生产环境安全。

References:
- LAAP2.0大版本升级方案 § 四区安全架构
- realize-laap-agi-vision spec M5 Task I1
- laap-2-living-workspace spec Phase 6
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional


class SafetyZone(Enum):
    """安全区域枚举（按安全级别递增）"""
    SANDBOX = "sandbox"          # 沙箱区：完全隔离，无网络，受限资源
    QUARANTINE = "quarantine"    # 隔离区：含审计日志，可有限网络
    TEST = "test"                # 测试区：完整测试环境，模拟生产
    PRODUCTION = "production"    # 生产区：真实环境，最高权限


class ActionType(Enum):
    """操作类型"""
    CODE_EXECUTION = "code_execution"           # 代码执行
    FILE_WRITE = "file_write"                   # 文件写入
    NETWORK_ACCESS = "network_access"           # 网络访问
    DATABASE_WRITE = "database_write"           # 数据库写入
    EXTERNAL_API_CALL = "external_api_call"     # 外部 API 调用
    SYSTEM_MODIFICATION = "system_modification" # 系统修改
    DEPLOYMENT = "deployment"                   # 部署
    ROLLBACK = "rollback"                       # 回滚
    READ_ONLY = "read_only"                     # 只读


@dataclass
class ZonePolicy:
    """区域策略配置

    定义每个区域允许的操作、资源限制、网络访问、回滚策略等。
    """
    zone: SafetyZone
    allowed_actions: List[ActionType] = field(default_factory=list)
    denied_actions: List[ActionType] = field(default_factory=list)
    network_access: bool = False
    cpu_limit: str = "1.0"           # CPU 配额
    memory_limit_mb: int = 512       # 内存上限（MB）
    disk_limit_mb: int = 1024        # 磁盘上限（MB）
    execution_timeout_sec: int = 300 # 执行超时
    requires_approval: bool = False  # 是否需要人类审批
    requires_audit_log: bool = True  # 是否记录审计日志
    auto_rollback_on_failure: bool = True  # 失败时自动回滚
    max_concurrent_tasks: int = 4    # 最大并发任务数


# 各区域的默认策略
DEFAULT_POLICIES: Dict[SafetyZone, ZonePolicy] = {
    SafetyZone.SANDBOX: ZonePolicy(
        zone=SafetyZone.SANDBOX,
        allowed_actions=[ActionType.CODE_EXECUTION, ActionType.FILE_WRITE, ActionType.READ_ONLY],
        denied_actions=[ActionType.NETWORK_ACCESS, ActionType.DATABASE_WRITE,
                       ActionType.EXTERNAL_API_CALL, ActionType.SYSTEM_MODIFICATION,
                       ActionType.DEPLOYMENT],
        network_access=False,
        cpu_limit="1.0",
        memory_limit_mb=512,
        disk_limit_mb=1024,
        execution_timeout_sec=300,
        requires_approval=False,
        requires_audit_log=True,
        auto_rollback_on_failure=True,
        max_concurrent_tasks=4,
    ),
    SafetyZone.QUARANTINE: ZonePolicy(
        zone=SafetyZone.QUARANTINE,
        allowed_actions=[ActionType.CODE_EXECUTION, ActionType.FILE_WRITE,
                        ActionType.NETWORK_ACCESS, ActionType.READ_ONLY],
        denied_actions=[ActionType.DATABASE_WRITE, ActionType.SYSTEM_MODIFICATION,
                       ActionType.DEPLOYMENT],
        network_access=True,  # 有限网络（白名单）
        cpu_limit="2.0",
        memory_limit_mb=1024,
        disk_limit_mb=2048,
        execution_timeout_sec=600,
        requires_approval=False,
        requires_audit_log=True,
        auto_rollback_on_failure=True,
        max_concurrent_tasks=2,
    ),
    SafetyZone.TEST: ZonePolicy(
        zone=SafetyZone.TEST,
        allowed_actions=[ActionType.CODE_EXECUTION, ActionType.FILE_WRITE,
                        ActionType.NETWORK_ACCESS, ActionType.DATABASE_WRITE,
                        ActionType.EXTERNAL_API_CALL, ActionType.READ_ONLY],
        denied_actions=[ActionType.SYSTEM_MODIFICATION, ActionType.DEPLOYMENT],
        network_access=True,
        cpu_limit="4.0",
        memory_limit_mb=2048,
        disk_limit_mb=4096,
        execution_timeout_sec=1800,
        requires_approval=False,
        requires_audit_log=True,
        auto_rollback_on_failure=True,
        max_concurrent_tasks=8,
    ),
    SafetyZone.PRODUCTION: ZonePolicy(
        zone=SafetyZone.PRODUCTION,
        allowed_actions=list(ActionType),  # 全部允许（但需审批）
        denied_actions=[],
        network_access=True,
        cpu_limit="8.0",
        memory_limit_mb=4096,
        disk_limit_mb=10240,
        execution_timeout_sec=3600,
        requires_approval=True,
        requires_audit_log=True,
        auto_rollback_on_failure=False,  # 生产区不自动回滚，需人工介入
        max_concurrent_tasks=16,
    ),
}


@dataclass
class PromotionRequest:
    """晋升申请"""
    request_id: str
    artifact_id: str  # 待晋升的产物 ID（代码变更、依赖、配置等）
    from_zone: SafetyZone
    to_zone: SafetyZone
    test_results: Dict[str, Any] = field(default_factory=dict)
    performance_metrics: Dict[str, float] = field(default_factory=dict)
    requested_at: datetime = field(default_factory=datetime.utcnow)
    requested_by: str = ""
    approval_token: Optional[str] = None
    status: str = "pending"  # pending/approved/rejected/promoted


class ZoneManager:
    """区域管理器

    负责操作分类、策略执行、晋升流程管理。
    所有安全相关决策通过本类进行，确保统一的策略边界。
    """

    # 晋升路径：严格按顺序
    PROMOTION_PATH = [
        SafetyZone.SANDBOX,
        SafetyZone.QUARANTINE,
        SafetyZone.TEST,
        SafetyZone.PRODUCTION,
    ]

    def __init__(self, policies: Optional[Dict[SafetyZone, ZonePolicy]] = None):
        self._policies = policies or dict(DEFAULT_POLICIES)
        self._promotion_history: List[PromotionRequest] = []
        self._audit_log: List[Dict[str, Any]] = []
        self._approval_callbacks: Dict[str, Callable[[PromotionRequest], bool]] = {}

    def classify_action(self, action: ActionType, target_zone: SafetyZone) -> SafetyZone:
        """根据操作类型与目标判断应在哪个区域执行

        Args:
            action: 操作类型
            target_zone: 期望执行的区域

        Returns:
            实际应执行的区域（可能高于目标区域，如果操作需要更强隔离）
        """
        # 高风险操作必须从 Sandbox 开始
        high_risk_actions = {
            ActionType.CODE_EXECUTION,
            ActionType.SYSTEM_MODIFICATION,
            ActionType.DEPLOYMENT,
        }
        if action in high_risk_actions and target_zone == SafetyZone.PRODUCTION:
            # 生产区的高风险操作需先在 Sandbox 验证
            return SafetyZone.SANDBOX
        return target_zone

    def enforce(self, zone: SafetyZone, action: ActionType) -> bool:
        """执行策略校验：检查操作是否允许在指定区域执行

        Args:
            zone: 目标区域
            action: 操作类型

        Returns:
            True 表示允许执行
        """
        policy = self._policies.get(zone)
        if policy is None:
            self._log_audit(zone, action, False, "未知区域")
            return False
        # 检查显式拒绝
        if action in policy.denied_actions:
            self._log_audit(zone, action, False, "操作在拒绝列表中")
            return False
        # 检查允许列表
        if action not in policy.allowed_actions:
            self._log_audit(zone, action, False, "操作不在允许列表中")
            return False
        self._log_audit(zone, action, True, "策略校验通过")
        return True

    def get_policy(self, zone: SafetyZone) -> ZonePolicy:
        """获取指定区域的策略"""
        return self._policies.get(zone, DEFAULT_POLICIES[SafetyZone.SANDBOX])

    def can_promote(self, from_zone: SafetyZone, to_zone: SafetyZone) -> bool:
        """检查是否允许从 from_zone 晋升到 to_zone

        Args:
            from_zone: 起始区域
            to_zone: 目标区域

        Returns:
            True 表示路径合法（必须是相邻晋升）
        """
        try:
            from_idx = self.PROMOTION_PATH.index(from_zone)
            to_idx = self.PROMOTION_PATH.index(to_zone)
        except ValueError:
            return False
        # 必须是相邻晋升（不允许跨级）
        return to_idx == from_idx + 1

    def request_promotion(
        self,
        artifact_id: str,
        from_zone: SafetyZone,
        to_zone: SafetyZone,
        test_results: Optional[Dict[str, Any]] = None,
        performance_metrics: Optional[Dict[str, float]] = None,
        requested_by: str = "",
    ) -> PromotionRequest:
        """提交晋升申请

        Args:
            artifact_id: 待晋升产物 ID
            from_zone: 起始区域
            to_zone: 目标区域
            test_results: 测试结果
            performance_metrics: 性能指标
            requested_by: 申请者

        Returns:
            PromotionRequest 晋升申请对象

        Raises:
            ValueError: 晋升路径不合法
        """
        if not self.can_promote(from_zone, to_zone):
            raise ValueError(
                f"非法晋升路径：{from_zone.value} → {to_zone.value}，"
                f"必须按 Sandbox → Quarantine → Test → Production 顺序相邻晋升"
            )
        request = PromotionRequest(
            request_id=f"promo_{len(self._promotion_history) + 1:04d}",
            artifact_id=artifact_id,
            from_zone=from_zone,
            to_zone=to_zone,
            test_results=test_results or {},
            performance_metrics=performance_metrics or {},
            requested_by=requested_by,
        )
        self._promotion_history.append(request)
        self._log_audit(to_zone, ActionType.DEPLOYMENT, False,
                       f"晋升申请提交：{request.request_id}")
        return request

    def approve_promotion(
        self,
        request_id: str,
        approval_token: str,
    ) -> PromotionRequest:
        """审批晋升申请

        Args:
            request_id: 申请 ID
            approval_token: 审批令牌

        Returns:
            更新后的 PromotionRequest

        Raises:
            ValueError: 申请不存在或已处理
        """
        request = self._find_request(request_id)
        if request is None:
            raise ValueError(f"晋升申请不存在：{request_id}")
        if request.status != "pending":
            raise ValueError(f"申请已处理：当前状态 {request.status}")
        # 检查目标区域是否需要审批
        target_policy = self.get_policy(request.to_zone)
        if target_policy.requires_approval and not approval_token:
            raise ValueError("目标区域需要审批令牌")
        request.approval_token = approval_token
        request.status = "approved"
        self._log_audit(request.to_zone, ActionType.DEPLOYMENT, True,
                       f"晋升申请批准：{request_id}")
        return request

    def execute_promotion(self, request_id: str) -> PromotionRequest:
        """执行已批准的晋升

        Args:
            request_id: 申请 ID

        Returns:
            更新后的 PromotionRequest（status=promoted）

        Raises:
            ValueError: 申请未批准或不存在
        """
        request = self._find_request(request_id)
        if request is None:
            raise ValueError(f"晋升申请不存在：{request_id}")
        if request.status != "approved":
            raise ValueError(f"申请未批准，当前状态：{request.status}")
        request.status = "promoted"
        self._log_audit(request.to_zone, ActionType.DEPLOYMENT, True,
                       f"晋升执行完成：{request_id}，"
                       f"{request.from_zone.value} → {request.to_zone.value}")
        return request

    def get_audit_log(
        self,
        zone: Optional[SafetyZone] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """查询审计日志

        Args:
            zone: 可选的区域过滤
            limit: 返回上限

        Returns:
            审计日志列表（按时间倒序）
        """
        logs = self._audit_log
        if zone:
            logs = [l for l in logs if l.get("zone") == zone]
        return list(reversed(logs))[:limit]

    def get_promotion_history(
        self,
        artifact_id: Optional[str] = None,
    ) -> List[PromotionRequest]:
        """查询晋升历史"""
        if artifact_id:
            return [r for r in self._promotion_history if r.artifact_id == artifact_id]
        return list(self._promotion_history)

    def _find_request(self, request_id: str) -> Optional[PromotionRequest]:
        """查找晋升申请"""
        for r in self._promotion_history:
            if r.request_id == request_id:
                return r
        return None

    def _log_audit(
        self,
        zone: SafetyZone,
        action: ActionType,
        allowed: bool,
        message: str,
    ) -> None:
        """记录审计日志"""
        self._audit_log.append({
            "timestamp": datetime.utcnow().isoformat(),
            "zone": zone,
            "action": action,
            "allowed": allowed,
            "message": message,
        })
