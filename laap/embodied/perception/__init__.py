"""
LAAP Embodied — 感知管道
=========================

从传感器数据到 Aris 认知核心的感知通道。

数据流：
    Genesis Sensors / Real Hardware
        → VisualProcessor (视觉: 物体检测/位姿/场景图)
        → TactileProcessor (触觉: 接触力/滑落检测)
        → MultimodalFusion (融合: Entity + Relation + Event)
        → Aris WorldModel (agi/world_model.py)

用法：
    from laap.embodied.perception import VisualProcessor, TactileProcessor, MultimodalFusion

    visual = VisualProcessor(use_ground_truth=True)
    tactile = TactileProcessor()
    fusion = MultimodalFusion()

    # 处理传感器数据
    scene = visual.process(rgb, depth, gt_positions=gt)
    events = tactile.process(ft_reading, entity='block')
    frame = fusion.fuse(visual_scene=scene, contact_events=events)
    
    # 推送到 Aris 世界模型
    n = fusion.apply_to_world_model(aris.world)
    print(f'感知到 {n} 个实体')

印记: 看到世界，理解世界
"""

from .visual import VisualProcessor, SceneGraph, DetectedObject
from .tactile import TactileProcessor, ContactEvent, ContactState
from .multimodal import MultimodalFusion, PerceptionFrame

__all__ = [
    "VisualProcessor", "SceneGraph", "DetectedObject",
    "TactileProcessor", "ContactEvent", "ContactState",
    "MultimodalFusion", "PerceptionFrame",
]
