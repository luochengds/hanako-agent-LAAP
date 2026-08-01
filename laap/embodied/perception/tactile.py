"""
LAAP Embodied — 触觉感知管道
==============================

处理接触力/触觉传感器数据，输出接触事件和力状态。
Genesis 提供 ContactForce, ContactProbe, Tactile 传感器。

流：
    Genesis ContactForce/Probe → TactileProcessor
        → contact_events()  — "夹爪接触了物体"
        → force_profile()   — "施加了 5N 力"
        → slip_detection()  — "物体正在滑落"
        → [Entity + Relation] → Aris WorldModel
"""

from __future__ import annotations

import numpy as np
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum


class ContactState(str, Enum):
    NO_CONTACT = "no_contact"
    LIGHT_TOUCH = "light_touch"     # < 1N
    FIRM_GRASP = "firm_grasp"       # 1-10N
    OVERLOAD = "overload"            # > 10N
    SLIPPING = "slipping"            # 正在滑落


@dataclass
class ContactEvent:
    """接触事件"""
    entity: str = ""
    state: ContactState = ContactState.NO_CONTACT
    force: np.ndarray = field(default_factory=lambda: np.zeros(3))
    torque: np.ndarray = field(default_factory=lambda: np.zeros(3))
    contact_point: Optional[np.ndarray] = None
    timestamp: float = 0.0


class TactileProcessor:
    """触觉感知处理器

    从力/触觉传感器提取语义触觉信息。

    用法：
        tp = TactileProcessor()
        events = tp.process(ft_reading=[Fx,Fy,Fz,Tx,Ty,Tz])
        for ev in events:
            if ev.state == ContactState.SLIPPING:
                print(f'物体滑落！抓紧！')
    """

    def __init__(self, force_thresholds: Optional[Dict[str, float]] = None):
        self._thresholds = force_thresholds or {
            "light_touch": 0.5,    # N
            "firm_grasp": 1.0,     # N
            "overload": 10.0,      # N
            "slip_detection": 0.3, # 力变化率阈值 N/s
        }
        self._prev_force: Optional[np.ndarray] = None
        self._prev_timestamp: float = 0.0
        self._contact_history: List[ContactEvent] = []

    def process(self, ft_reading: np.ndarray, entity: str = "unknown",
                timestamp: float = 0.0) -> List[ContactEvent]:
        """处理一帧力/力矩读数

        Args:
            ft_reading: (Fx,Fy,Fz,Tx,Ty,Tz)
            entity: 关联实体名
            timestamp: 时间戳

        Returns:
            接触事件列表
        """
        events = []
        force_mag = np.linalg.norm(ft_reading[:3])

        # 接触状态判定
        if force_mag < self._thresholds["light_touch"]:
            state = ContactState.NO_CONTACT
        elif force_mag < self._thresholds["firm_grasp"]:
            state = ContactState.LIGHT_TOUCH
        elif force_mag < self._thresholds["overload"]:
            state = ContactState.FIRM_GRASP
        else:
            state = ContactState.OVERLOAD

        # 滑落检测：比较力变化率
        if self._prev_force is not None and timestamp - self._prev_timestamp > 0:
            dt = max(timestamp - self._prev_timestamp, 0.001)
            dF = np.linalg.norm(ft_reading[:3] - self._prev_force[:3]) / dt
            if dF > self._thresholds["slip_detection"] and state == ContactState.FIRM_GRASP:
                state = ContactState.SLIPPING

        event = ContactEvent(
            entity=entity,
            state=state,
            force=ft_reading[:3].copy(),
            torque=ft_reading[3:6].copy(),
            timestamp=timestamp,
        )
        events.append(event)
        self._contact_history.append(event)

        # 保持历史长度
        if len(self._contact_history) > 100:
            self._contact_history = self._contact_history[-100:]

        self._prev_force = ft_reading[:3].copy()
        self._prev_timestamp = timestamp

        return events

    def get_last_event(self) -> Optional[ContactEvent]:
        """获取最近一次接触事件"""
        return self._contact_history[-1] if self._contact_history else None

    def is_grasping(self) -> bool:
        """检查是否正在抓取（最后一帧是 firm_grasp 或 overload）"""
        last = self.get_last_event()
        if last is None:
            return False
        return last.state in (ContactState.FIRM_GRASP, ContactState.OVERLOAD)

    def is_slipping(self) -> bool:
        """检查是否正在滑落"""
        last = self.get_last_event()
        if last is None:
            return False
        return last.state == ContactState.SLIPPING

    def reset(self) -> None:
        """重置历史"""
        self._prev_force = None
        self._prev_timestamp = 0.0
        self._contact_history.clear()
