"""威胁情报同步总线 — Threat Intelligence Bus

基于 ColonyEventBus 扩展，实现生命体间的威胁情报实时同步。
单节点检测到威胁后，全网 1 分钟内同步防护规则。

References:
- LAAP2.0大版本升级方案 § 威胁情报同步
- realize-laap-agi-vision spec M5 Task I2
- laap-2-living-workspace spec Phase 6
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set


class ThreatType(Enum):
    """威胁类型"""
    MALICIOUS_CODE = "malicious_code"           # 恶意代码
    INJECTION_ATTACK = "injection_attack"       # 注入攻击
    PATH_TRAVERSAL = "path_traversal"           # 路径遍历
    PRIVILEGE_ESCALATION = "privilege_escalation"  # 提权
    DATA_EXFILTRATION = "data_exfiltration"     # 数据外泄
    RESOURCE_EXHAUSTION = "resource_exhaustion"  # 资源耗尽
    SUPPLY_CHAIN = "supply_chain"               # 供应链攻击
    SOCIAL_ENGINEERING = "social_engineering"   # 社会工程
    ANOMALOUS_BEHAVIOR = "anomalous_behavior"   # 异常行为
    UNKNOWN = "unknown"


class ThreatSeverity(Enum):
    """威胁严重程度"""
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ThreatStatus(Enum):
    """威胁状态"""
    DETECTED = "detected"       # 已检测
    BROADCASTING = "broadcasting"  # 广播中
    RECEIVED = "received"        # 已接收
    MITIGATED = "mitigated"      # 已缓解
    FALSE_POSITIVE = "false_positive"  # 误报


@dataclass
class ThreatPattern:
    """威胁模式

    描述一个检测到的威胁模式，包含检测规则与缓解建议。
    """
    threat_id: str = field(default_factory=lambda: f"threat_{uuid.uuid4().hex[:8]}")
    threat_type: ThreatType = ThreatType.UNKNOWN
    severity: ThreatSeverity = ThreatSeverity.MEDIUM
    name: str = ""  # 威胁名称
    description: str = ""  # 详细描述
    detection_rule: Dict[str, Any] = field(default_factory=dict)
    # 检测规则（如 regex pattern、AST pattern、behavior signature 等）
    mitigation: Dict[str, Any] = field(default_factory=dict)
    # 缓解措施（如 block、sanitize、alert 等）
    source_node_id: str = ""  # 检测到的节点 ID
    detected_at: datetime = field(default_factory=datetime.utcnow)
    confidence: float = 0.5  # 置信度 [0, 1]
    tags: List[str] = field(default_factory=list)
    evidence: List[str] = field(default_factory=list)  # 证据链
    status: ThreatStatus = ThreatStatus.DETECTED
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ThreatIntelEvent:
    """威胁情报事件（用于在总线上传播）"""
    threat: ThreatPattern  # 必填字段，须置于带默认值的字段之前
    event_id: str = field(default_factory=lambda: f"evt_{uuid.uuid4().hex[:8]}")
    broadcast_at: datetime = field(default_factory=datetime.utcnow)
    broadcast_by: str = ""  # 广播节点 ID
    received_by: List[str] = field(default_factory=list)  # 已接收节点列表
    ttl: int = 60  # 事件存活时间（秒）


class ThreatIntelBus:
    """威胁情报同步总线

    基于 ColonyEventBus 模式扩展，提供威胁情报的广播、接收、本地应用能力。
    单节点检测到威胁后，通过 broadcast_threat 立即通知所有节点；
    各节点通过 receive_threat 接收并更新本地检测规则。

    设计为可在单进程内使用（直接调用），也可通过 CognitiveBus 跨进程同步。
    """

    # 同步超时（秒）
    SYNC_TIMEOUT_SEC = 60
    # 最大缓冲事件数
    MAX_BUFFER_SIZE = 1000
    # 事件类型标识
    EVENT_TYPE = "THREAT_INTEL"

    def __init__(self, node_id: Optional[str] = None):
        self._node_id = node_id or f"node_{uuid.uuid4().hex[:8]}"
        self._local_threats: Dict[str, ThreatPattern] = {}  # threat_id -> pattern
        self._received_events: List[ThreatIntelEvent] = []
        self._subscribers: List[Callable[[ThreatPattern], None]] = []
        self._detection_rules: Dict[str, Dict[str, Any]] = {}  # rule_id -> rule
        self._mitigation_handlers: Dict[ThreatType, Callable] = {}
        self._stats = {
            "broadcast_count": 0,
            "received_count": 0,
            "mitigated_count": 0,
            "false_positive_count": 0,
        }

    @property
    def node_id(self) -> str:
        return self._node_id

    @property
    def stats(self) -> Dict[str, int]:
        return dict(self._stats)

    def broadcast_threat(
        self,
        threat: ThreatPattern,
        targets: Optional[List[str]] = None,
    ) -> ThreatIntelEvent:
        """广播威胁情报到所有节点

        Args:
            threat: 检测到的威胁模式
            targets: 可选的目标节点 ID 列表（None 表示广播全部）

        Returns:
            ThreatIntelEvent 广播事件
        """
        threat.source_node_id = self._node_id
        threat.status = ThreatStatus.BROADCASTING
        # 本地保存
        self._local_threats[threat.threat_id] = threat
        # 创建广播事件
        event = ThreatIntelEvent(
            threat=threat,
            broadcast_by=self._node_id,
        )
        # 通知本地订阅者
        for subscriber in self._subscribers:
            try:
                subscriber(threat)
            except Exception:
                pass  # 订阅者异常不影响广播
        # 更新本地检测规则
        self._update_local_rules(threat)
        self._stats["broadcast_count"] += 1
        return event

    def receive_threat(
        self,
        event: ThreatIntelEvent,
        apply_locally: bool = True,
    ) -> bool:
        """接收威胁情报并更新本地检测规则

        Args:
            event: 接收到的威胁情报事件
            apply_locally: 是否应用到本地检测规则

        Returns:
            True 表示接收成功
        """
        # 检查 TTL
        age = (datetime.utcnow() - event.broadcast_at).total_seconds()
        if age > event.ttl:
            return False  # 事件过期
        # 检查是否已接收
        if event.event_id in [e.event_id for e in self._received_events]:
            return False  # 重复事件
        # 记录接收
        event.received_by.append(self._node_id)
        self._received_events.append(event)
        threat = event.threat
        threat.status = ThreatStatus.RECEIVED
        # 应用到本地
        if apply_locally:
            self._update_local_rules(threat)
            self._local_threats[threat.threat_id] = threat
        self._stats["received_count"] += 1
        return True

    def subscribe(
        self,
        callback: Callable[[ThreatPattern], None],
    ) -> Callable[[], None]:
        """订阅威胁情报更新

        Args:
            callback: 收到新威胁时的回调函数

        Returns:
            取消订阅的函数
        """
        self._subscribers.append(callback)

        def unsubscribe():
            if callback in self._subscribers:
                self._subscribers.remove(callback)

        return unsubscribe

    def register_mitigation_handler(
        self,
        threat_type: ThreatType,
        handler: Callable[[ThreatPattern], bool],
    ) -> None:
        """注册威胁缓解处理器

        Args:
            threat_type: 威胁类型
            handler: 缓解处理函数，返回 True 表示成功缓解
        """
        self._mitigation_handlers[threat_type] = handler

    def mitigate_threat(self, threat_id: str) -> bool:
        """缓解指定威胁

        Args:
            threat_id: 威胁 ID

        Returns:
            True 表示缓解成功
        """
        threat = self._local_threats.get(threat_id)
        if threat is None:
            return False
        handler = self._mitigation_handlers.get(threat.threat_type)
        if handler is None:
            return False  # 无注册处理器
        try:
            success = handler(threat)
            if success:
                threat.status = ThreatStatus.MITIGATED
                self._stats["mitigated_count"] += 1
            return success
        except Exception:
            return False

    def mark_false_positive(self, threat_id: str) -> bool:
        """标记为误报

        Args:
            threat_id: 威胁 ID

        Returns:
            True 表示标记成功
        """
        threat = self._local_threats.get(threat_id)
        if threat is None:
            return False
        threat.status = ThreatStatus.FALSE_POSITIVE
        self._stats["false_positive_count"] += 1
        return True

    def get_threat(
        self,
        threat_id: str,
    ) -> Optional[ThreatPattern]:
        """获取指定威胁详情"""
        return self._local_threats.get(threat_id)

    def list_threats(
        self,
        threat_type: Optional[ThreatType] = None,
        severity: Optional[ThreatSeverity] = None,
        status: Optional[ThreatStatus] = None,
    ) -> List[ThreatPattern]:
        """查询威胁列表

        Args:
            threat_type: 可选的类型过滤
            severity: 可选的严重程度过滤
            status: 可选的状态过滤

        Returns:
            匹配的威胁列表（按检测时间倒序）
        """
        result = list(self._local_threats.values())
        if threat_type:
            result = [t for t in result if t.threat_type == threat_type]
        if severity:
            result = [t for t in result if t.severity == severity]
        if status:
            result = [t for t in result if t.status == status]
        return sorted(result, key=lambda t: t.detected_at, reverse=True)

    def get_detection_rules(self) -> Dict[str, Dict[str, Any]]:
        """获取当前所有检测规则"""
        return dict(self._detection_rules)

    def get_received_events(self, limit: int = 100) -> List[ThreatIntelEvent]:
        """获取已接收的事件列表"""
        return list(reversed(self._received_events))[:limit]

    def integrate_with_immune(
        self,
        immune_detector: Any,
    ) -> None:
        """集成到现有免疫系统检测器

        将当前所有检测规则注入到 immune_detector，使其能检测已知威胁。

        Args:
            immune_detector: laap.security.immune.detector.Detector 实例
        """
        # 注入检测规则到检测器
        for rule_id, rule in self._detection_rules.items():
            try:
                # 尝试调用检测器的 add_rule 方法（如存在）
                if hasattr(immune_detector, "add_rule"):
                    immune_detector.add_rule(rule_id, rule)
                elif hasattr(immune_detector, "register_pattern"):
                    immune_detector.register_pattern(rule)
                else:
                    # 通用回退：直接附加到 patterns 属性
                    if not hasattr(immune_detector, "patterns"):
                        immune_detector.patterns = {}
                    immune_detector.patterns[rule_id] = rule
            except Exception:
                pass

    def _update_local_rules(self, threat: ThreatPattern) -> None:
        """根据威胁模式更新本地检测规则"""
        rule_id = threat.threat_id
        rule = {
            "threat_type": threat.threat_type.value,
            "severity": threat.severity.value,
            "name": threat.name,
            "detection_rule": threat.detection_rule,
            "mitigation": threat.mitigation,
            "source": threat.source_node_id,
            "added_at": datetime.utcnow().isoformat(),
        }
        self._detection_rules[rule_id] = rule
        # 缓冲区上限保护
        if len(self._detection_rules) > self.MAX_BUFFER_SIZE:
            # 移除最旧的规则
            oldest_id = next(iter(self._detection_rules))
            self._detection_rules.pop(oldest_id, None)
