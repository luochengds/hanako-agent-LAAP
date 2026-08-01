"""
LAAP Embodied — 视觉感知管道
==============================

从 Genesis 相机/RGB-D 传感器提取语义信息，
输出 Aris world_model 可以消费的 Entity 和 SpatialPos。

流：
    Genesis Camera → Raw RGB/D
        → VisualProcessor
            → object_detection()  — 物体检测/分割
            → pose_estimation()   — 6D 位姿估计
            → scene_graph()       — 场景图（物体+空间关系）
        → [Entity + Relation] → Aris WorldModel
"""

from __future__ import annotations

import numpy as np
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass, field


@dataclass
class DetectedObject:
    """检测到的物体"""
    label: str                          # 类别标签
    confidence: float = 0.0             # 置信度
    bbox: Optional[np.ndarray] = None   # 2D 边界框 [x1,y1,x2,y2]
    position: Optional[np.ndarray] = None  # 3D 位置 [x,y,z]
    orientation: Optional[np.ndarray] = None  # 四元数 [w,x,y,z]（可选）
    mask: Optional[np.ndarray] = None   # 分割掩码 (optional)


@dataclass
class SceneGraph:
    """场景图 — 物体 + 空间关系"""
    objects: List[DetectedObject] = field(default_factory=list)
    relations: List[Tuple[str, str, str]] = field(default_factory=list)  # (obj1, relation, obj2)


class VisualProcessor:
    """视觉感知处理器

    从 RGB/D 图像提取语义信息。
    在仿真中直接从 Genesis 场景获取 ground truth（简单模式），
    在实际中接入 YOLO/SAM/FoundationPose（真实模式）。

    用法：
        vp = VisualProcessor()
        scene = vp.process(rgb_image, depth_image)
        for obj in scene.objects:
            print(f'看到: {obj.label} @ {obj.position}')
    """

    def __init__(self, use_ground_truth: bool = True,
                 known_objects: Optional[Dict[str, Tuple[float, float, float]]] = None):
        self._use_gt = use_ground_truth
        # 已知物体库: {name: (width, height, depth)}
        self._known = known_objects or {
            "cube_red": (0.05, 0.05, 0.05),
            "cube_blue": (0.06, 0.06, 0.06),
            "sphere": (0.05, 0.05, 0.05),
            "cylinder": (0.04, 0.04, 0.10),
        }
        self._last_scene: Optional[SceneGraph] = None

    def process(self, rgb: np.ndarray, depth: Optional[np.ndarray] = None,
                camera_intrinsics: Optional[np.ndarray] = None,
                gt_positions: Optional[Dict[str, np.ndarray]] = None) -> SceneGraph:
        """处理一帧视觉数据

        Args:
            rgb: HxWx3 uint8
            depth: HxW float (meters), or None
            camera_intrinsics: 3x3 内参矩阵, or None
            gt_positions: ground truth 物体位置 {name: [x,y,z]}（仿真模式可用）

        Returns:
            SceneGraph 场景图
        """
        if self._use_gt and gt_positions is not None:
            return self._process_ground_truth(gt_positions)
        return self._process_vision(rgb, depth)

    def _process_ground_truth(self, gt_positions: Dict[str, np.ndarray]) -> SceneGraph:
        """仿真模式：直接从场景获取 ground truth（零错误）"""
        objects = []
        relations = []

        for name, pos in gt_positions.items():
            obj = DetectedObject(
                label=name,
                confidence=1.0,
                position=np.array(pos, dtype=float),
            )
            objects.append(obj)

        # 空间关系：检测物体之间距离
        for i, a in enumerate(objects):
            for j, b in enumerate(objects):
                if i >= j:
                    continue
                if a.position is None or b.position is None:
                    continue
                dist = np.linalg.norm(a.position - b.position)
                if dist < 0.1:
                    relations.append((a.label, "touching", b.label))
                elif dist < 0.3:
                    rel = "near" if a.position[2] < b.position[2] + 0.01 else "above"
                    relations.append((a.label, rel, b.label))

        self._last_scene = SceneGraph(objects=objects, relations=relations)
        return self._last_scene

    def _process_vision(self, rgb: np.ndarray, depth: Optional[np.ndarray]) -> SceneGraph:
        """真实模式：从 RGB/D 做视觉检测

        目前是简化实现。实际应该接入 YOLO/SAM/ViT。
        Genesis 仿真中也可以直接从场景 get 物体位姿。
        """
        objects = []
        # 简化：返回空结果，真实检测后续接入
        self._last_scene = SceneGraph(objects=objects)
        return self._last_scene

    def get_scene_graph(self) -> Optional[SceneGraph]:
        """获取最后处理的场景图"""
        return self._last_scene

    def set_known_objects(self, objects: Dict[str, Tuple[float, float, float]]) -> None:
        """设置已知物体库"""
        self._known = objects
