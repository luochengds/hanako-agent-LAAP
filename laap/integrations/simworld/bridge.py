# -*- coding: utf-8 -*-
"""SimWorldBridge — 双向桥接 SimWorld 与 LAAP UnifiedWorldModel.

职责：
  1. ``sync_world_to_laap``: 轮询 SimWorld ``get_position_and_direction``，
     把 UE 中的实体位置/方向同步到 LAAP ``UnifiedWorldModel.entities``。
  2. ``sync_laap_to_world``: 把 LAAP 决策结果下发到 SimWorld communicator。
  3. ``run_sync_loop``: 后台线程持续同步。
  4. ``spawn_humanoid_in_laap``: 在 UnifiedWorldModel 中创建对应实体
     (EntityType.AGENT)。

设计要点：
  - 不修改 SimWorld 源码，所有适配在 LAAP 侧完成。
  - 所有 SimWorld / LAAP 调用都包裹在 try/except 中，避免一侧故障
    导致整个桥崩溃。
  - 同步循环用 ``threading.Event`` 控制，便于外部优雅停止。
"""

from __future__ import annotations

import logging
import math
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("laap.integrations.simworld.bridge")


# ─── LAAP UnifiedWorldModel 容错导入 ─────────────────────────

try:
    from laap.agi.world_model import (
        UnifiedWorldModel, EntityType, SpatialPos, Entity,
    )
    _HAS_LAAP_WM = True
except Exception:  # pragma: no cover — LAAP 世界模型可选
    UnifiedWorldModel = None  # type: ignore
    EntityType = None  # type: ignore
    SpatialPos = None  # type: ignore
    Entity = None  # type: ignore
    _HAS_LAAP_WM = False


# ─── CognitiveEventType 容错导入 ─────────────────────────────

try:
    from laap.agi.cognitive_bus import CognitiveEventType as _CognitiveEventType
    _HAS_COG_EV = True
except Exception:  # pragma: no cover
    _CognitiveEventType = None  # type: ignore
    _HAS_COG_EV = False


def _make_event_type(name: str):
    if _HAS_COG_EV and _CognitiveEventType is not None:
        try:
            return _CognitiveEventType(name)
        except Exception:
            return name
    return name


EV_PERCEPTION = _make_event_type("perception_incoming")
EV_ACTION = _make_event_type("action_taken")


class SimWorldBridge:
    """双向桥接 SimWorld 与 LAAP UnifiedWorldModel.

    Usage:
        bridge = SimWorldBridge(communicator, world_model, cognitive_bus)
        bridge.spawn_humanoid_in_laap(humanoid_id=0, name="Alice")
        bridge.run_sync_loop(stop_event)  # 后台同步

    Attributes:
        communicator: SimWorld Communicator 或 MockCommunicator 实例.
        world_model: LAAP UnifiedWorldModel 实例.
        cognitive_bus: 可选的 CognitiveBus，用于发布同步事件.
        sync_interval: 后台同步循环间隔（秒）.
    """

    def __init__(self,
                 communicator: Any,
                 world_model: Any,
                 cognitive_bus: Optional[Any] = None,
                 sync_interval: float = 0.1):
        self.communicator = communicator
        self.world_model = world_model
        self.cognitive_bus = cognitive_bus
        self.sync_interval = float(sync_interval)

        # SimWorld 实体 → LAAP entity eid 映射
        # key: (type, simworld_id) -> value: laap_entity_id
        self._entity_map: Dict[Tuple[str, Any], str] = {}
        self._lock = threading.Lock()

        # 同步统计
        self._sync_count = 0
        self._last_sync_time = 0.0
        self._last_error: Optional[str] = None

    # ─── 内部辅助 ───────────────────────────────────────────

    def _publish(self, event_type, data: Dict[str, Any]):
        if self.cognitive_bus is None:
            return
        try:
            self.cognitive_bus.publish(event_type, "simworld_bridge", data)
        except Exception as e:
            logger.debug("bridge publish failed: %s", e)

    def _to_laap_eid(self, entity_type: str, sim_id: Any) -> str:
        """为 SimWorld 实体生成 LAAP eid，保持映射稳定."""
        key = (entity_type, sim_id)
        with self._lock:
            if key not in self._entity_map:
                eid = "simworld_{0}_{1}".format(entity_type, sim_id)
                self._entity_map[key] = eid
            return self._entity_map[key]

    # ─── 实体创建 ───────────────────────────────────────────

    def _create_entity_in_laap(self, eid: str, name: str,
                                sim_type: str, sim_id: Any) -> Optional[Any]:
        """在 LAAP world_model 中直接以指定 eid 创建实体.

        ``UnifiedWorldModel.add_entity`` 会自动生成 eid，无法指定。
        这里直接构造 ``Entity`` 并写入 ``world_model.entities``，
        以保证 eid 与 ``_entity_map`` 中的稳定映射一致。
        """
        if not _HAS_LAAP_WM or self.world_model is None or Entity is None:
            return None
        try:
            etype = (EntityType.AGENT if sim_type == "humanoid"
                     else EntityType.OBJECT)  # type: ignore[arg-type]
            entity = Entity(
                name=name,
                entity_type=etype,
                properties={
                    "simworld_id": sim_id,
                    "simworld_type": sim_type,
                },
            )
            # 覆盖自动生成的 eid，使用我们的稳定 eid
            entity.eid = eid
            self.world_model.entities[eid] = entity
            # 记录时间线
            try:
                self.world_model._add_timeline("entity_created", {
                    "eid": eid, "name": name, "type": etype.value,
                    "source": "simworld_bridge",
                })
            except Exception:
                pass
            return entity
        except Exception as e:
            logger.debug("_create_entity_in_laap failed: %s", e)
            return None

    def spawn_humanoid_in_laap(self, humanoid_id: Any,
                               name: str = "humanoid") -> Optional[str]:
        """在 LAAP UnifiedWorldModel 中创建对应 AGENT 实体.

        Args:
            humanoid_id: SimWorld humanoid ID.
            name: 实体名.

        Returns:
            LAAP entity eid，失败时返回 None。
        """
        if not _HAS_LAAP_WM or self.world_model is None:
            logger.debug("world_model unavailable, skip spawn_humanoid_in_laap")
            return None
        try:
            eid = self._to_laap_eid("humanoid", humanoid_id)
            # 若已存在则跳过创建
            existing = self.world_model.get_entity(eid)
            if existing is None:
                self._create_entity_in_laap(eid, name, "humanoid", humanoid_id)
            # 同步初始位置
            self._sync_one_entity("humanoid", humanoid_id, eid)
            self._publish(EV_ACTION, {
                "op": "spawn_humanoid_in_laap",
                "humanoid_id": humanoid_id,
                "laap_eid": eid,
            })
            return eid
        except Exception as e:
            self._last_error = str(e)
            logger.warning("spawn_humanoid_in_laap failed: %s", e)
            return None

    def _sync_one_entity(self, sim_type: str, sim_id: Any, laap_eid: str):
        """同步单个实体的位置/方向到 LAAP world_model."""
        if not _HAS_LAAP_WM or self.world_model is None:
            return
        try:
            kwarg_name = ("{0}_ids".format(sim_type)
                          if sim_type != "traffic_signal"
                          else "traffic_signal_ids")
            result = self.communicator.get_position_and_direction(
                **{kwarg_name: [sim_id]}
            )
            key = (sim_type, sim_id)
            if key not in result:
                return
            pos_vec, yaw = result[key]
            # 更新 LAAP 实体
            entity = self.world_model.get_entity(laap_eid)
            if entity is None:
                entity = self._create_entity_in_laap(
                    laap_eid,
                    "{0}_{1}".format(sim_type, sim_id),
                    sim_type, sim_id,
                )
                if entity is None:
                    return
            # 更新位置
            if entity.pos is not None:
                entity.pos.x = float(getattr(pos_vec, "x", 0.0))
                entity.pos.y = float(getattr(pos_vec, "y", 0.0))
            # 记录历史
            entity.add_history("simworld_sync", {
                "pos": [float(getattr(pos_vec, "x", 0.0)),
                         float(getattr(pos_vec, "y", 0.0))],
                "yaw": float(yaw),
            })
        except Exception as e:
            logger.debug("sync_one_entity failed (%s,%s): %s", sim_type, sim_id, e)

    # ─── 双向同步 ───────────────────────────────────────────

    def sync_world_to_laap(self,
                           humanoid_ids: Optional[List[Any]] = None,
                           vehicle_ids: Optional[List[Any]] = None,
                           pedestrian_ids: Optional[List[Any]] = None,
                           scooter_ids: Optional[List[Any]] = None) -> int:
        """轮询 SimWorld get_position_and_direction，同步到 UnifiedWorldModel.entities.

        Args:
            humanoid_ids: 要同步的 humanoid ID 列表.
            vehicle_ids: 要同步的 vehicle ID 列表.
            pedestrian_ids: 要同步的 pedestrian ID 列表.
            scooter_ids: 要同步的 scooter ID 列表.

        Returns:
            成功同步的实体数量。
        """
        if self.world_model is None or self.communicator is None:
            return 0

        humanoid_ids = humanoid_ids or []
        vehicle_ids = vehicle_ids or []
        pedestrian_ids = pedestrian_ids or []
        scooter_ids = scooter_ids or []

        try:
            result = self.communicator.get_position_and_direction(
                vehicle_ids=vehicle_ids,
                pedestrian_ids=pedestrian_ids,
                humanoid_ids=humanoid_ids,
                scooter_ids=scooter_ids,
            )
        except Exception as e:
            self._last_error = str(e)
            logger.warning("sync_world_to_laap get_position failed: %s", e)
            return 0

        if not isinstance(result, dict):
            return 0

        synced = 0
        for key, value in result.items():
            try:
                sim_type, sim_id = key
                pos_vec, yaw = value
                laap_eid = self._to_laap_eid(sim_type, sim_id)
                # 确保实体存在
                entity = self.world_model.get_entity(laap_eid)
                if entity is None:
                    entity = self._create_entity_in_laap(
                        laap_eid,
                        "{0}_{1}".format(sim_type, sim_id),
                        sim_type, sim_id,
                    )
                    if entity is None:
                        continue
                # 更新位置
                if entity.pos is not None:
                    entity.pos.x = float(getattr(pos_vec, "x", 0.0))
                    entity.pos.y = float(getattr(pos_vec, "y", 0.0))
                # 在 properties 里记录 yaw / simworld 元信息
                entity.properties["yaw"] = float(yaw)
                entity.properties["simworld_id"] = sim_id
                entity.properties["simworld_type"] = sim_type
                entity.properties["last_sync"] = time.time()
                entity.add_history("simworld_sync", {
                    "pos": [float(getattr(pos_vec, "x", 0.0)),
                             float(getattr(pos_vec, "y", 0.0))],
                    "yaw": float(yaw),
                })
                synced += 1
            except Exception as e:
                logger.debug("sync entity %s failed: %s", key, e)

        self._sync_count += 1
        self._last_sync_time = time.time()
        self._publish(EV_PERCEPTION, {
            "op": "sync_world_to_laap",
            "synced": synced,
            "total": len(result),
            "sync_count": self._sync_count,
        })
        return synced

    def sync_laap_to_world(self, action: Dict[str, Any]) -> bool:
        """LAAP 决策结果下发到 SimWorld.

        Args:
            action: 决策字典，至少包含：
                - humanoid_id: SimWorld humanoid ID
                - action: "forward" | "rotate_left" | "rotate_right" | "stop"
                - params: dict (duration/direction/angle/clockwise)

        Returns:
            True 表示下发成功，False 表示失败。
        """
        if self.communicator is None:
            return False

        if not isinstance(action, dict):
            return False

        humanoid_id = action.get("humanoid_id")
        action_name = action.get("action", "stop")
        params = action.get("params", {}) or {}

        if humanoid_id is None:
            logger.warning("sync_laap_to_world: missing humanoid_id")
            return False

        try:
            if action_name == "forward":
                duration = params.get("duration", 1.0)
                direction = params.get("direction", 0)
                self.communicator.humanoid_step_forward(humanoid_id, duration, direction)
            elif action_name == "rotate_left":
                angle = params.get("angle", 30.0)
                self.communicator.humanoid_rotate(humanoid_id, angle, "left")
            elif action_name == "rotate_right":
                angle = params.get("angle", 30.0)
                self.communicator.humanoid_rotate(humanoid_id, angle, "right")
            elif action_name == "stop":
                self.communicator.humanoid_stop(humanoid_id)
            else:
                logger.warning("sync_laap_to_world: unknown action '%s'", action_name)
                return False

            self._publish(EV_ACTION, {
                "op": "sync_laap_to_world",
                "humanoid_id": humanoid_id,
                "action": action_name,
                "params": params,
            })
            return True
        except Exception as e:
            self._last_error = str(e)
            logger.warning("sync_laap_to_world failed: %s", e)
            return False

    # ─── 后台同步循环 ───────────────────────────────────────

    def run_sync_loop(self,
                      stop_event: threading.Event,
                      humanoid_ids: Optional[List[Any]] = None,
                      vehicle_ids: Optional[List[Any]] = None,
                      pedestrian_ids: Optional[List[Any]] = None,
                      scooter_ids: Optional[List[Any]] = None) -> None:
        """后台线程持续同步.

        Args:
            stop_event: ``threading.Event``，set() 后循环退出.
            humanoid_ids: 持续同步的 humanoid ID 列表.
            vehicle_ids: 持续同步的 vehicle ID 列表.
            pedestrian_ids: 持续同步的 pedestrian ID 列表.
            scooter_ids: 持续同步的 scooter ID 列表.
        """
        logger.info("SimWorldBridge sync loop started (interval=%ss)",
                    self.sync_interval)
        while not stop_event.is_set():
            try:
                self.sync_world_to_laap(
                    humanoid_ids=humanoid_ids,
                    vehicle_ids=vehicle_ids,
                    pedestrian_ids=pedestrian_ids,
                    scooter_ids=scooter_ids,
                )
            except Exception as e:
                self._last_error = str(e)
                logger.warning("sync loop iteration failed: %s", e)
            # 用 wait 代替 sleep，便于快速响应 stop_event
            stop_event.wait(self.sync_interval)
        logger.info("SimWorldBridge sync loop stopped (sync_count=%s)",
                    self._sync_count)

    # ─── 状态查询 ───────────────────────────────────────────

    def stats(self) -> Dict[str, Any]:
        """返回桥接器统计信息."""
        with self._lock:
            return {
                "sync_count": self._sync_count,
                "last_sync_time": self._last_sync_time,
                "last_error": self._last_error,
                "entity_map_size": len(self._entity_map),
                "sync_interval": self.sync_interval,
                "has_world_model": self.world_model is not None,
                "has_communicator": self.communicator is not None,
                "has_cognitive_bus": self.cognitive_bus is not None,
            }
