# -*- coding: utf-8 -*-
"""EventedCommunicator + MockCommunicator.

``EventedCommunicator`` 继承 SimWorld 的 ``Communicator``，在调用
原生前方法前后向 LAAP ``CognitiveBus`` 发布 ``PERCEPTION_INCOMING`` /
``ACTION_TAKEN`` 事件，让 LAAP 的认知总线实时感知 SimWorld 的物理反馈。

``MockCommunicator`` 鸭子类型实现 ``Communicator`` 接口，但内部维护
一个虚拟 2D 世界（dict of entity_id → (Vector, yaw)），不连接 UE，
用于 headless 测试和 CI。仅依赖 numpy。
"""

from __future__ import annotations

import logging
import math
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("laap.integrations.simworld.communicator")


# ─── LAAP CognitiveBus 容错导入 ───────────────────────────────

try:
    from laap.agi.cognitive_bus import CognitiveBus, CognitiveEventType
    _HAS_COG_BUS = True
except Exception:  # pragma: no cover — LAAP 认知总线可选
    CognitiveBus = None  # type: ignore
    CognitiveEventType = None  # type: ignore
    _HAS_COG_BUS = False


def _make_event_type(name: str):
    """获取 CognitiveEventType 枚举值，导入失败时返回字符串."""
    if _HAS_COG_BUS and CognitiveEventType is not None:
        try:
            return CognitiveEventType(name)
        except Exception:
            return name
    return name


# 预解析常用事件类型（容错）
EV_PERCEPTION = _make_event_type("perception_incoming")
EV_ACTION = _make_event_type("action_taken")


# ─── SimWorld Communicator 容错导入 ──────────────────────────

try:
    from simworld.communicator.communicator import Communicator as _SWCommunicator
    _HAS_SW_COMMUNICATOR = True
except Exception:  # pragma: no cover — SimWorld 可选
    _SWCommunicator = object  # type: ignore
    _HAS_SW_COMMUNICATOR = False


# ─── Vector 容错导入 ──────────────────────────────────────────

class _Vector:
    """轻量 2D 向量，仅当 simworld.utils.vector.Vector 不可用时使用."""

    def __init__(self, x=0.0, y=0.0):
        if isinstance(x, (list, tuple)) and len(x) >= 2:
            self.x = float(x[0])
            self.y = float(x[1])
        else:
            self.x = float(x)
            self.y = float(y)

    def __repr__(self):
        return "Vector(x={0}, y={1})".format(self.x, self.y)

    def distance(self, other) -> float:
        return math.hypot(self.x - other.x, self.y - other.y)


def _get_vector(x, y=None):
    """优先使用 SimWorld Vector，否则用本地 _Vector."""
    try:
        from simworld.utils.vector import Vector as _SWVector
        return _SWVector(x, y)
    except Exception:
        return _Vector(x, y)


# ═══════════════════════════════════════════════════════════════
# EventedCommunicator
# ═══════════════════════════════════════════════════════════════

class EventedCommunicator(_SWCommunicator):  # type: ignore[misc]
    """继承 SimWorld Communicator，在关键方法前后发布 CognitiveBus 事件.

    在调用原生前方法（spawn / step_forward / rotate / stop / get_camera_observation /
    get_position_and_direction / clear_env）前后向 LAAP CognitiveBus 发布：
      - 前置: ``PERCEPTION_INCOMING`` 或 ``ACTION_TAKEN`` 事件（异步，不阻塞）
      - 后置: ``ACTION_TAKEN`` 状态更新事件

    用 ``threading.Lock`` 保护事件发布，避免与 SimWorld 的 ``self.lock`` 死锁。

    若 SimWorld 不可用或 CognitiveBus 未注入，则降级为纯转发，不影响功能。
    """

    def __init__(self, unrealcv=None,
                 cognitive_bus: Optional[Any] = None,
                 event_prefix: str = "simworld"):
        """初始化.

        Args:
            unrealcv: SimWorld UnrealCV 实例.
            cognitive_bus: LAAP CognitiveBus 实例（可选）.
            event_prefix: CognitiveBus 事件源前缀.
        """
        if _HAS_SW_COMMUNICATOR:
            try:
                super().__init__(unrealcv=unrealcv)
            except TypeError:
                # 兼容旧签名
                super().__init__(unrealcv)
        else:
            # SimWorld 不可用时退化为基础对象
            self.unrealcv = unrealcv
            self.ue_manager_name = None
            self.vehicle_id_to_name = {}
            self.pedestrian_id_to_name = {}
            self.traffic_signal_id_to_name = {}
            self.humanoid_id_to_name = {}
            self.scooter_id_to_name = {}
            self.waypoint_mark_id_to_name = {}

        self.cognitive_bus = cognitive_bus
        self.event_prefix = event_prefix
        # 独立于 SimWorld self.lock 的事件锁，避免双向死锁
        self._event_lock = threading.Lock()
        self._event_counter = 0

        # 日志器（SimWorld Logger 可能不可用）
        try:
            from simworld.utils.logger import Logger as _SWLogger
            self.logger = _SWLogger.get_logger("EventedCommunicator")
        except Exception:
            self.logger = logger

    # ─── 事件发布辅助 ────────────────────────────────────────

    def _publish(self, event_type, data: Dict[str, Any]):
        """异步发布 CognitiveBus 事件（不阻塞调用方）."""
        if self.cognitive_bus is None:
            return
        try:
            with self._event_lock:
                self._event_counter += 1
                enriched = dict(data)
                enriched.setdefault("source", self.event_prefix)
                enriched.setdefault("seq", self._event_counter)
                enriched.setdefault("t", time.time())
            # CognitiveBus.publish 内部已有锁，这里不持有 _event_lock 调用
            self.cognitive_bus.publish(event_type, self.event_prefix, enriched)
        except Exception as e:
            logger.debug("publish event failed: %s", e)

    # ─── Humanoid 方法覆盖 ───────────────────────────────────

    def humanoid_step_forward(self, humanoid_id, duration, direction=0):
        """步进 — 前置 PERCEPTION_INCOMING，后置 ACTION_TAKEN."""
        self._publish(EV_PERCEPTION, {
            "op": "humanoid_step_forward",
            "humanoid_id": humanoid_id,
            "phase": "pre",
            "duration": duration,
            "direction": direction,
        })
        try:
            result = super().humanoid_step_forward(humanoid_id, duration, direction)
        except Exception as e:
            self._publish(EV_ACTION, {
                "op": "humanoid_step_forward", "phase": "error",
                "humanoid_id": humanoid_id, "error": str(e),
            })
            raise
        self._publish(EV_ACTION, {
            "op": "humanoid_step_forward",
            "humanoid_id": humanoid_id,
            "phase": "post",
            "duration": duration,
            "direction": direction,
        })
        return result

    def humanoid_rotate(self, humanoid_id, angle, direction):
        """旋转 — 前置 PERCEPTION_INCOMING，后置 ACTION_TAKEN."""
        self._publish(EV_PERCEPTION, {
            "op": "humanoid_rotate",
            "humanoid_id": humanoid_id,
            "phase": "pre",
            "angle": angle,
            "direction": direction,
        })
        try:
            result = super().humanoid_rotate(humanoid_id, angle, direction)
        except Exception as e:
            self._publish(EV_ACTION, {
                "op": "humanoid_rotate", "phase": "error",
                "humanoid_id": humanoid_id, "error": str(e),
            })
            raise
        self._publish(EV_ACTION, {
            "op": "humanoid_rotate",
            "humanoid_id": humanoid_id,
            "phase": "post",
            "angle": angle,
            "direction": direction,
        })
        return result

    def humanoid_stop(self, humanoid_id):
        """停止 — 前置 PERCEPTION_INCOMING，后置 ACTION_TAKEN."""
        self._publish(EV_PERCEPTION, {
            "op": "humanoid_stop",
            "humanoid_id": humanoid_id,
            "phase": "pre",
        })
        try:
            result = super().humanoid_stop(humanoid_id)
        except Exception as e:
            self._publish(EV_ACTION, {
                "op": "humanoid_stop", "phase": "error",
                "humanoid_id": humanoid_id, "error": str(e),
            })
            raise
        self._publish(EV_ACTION, {
            "op": "humanoid_stop",
            "humanoid_id": humanoid_id,
            "phase": "post",
        })
        return result

    def spawn_agent(self, agent, name=None, position=None,
                    model_path='/Game/TrafficSystem/Pedestrian/Base_User_Agent.Base_User_Agent_C',
                    type='humanoid'):
        """生成 agent — 前置 PERCEPTION_INCOMING，后置 ACTION_TAKEN."""
        self._publish(EV_PERCEPTION, {
            "op": "spawn_agent", "phase": "pre",
            "agent_id": getattr(agent, "id", None),
            "name": name, "type": type,
        })
        try:
            result = super().spawn_agent(agent, name, position, model_path, type)
        except Exception as e:
            self._publish(EV_ACTION, {
                "op": "spawn_agent", "phase": "error",
                "agent_id": getattr(agent, "id", None), "error": str(e),
            })
            raise
        self._publish(EV_ACTION, {
            "op": "spawn_agent", "phase": "post",
            "agent_id": getattr(agent, "id", None), "type": type,
        })
        return result

    def spawn_object(self, object_name, model_path, position, direction):
        """生成对象 — 前置 PERCEPTION_INCOMING，后置 ACTION_TAKEN."""
        self._publish(EV_PERCEPTION, {
            "op": "spawn_object", "phase": "pre",
            "object_name": object_name,
        })
        try:
            result = super().spawn_object(object_name, model_path, position, direction)
        except Exception as e:
            self._publish(EV_ACTION, {
                "op": "spawn_object", "phase": "error",
                "object_name": object_name, "error": str(e),
            })
            raise
        self._publish(EV_ACTION, {
            "op": "spawn_object", "phase": "post",
            "object_name": object_name,
        })
        return result

    def get_camera_observation(self, cam_id, viewmode, mode='direct'):
        """获取相机观测 — 前置 PERCEPTION_INCOMING，后置 PERCEPTION_INCOMING."""
        self._publish(EV_PERCEPTION, {
            "op": "get_camera_observation", "phase": "pre",
            "cam_id": cam_id, "viewmode": viewmode,
        })
        try:
            result = super().get_camera_observation(cam_id, viewmode, mode)
        except Exception as e:
            self._publish(EV_PERCEPTION, {
                "op": "get_camera_observation", "phase": "error",
                "cam_id": cam_id, "error": str(e),
            })
            raise
        self._publish(EV_PERCEPTION, {
            "op": "get_camera_observation", "phase": "post",
            "cam_id": cam_id, "viewmode": viewmode,
            "shape": getattr(result, "shape", None),
        })
        return result

    def get_position_and_direction(self, vehicle_ids=[], pedestrian_ids=[],
                                   traffic_signal_ids=[], humanoid_ids=[],
                                   scooter_ids=[]):
        """获取位置和方向 — 前置 PERCEPTION_INCOMING，后置 PERCEPTION_INCOMING."""
        self._publish(EV_PERCEPTION, {
            "op": "get_position_and_direction", "phase": "pre",
            "humanoid_ids": list(humanoid_ids or []),
        })
        try:
            result = super().get_position_and_direction(
                vehicle_ids, pedestrian_ids, traffic_signal_ids,
                humanoid_ids, scooter_ids,
            )
        except Exception as e:
            self._publish(EV_PERCEPTION, {
                "op": "get_position_and_direction", "phase": "error",
                "error": str(e),
            })
            raise
        self._publish(EV_PERCEPTION, {
            "op": "get_position_and_direction", "phase": "post",
            "entities": len(result) if isinstance(result, dict) else 0,
        })
        return result

    def clear_env(self, keep_roads=False):
        """清空环境 — 前置 ACTION_TAKEN，后置 ACTION_TAKEN."""
        self._publish(EV_ACTION, {
            "op": "clear_env", "phase": "pre", "keep_roads": keep_roads,
        })
        try:
            result = super().clear_env(keep_roads)
        except Exception as e:
            self._publish(EV_ACTION, {
                "op": "clear_env", "phase": "error", "error": str(e),
            })
            raise
        self._publish(EV_ACTION, {
            "op": "clear_env", "phase": "post", "keep_roads": keep_roads,
        })
        return result


# ═══════════════════════════════════════════════════════════════
# MockCommunicator — headless 内存世界
# ═══════════════════════════════════════════════════════════════

class MockCommunicator:
    """鸭子类型实现 Communicator 接口的内存 mock.

    内部维护虚拟 2D 世界状态: ``dict[entity_id -> (Vector, yaw)]``
    不连接 UE，所有 spawn/move 在内存中模拟。
    ``get_camera_observation`` 返回全零 numpy 数组 (1280×720×3)。
    用于 headless 测试和 CI。

    只依赖 numpy，不需要 unrealcv / cv2 / PIL。
    """

    # 默认相机分辨率
    DEFAULT_CAM_WIDTH = 1280
    DEFAULT_CAM_HEIGHT = 720

    def __init__(self, unrealcv=None, **kwargs):
        # 兼容 EventedCommunicator 的签名
        self.unrealcv = None  # 始终不连接 UE
        self.ue_manager_name = None
        self.humanoid_id_to_name: Dict[Any, str] = {}
        self.vehicle_id_to_name: Dict[Any, str] = {}
        self.pedestrian_id_to_name: Dict[Any, str] = {}
        self.traffic_signal_id_to_name: Dict[Any, str] = {}
        self.scooter_id_to_name: Dict[Any, str] = {}
        self.waypoint_mark_id_to_name: Dict[Any, str] = {}

        # 虚拟世界状态: entity_id -> {"pos": (x, y), "yaw": float, "type": str}
        self._world: Dict[Any, Dict[str, Any]] = {}
        self._lock = threading.Lock()

        # 可选的 CognitiveBus 事件发布（与 EventedCommunicator 兼容）
        self.cognitive_bus = kwargs.get("cognitive_bus")
        self.event_prefix = kwargs.get("event_prefix", "simworld")
        self._event_lock = threading.Lock()
        self._event_counter = 0

        try:
            import numpy as _np
            self._np = _np
        except ImportError as e:  # pragma: no cover
            raise RuntimeError("MockCommunicator requires numpy") from e

    # ─── 日志器 ─────────────────────────────────────────────

    @property
    def logger(self):
        return logger

    # ─── CognitiveBus 事件发布（与 EventedCommunicator 兼容） ─

    def _publish(self, event_type, data: Dict[str, Any]):
        if self.cognitive_bus is None:
            return
        try:
            with self._event_lock:
                self._event_counter += 1
                enriched = dict(data)
                enriched.setdefault("source", self.event_prefix)
                enriched.setdefault("seq", self._event_counter)
                enriched.setdefault("t", time.time())
            self.cognitive_bus.publish(event_type, self.event_prefix, enriched)
        except Exception as e:
            logger.debug("mock publish event failed: %s", e)

    # ─── 名称映射（与 Communicator 对齐） ──────────────────

    def get_humanoid_name(self, humanoid_id) -> str:
        if humanoid_id not in self.humanoid_id_to_name:
            self.humanoid_id_to_name[humanoid_id] = "GEN_BP_Humanoid_{0}".format(humanoid_id)
        return self.humanoid_id_to_name[humanoid_id]

    def get_vehicle_name(self, vehicle_id) -> str:
        if vehicle_id not in self.vehicle_id_to_name:
            self.vehicle_id_to_name[vehicle_id] = "GEN_BP_Vehicle_{0}".format(vehicle_id)
        return self.vehicle_id_to_name[vehicle_id]

    def get_pedestrian_name(self, pedestrian_id) -> str:
        if pedestrian_id not in self.pedestrian_id_to_name:
            self.pedestrian_id_to_name[pedestrian_id] = "GEN_BP_Pedestrian_{0}".format(pedestrian_id)
        return self.pedestrian_id_to_name[pedestrian_id]

    def get_scooter_name(self, scooter_id) -> str:
        if scooter_id not in self.scooter_id_to_name:
            self.scooter_id_to_name[scooter_id] = "GEN_BP_Scooter_{0}".format(scooter_id)
        return self.scooter_id_to_name[scooter_id]

    def get_traffic_signal_name(self, traffic_signal_id) -> str:
        if traffic_signal_id not in self.traffic_signal_id_to_name:
            self.traffic_signal_id_to_name[traffic_signal_id] = "GEN_BP_TrafficSignal_{0}".format(traffic_signal_id)
        return self.traffic_signal_id_to_name[traffic_signal_id]

    # ─── 世界状态查询 ───────────────────────────────────────

    def _ensure_entity(self, entity_id, etype="humanoid"):
        if entity_id not in self._world:
            self._world[entity_id] = {
                "pos": (0.0, 0.0),
                "yaw": 0.0,
                "type": etype,
                "moving": False,
                "speed": 200.0,  # cm/s 默认步速
            }
        return self._world[entity_id]

    # ─── Humanoid 方法 ──────────────────────────────────────

    def humanoid_step_forward(self, humanoid_id, duration, direction=0):
        self._publish(EV_PERCEPTION, {
            "op": "humanoid_step_forward", "phase": "pre",
            "humanoid_id": humanoid_id, "duration": duration,
        })
        with self._lock:
            ent = self._ensure_entity(humanoid_id, "humanoid")
            # direction: 0=forward, 1=backward
            sign = -1.0 if direction == 1 else 1.0
            speed = ent.get("speed", 200.0)
            yaw_rad = math.radians(ent["yaw"])
            dx = math.cos(yaw_rad) * speed * float(duration) * sign
            dy = math.sin(yaw_rad) * speed * float(duration) * sign
            ent["pos"] = (ent["pos"][0] + dx, ent["pos"][1] + dy)
            ent["moving"] = True
        self._publish(EV_ACTION, {
            "op": "humanoid_step_forward", "phase": "post",
            "humanoid_id": humanoid_id, "pos": ent["pos"],
        })

    def humanoid_rotate(self, humanoid_id, angle, direction):
        self._publish(EV_PERCEPTION, {
            "op": "humanoid_rotate", "phase": "pre",
            "humanoid_id": humanoid_id, "angle": angle, "direction": direction,
        })
        with self._lock:
            ent = self._ensure_entity(humanoid_id, "humanoid")
            # direction: 'left'/'right' 或 bool True=right
            if isinstance(direction, str):
                sign = -1.0 if direction.lower() == "left" else 1.0
            else:
                sign = 1.0 if direction else -1.0
            ent["yaw"] = (ent["yaw"] + sign * float(angle)) % 360.0
        self._publish(EV_ACTION, {
            "op": "humanoid_rotate", "phase": "post",
            "humanoid_id": humanoid_id, "yaw": ent["yaw"],
        })

    def humanoid_stop(self, humanoid_id):
        self._publish(EV_PERCEPTION, {
            "op": "humanoid_stop", "phase": "pre",
            "humanoid_id": humanoid_id,
        })
        with self._lock:
            ent = self._ensure_entity(humanoid_id, "humanoid")
            ent["moving"] = False
        self._publish(EV_ACTION, {
            "op": "humanoid_stop", "phase": "post",
            "humanoid_id": humanoid_id,
        })

    def humanoid_move_forward(self, humanoid_id):
        with self._lock:
            ent = self._ensure_entity(humanoid_id, "humanoid")
            ent["moving"] = True

    def humanoid_set_speed(self, humanoid_id, speed):
        with self._lock:
            ent = self._ensure_entity(humanoid_id, "humanoid")
            ent["speed"] = float(speed)

    # ─── Spawn 方法 ─────────────────────────────────────────

    def spawn_agent(self, agent, name=None, position=None,
                    model_path='/Game/TrafficSystem/Pedestrian/Base_User_Agent.Base_User_Agent_C',
                    type='humanoid'):
        self._publish(EV_PERCEPTION, {
            "op": "spawn_agent", "phase": "pre",
            "agent_id": getattr(agent, "id", None), "type": type,
        })
        agent_id = getattr(agent, "id", None) or name
        # 注册名称
        if type == "humanoid":
            self.get_humanoid_name(agent_id)
        with self._lock:
            if position is not None:
                pos = (float(position[0]), float(position[1]))
            else:
                agent_pos = getattr(agent, "position", None)
                if agent_pos is not None:
                    pos = (float(getattr(agent_pos, "x", 0.0)),
                           float(getattr(agent_pos, "y", 0.0)))
                else:
                    pos = (0.0, 0.0)
            agent_dir = getattr(agent, "direction", None)
            yaw = 0.0
            if agent_dir is not None:
                dx = float(getattr(agent_dir, "x", 0.0))
                dy = float(getattr(agent_dir, "y", 0.0))
                if dx != 0.0 or dy != 0.0:
                    yaw = math.degrees(math.atan2(dy, dx))
            self._world[agent_id] = {
                "pos": pos, "yaw": yaw, "type": type,
                "moving": False, "speed": 200.0,
            }
        self._publish(EV_ACTION, {
            "op": "spawn_agent", "phase": "post",
            "agent_id": agent_id, "type": type, "pos": pos,
        })

    def spawn_object(self, object_name, model_path, position, direction):
        self._publish(EV_PERCEPTION, {
            "op": "spawn_object", "phase": "pre", "object_name": object_name,
        })
        with self._lock:
            pos = (float(position[0]), float(position[1]))
            yaw = float(direction[1]) if isinstance(direction, (list, tuple)) and len(direction) >= 2 else 0.0
            self._world[object_name] = {
                "pos": pos, "yaw": yaw, "type": "object",
                "moving": False, "speed": 0.0,
            }
        self._publish(EV_ACTION, {
            "op": "spawn_object", "phase": "post",
            "object_name": object_name, "pos": pos,
        })

    # ─── 相机 / 观测 ────────────────────────────────────────

    def get_camera_observation(self, cam_id, viewmode, mode='direct'):
        self._publish(EV_PERCEPTION, {
            "op": "get_camera_observation", "phase": "pre",
            "cam_id": cam_id, "viewmode": viewmode,
        })
        # 返回全零 uint8 数组 (H, W, 3)
        img = self._np.zeros(
            (self.DEFAULT_CAM_HEIGHT, self.DEFAULT_CAM_WIDTH, 3),
            dtype=self._np.uint8,
        )
        self._publish(EV_PERCEPTION, {
            "op": "get_camera_observation", "phase": "post",
            "cam_id": cam_id, "shape": list(img.shape),
        })
        return img

    def get_position_and_direction(self, vehicle_ids=[], pedestrian_ids=[],
                                   traffic_signal_ids=[], humanoid_ids=[],
                                   scooter_ids=[]):
        """返回与 Communicator 兼容的 {(type, id): (Vector, yaw)} 字典."""
        self._publish(EV_PERCEPTION, {
            "op": "get_position_and_direction", "phase": "pre",
            "humanoid_ids": list(humanoid_ids or []),
        })
        result: Dict[Tuple[str, Any], Tuple[Any, float]] = {}
        with self._lock:
            for hid in (humanoid_ids or []):
                ent = self._world.get(hid)
                if ent is None:
                    continue
                vec = _get_vector(ent["pos"][0], ent["pos"][1])
                result[("humanoid", hid)] = (vec, ent["yaw"])
            for vid in (vehicle_ids or []):
                ent = self._world.get(vid)
                if ent is None:
                    continue
                vec = _get_vector(ent["pos"][0], ent["pos"][1])
                result[("vehicle", vid)] = (vec, ent["yaw"])
            for pid in (pedestrian_ids or []):
                ent = self._world.get(pid)
                if ent is None:
                    continue
                vec = _get_vector(ent["pos"][0], ent["pos"][1])
                result[("pedestrian", pid)] = (vec, ent["yaw"])
            for sid in (scooter_ids or []):
                ent = self._world.get(sid)
                if ent is None:
                    continue
                vec = _get_vector(ent["pos"][0], ent["pos"][1])
                result[("scooter", sid)] = (vec, ent["yaw"])
        self._publish(EV_PERCEPTION, {
            "op": "get_position_and_direction", "phase": "post",
            "entities": len(result),
        })
        return result

    def get_collision_number(self, humanoid_id):
        """Mock: 返回 (0, 0, 0, 0) — 无碰撞."""
        return (0, 0, 0, 0)

    # ─── 环境清理 ───────────────────────────────────────────

    def clear_env(self, keep_roads=False):
        self._publish(EV_ACTION, {
            "op": "clear_env", "phase": "pre", "keep_roads": keep_roads,
        })
        with self._lock:
            self._world.clear()
            self.humanoid_id_to_name.clear()
            self.vehicle_id_to_name.clear()
            self.pedestrian_id_to_name.clear()
            self.traffic_signal_id_to_name.clear()
            self.scooter_id_to_name.clear()
            self.waypoint_mark_id_to_name.clear()
        self._publish(EV_ACTION, {
            "op": "clear_env", "phase": "post", "keep_roads": keep_roads,
        })

    def disconnect(self):
        """Mock: 无操作."""
        pass

    # ─── 调试 / 测试辅助 ────────────────────────────────────

    def inspect_world(self) -> Dict[str, Any]:
        """返回当前虚拟世界状态快照（用于测试）."""
        with self._lock:
            return {
                str(k): dict(v) for k, v in self._world.items()
            }
