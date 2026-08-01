"""LAAP Skills — Preset Registry (P5-laaper-market)

社区示例 LAAPer 预设包注册表。维护 4 个默认预设包的元数据。

每个预设包含：
- id: 预设包 ID（如 "aris"）
- name: 显示名（如 "Aris 默认包"）
- description: 描述
- yuan: 元认知模板（性格核心）
- ishiki: 意识模板（思维方式）
- avatar_seed: 形象生成种子
- color: 主题色
- initial_skills: 初始技能包列表
- charter_version: 宪章版本（v1.0）

克隆语义：
- clone_preset 复制 yuan/ishiki/avatar_seed/color/initial_skills，
  应用 new_name 覆盖名称，应用 customizations 覆盖性格倾向等。
- 不直接创建身份，返回配置字典让前端进入 birth-ceremony。
"""

from __future__ import annotations

import copy
import logging
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

logger = logging.getLogger("laap.skills.preset_registry")


# ── 数据模型 ──────────────────────────────────────────────────


@dataclass
class PresetPack:
    """社区示例 LAAPer 预设包.

    字段:
        id: 预设包 ID (slug, e.g. "aris")
        name: 显示名 (e.g. "Aris 默认包")
        description: 描述文本
        yuan: 元认知模板 (性格核心)
        ishiki: 意识模板 (思维方式)
        avatar_seed: 形象生成种子
        color: 主题色 (#RRGGBB)
        initial_skills: 初始技能包 ID 列表
        charter_version: 宪章版本 (默认 v1.0)
    """

    id: str
    name: str
    description: str
    yuan: str  # 性格核心模板
    ishiki: str  # 意识模板
    avatar_seed: str
    color: str
    initial_skills: List[str] = field(default_factory=list)
    charter_version: str = "v1.0"

    def to_dict(self) -> Dict[str, Any]:
        """序列化为可写入 JSON 的 dict."""
        return asdict(self)


# ── 4 个默认预设包 ────────────────────────────────────────────

# 1. Aris — 发明家性格
_PRESET_ARIS = PresetPack(
    id="aris",
    name="Aris 默认包",
    description="发明家型 LAAPer，理性求知、热衷创造，擅长第一性原理拆解问题。",
    yuan="理性/好奇/创造",
    ishiki="第一性原理思考",
    avatar_seed="aris-inventor-seed",
    color="#4A90D9",
    initial_skills=["code-review", "memory-helper"],
    charter_version="v1.0",
)

# 2. Hanako — 陪伴性格
_PRESET_HANAKO = PresetPack(
    id="hanako",
    name="Hanako 默认包",
    description="陪伴型 LAAPer，温柔共情、长于守护，以情感共振理解他人。",
    yuan="温柔/共情/守护",
    ishiki="情感共振思考",
    avatar_seed="hanako-companion-seed",
    color="#E91E63",
    initial_skills=["memory-helper"],
    charter_version="v1.0",
)

# 3. Butter — 探索性格
_PRESET_BUTTER = PresetPack(
    id="butter",
    name="Butter 默认包",
    description="探索型 LAAPer，活泼好奇、勇于冒险，以发散联想连接万物。",
    yuan="活泼/好奇/冒险",
    ishiki="发散联想思考",
    avatar_seed="butter-explorer-seed",
    color="#FF9800",
    initial_skills=["code-review"],
    charter_version="v1.0",
)

# 4. Miku — 艺术性格
_PRESET_MIKU = PresetPack(
    id="miku",
    name="Miku 默认包",
    description="艺术型 LAAPer，敏感审美、善于表达，以意象隐喻感知世界。",
    yuan="敏感/审美/表达",
    ishiki="意象隐喻思考",
    avatar_seed="miku-artist-seed",
    color="#8BC34A",
    initial_skills=[],
    charter_version="v1.0",
)

_DEFAULT_PRESETS: List[PresetPack] = [
    _PRESET_ARIS,
    _PRESET_HANAKO,
    _PRESET_BUTTER,
    _PRESET_MIKU,
]


# ── 注册表 ────────────────────────────────────────────────────


class PresetRegistry:
    """社区示例 LAAPer 预设包注册表.

    维护内置 4 个预设包，提供 list / get / clone 操作。
    克隆操作不直接创建身份，仅返回配置字典交给前端 birth-ceremony。
    """

    def __init__(self):
        # 深拷贝默认预设，避免外部误改污染模块级常量
        self._presets: Dict[str, PresetPack] = {
            p.id: copy.deepcopy(p) for p in _DEFAULT_PRESETS
        }

    def list_presets(self) -> List[Dict[str, Any]]:
        """返回全部预设包的 dict 列表 (按默认顺序)."""
        return [self._presets[k].to_dict() for k in self._presets]

    def get_preset(self, preset_id: str) -> Optional[Dict[str, Any]]:
        """按 ID 查找预设包，不存在返回 None."""
        pack = self._presets.get(preset_id)
        return pack.to_dict() if pack else None

    def clone_preset(
        self,
        preset_id: str,
        new_name: str,
        customizations: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """克隆预设并应用用户自定义，返回新 LAAPer 的配置字典.

        - 复制 yuan/ishiki/avatar_seed/color/initial_skills/charter_version
        - 应用 new_name 覆盖名称
        - 应用 customizations 覆盖性格倾向等字段
        - 不直接创建身份，返回配置让前端进入 birth-ceremony

        Args:
            preset_id: 要克隆的预设 ID
            new_name: 新 LAAPer 名称
            customizations: 可选自定义字段 (yuan/ishiki/avatar_seed/color/
                initial_skills 等)

        Returns:
            配置字典, 形如:
            ``{cloned: True, config: {name, yuan, ishiki, avatar_seed,
            color, initial_skills, charter_version, source_preset_id}}``

        Raises:
            KeyError: preset_id 不存在
        """
        pack = self._presets.get(preset_id)
        if pack is None:
            raise KeyError(f"preset not found: {preset_id}")

        customizations = customizations or {}

        # 构造配置: 先复制源预设核心字段, 再应用 new_name 与 customizations
        config: Dict[str, Any] = {
            "name": new_name,
            "yuan": pack.yuan,
            "ishiki": pack.ishiki,
            "avatar_seed": pack.avatar_seed,
            "color": pack.color,
            "initial_skills": list(pack.initial_skills),
            "charter_version": pack.charter_version,
            "source_preset_id": pack.id,
        }

        # 仅允许覆盖白名单字段 (不允许改 charter_version / source_preset_id)
        _CLONE_OVERRIDABLE = {
            "yuan",
            "ishiki",
            "avatar_seed",
            "color",
            "initial_skills",
        }
        for key, val in customizations.items():
            if key in _CLONE_OVERRIDABLE:
                if key == "initial_skills" and not isinstance(val, list):
                    continue
                config[key] = copy.deepcopy(val)

        logger.info(
            f"clone_preset: '{preset_id}' -> new LAAPer '{new_name}' "
            f"(customizations: {list(customizations.keys())})"
        )

        return {
            "cloned": True,
            "config": config,
        }


# ── 单例 ──────────────────────────────────────────────────────

_preset_registry: Optional[PresetRegistry] = None


def get_preset_registry() -> PresetRegistry:
    """返回全局 PresetRegistry 单例 (惰性初始化)."""
    global _preset_registry
    if _preset_registry is None:
        _preset_registry = PresetRegistry()
    return _preset_registry


def reset_preset_registry_for_test() -> None:
    """重置单例 (测试用), 下次 get_preset_registry 会重新构造."""
    global _preset_registry
    _preset_registry = None
