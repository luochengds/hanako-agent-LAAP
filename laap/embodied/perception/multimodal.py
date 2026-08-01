"""
LAAP Embodied — 多模态感知融合管道
=====================================

将视觉、触觉、本体感知等多模态数据融合，
输出 Aris WorldModel 可以直接消费的 Entity + Relation。

这是 embodied/ 通往 Aris 认知核心的关键桥梁。

流：
    VisualProcessor → DetectedObject[]
    TactileProcessor → ContactEvent[]
    Robot Arm State → joint positions, ee pose, force
        │
        ▼
    MultimodalFusion
        │
        ├── Entities: 物体/机器人/目标
        ├── Relations: 空间关系/接触关系
        └── Events: "夹爪接触了红色方块"
            │
            ▼
    Aris WorldModel (agi/world_model.py)
"""

from __future__ import annotations

import time
import numpy as np
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass, field

from .visual import VisualProcessor, SceneGraph, DetectedObject
from .tactile import TactileProcessor, ContactEvent, ContactState


@dataclass
class PerceptionFrame:
    """感知帧 — 一个时间点的完整感知状态"""
    objects: List[Dict[str, Any]] = field(default_factory=list)   # Entity 兼容格式
    relations: List[Dict[str, Any]] = field(default_factory=list) # Relation 兼容格式
    events: List[str] = field(default_factory=list)               # 自然语言事件
    robot_state: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = 0.0


class MultimodalFusion:
    """多模态感知融合引擎

    将不同传感器的输出融合为统一的感知帧，
    输出格式兼容 Aris 的 world_model.Entity 和 world_model.Relation。

    用法：
        fusion = MultimodalFusion()
        frame = fusion.fuse(
            visual_scene=scene,
            contact_events=contacts,
            ee_pose=arm.get_eef_pose(),
            joint_pos=arm.get_state().joint_positions,
        )
        # frame.objects → Entity 格式
        # frame.relations → Relation 格式
        # frame.events → 自然语言事件
    """

    def __init__(self):
        self._last_frame: Optional[PerceptionFrame] = None
        self._frame_count = 0

    def fuse(
        self,
        visual_scene: Optional[SceneGraph] = None,
        contact_events: Optional[List[ContactEvent]] = None,
        ee_pose: Optional[np.ndarray] = None,
        joint_pos: Optional[np.ndarray] = None,
        timestamp: Optional[float] = None,
    ) -> PerceptionFrame:
        """融合所有传感器输出为一帧感知"""
        ts = timestamp or time.time()
        self._frame_count += 1

        objects: List[Dict[str, Any]] = []
        relations: List[Dict[str, Any]] = []
        events: List[str] = []

        # ── 视觉 → Entity ──
        if visual_scene is not None:
            for obj in visual_scene.objects:
                entity = {
                    "name": obj.label,
                    "entity_type": "object",
                    "properties": {
                        "position": obj.position.tolist() if obj.position is not None else None,
                        "orientation": obj.orientation.tolist() if obj.orientation is not None else None,
                        "confidence": obj.confidence,
                        "detected": True,
                        "source": "vision",
                    }
                }
                objects.append(entity)

            # 视觉空间关系
            for rel in visual_scene.relations:
                rel_entry = {
                    "source": rel[0],
                    "target": rel[1],
                    "relation_type": "spatial",
                    "properties": {"spatial_relation": rel[1], "source": "vision"},
                }
                relations.append(rel_entry)

        # ── 触觉 → Entity + Event ──
        if contact_events:
            for ce in contact_events:
                if ce.state != ContactState.NO_CONTACT:
                    # 更新物体状态
                    for obj in objects:
                        if obj["name"] == ce.entity:
                            obj["properties"]["contact_state"] = ce.state.value
                            obj["properties"]["contact_force"] = ce.force.tolist()
                            break
                    else:
                        # 触觉检测到的实体（不可见但可接触）
                        objects.append({
                            "name": ce.entity,
                            "entity_type": "object",
                            "properties": {
                                "contact_state": ce.state.value,
                                "contact_force": ce.force.tolist(),
                                "detected": True,
                                "source": "tactile",
                            }
                        })

                    # 自然语言事件
                    if ce.state == ContactState.FIRM_GRASP:
                        events.append(f"夹爪抓紧了{ce.entity}")
                    elif ce.state == ContactState.SLIPPING:
                        events.append(f"⚠ {ce.entity}正在滑落！")
                    elif ce.state == ContactState.OVERLOAD:
                        events.append(f"⚠ {ce.entity}受力过载！")

        # ── 本体感知 → Robot State ──
        robot_entity = {
            "name": "robot_arm",
            "entity_type": "agent",
            "properties": {
                "ee_pose": ee_pose.tolist() if ee_pose is not None else None,
                "joint_positions": joint_pos.tolist() if joint_pos is not None else None,
                "detected": True,
                "source": "proprioception",
            }
        }
        objects.append(robot_entity)

        frame = PerceptionFrame(
            objects=objects,
            relations=relations,
            events=events,
            robot_state={
                "ee_pose": ee_pose.tolist() if ee_pose is not None else None,
                "n_objects_visible": len(visual_scene.objects) if visual_scene else 0,
            },
            timestamp=ts,
        )
        self._last_frame = frame
        return frame

    def get_perception_frame(self) -> Optional[PerceptionFrame]:
        """获取最新感知帧"""
        return self._last_frame

    def apply_to_world_model(self, world_model) -> int:
        """将感知帧应用到 Aris 世界模型

        Args:
            world_model: Aris 的 AbstractWorldModel 实例

        Returns:
            添加的实体数量
        """
        if self._last_frame is None:
            return 0

        count = 0
        for ent in self._last_frame.objects:
            try:
                world_model.add_entity(
                    name=ent["name"],
                    entity_type=ent["entity_type"],
                    properties=ent["properties"],
                )
                count += 1
            except Exception:
                pass

        for rel in self._last_frame.relations:
            try:
                world_model.add_relation(
                    source_id=rel["source"],
                    target_id=rel["target"],
                    relation_type=rel["relation_type"],
                    strength=0.8,
                )
            except Exception:
                pass

        return count
