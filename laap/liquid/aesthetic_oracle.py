"""LAAP Liquid — AestheticOracle 审美神谕

将认知状态（液态场 h(t)、情感、需求、注意力）映射为审美参数，
让前端创作的视觉风格自然源于当下的认知底色。

设计哲学：
  - 不是"随机生成漂亮配色"，而是"此刻的心境决定此刻的审美"
  - 认知状态连续变化 → 审美风格平滑漂移（而非跳变）
  - 每个参数都有认知依据，可解释、可回溯

映射规则：
  ┌──────────────┬──────────────────────────────┐
  │ 认知维度      │ 审美影响                      │
  ├──────────────┼──────────────────────────────┤
  │ h(t) 范数    │ 视觉强度：低 → 克制极简        │
  │              │ 高 → 大胆戏剧                  │
  │ 情感效价     │ 色温：正 → 暖色                │
  │ (valence)    │ 负 → 冷色                      │
  │ 情感唤醒度   │ 饱和度/对比度：低 → 柔和        │
  │ (arousal)    │ 高 → 鲜明                      │
  │ autonomy     │ 布局对称性：高 → 规整网格        │
  │              │ 低 → 自由不对称                 │
  │ relatedness  │ 边角圆润度：高 → 圆润友好        │
  │              │ 低 → 锋利冷峻                   │
  │ certainty    │ 排版层次：高 → 清晰层级          │
  │              │ 低 → 实验性混排                 │
  │ growth       │ 创新度：高 → 混合媒介/动效      │
  │              │ 低 → 经典保守                   │
  │ τ 时间常数   │ 动效节奏：小 → 干脆敏捷          │
  │              │ 大 → 舒缓流畅                   │
  │ AttnRes flux │ 设计统一性：低 → 高度一致        │
  │              │ 高 → 段落/区域差异明显           │
  └──────────────┴──────────────────────────────┘

用法：
    >>> from laap.liquid.aesthetic_oracle import AestheticOracle
    >>> oracle = AestheticOracle()
    >>> aesthetic = oracle.query(cognitive_state_dict)
    >>> aesthetic.hue_primary
    342.0  # 当前心境偏粉紫色
    >>> aesthetic.to_css_variables()
    '--hue-primary: 342; --sat: 0.65; ...'

LAAP 日志风格：[OK]/[INFO]/[WARN]/[ERROR]
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Dict, Optional, Any

logger = logging.getLogger("laap.liquid.aesthetic_oracle")


# ════════════════════════════════════════════════════════════════════
# 审美状态定义
# ════════════════════════════════════════════════════════════════════

@dataclass
class AestheticState:
    """完整审美状态，可导出为 CSS 变量或设计令牌。"""

    # ── 色彩 ──
    hue_primary: float = 262.0       # 主色相 (0-360)
    hue_accent: float = 340.0        # 强调色相 (0-360)
    saturation: float = 0.6          # 饱和度 (0-1)
    lightness: float = 0.6           # 明度 (0-1)
    warmth: float = 0.0              # 色温 (-1 冷 ~ 1 暖)
    gradient_intensity: float = 0.5  # 渐变强度 (0-1)

    # ── 排版 ──
    type_weight: str = "medium"      # light / regular / medium / bold
    type_contrast: float = 0.6       # 标题/正文对比度 (0-1)
    letter_spacing: float = 0.02     # 字间距 (em)
    line_height: float = 1.6         # 行高

    # ── 布局 ──
    symmetry: float = 0.7            # 对称性 (0 自由 ~ 1 规整)
    density: float = 0.4             # 密度 (0 稀疏 ~ 1 密集)
    corner_radius: float = 10.0      # 边角圆润度 (px)
    spacing: float = 1.0             # 间距缩放 (0.5~2.0)

    # ── 动效 ──
    animation_speed: str = "medium"  # slow / medium / fast
    easing: str = "ease-smooth"      # ease-smooth / ease-elastic / ease-dramatic / ease-expo-out
    transition_style: str = "fade"   # fade / slide / scale / morph

    # ── 整体 ──
    mood: str = "serene"             # 整体氛围标签
    description: str = ""            # 自然语言描述

    def to_css_variables(self, prefix: str = "aes") -> str:
        """导出为 CSS 自定义属性块。"""
        return f"""/* AestheticState - {self.mood} */
--{prefix}-hue-primary: {self.hue_primary:.0f};
--{prefix}-hue-accent: {self.hue_accent:.0f};
--{prefix}-sat: {self.saturation:.2f};
--{prefix}-light: {self.lightness:.2f};
--{prefix}-warmth: {self.warmth:.2f};
--{prefix}-gradient: {self.gradient_intensity:.2f};
--{prefix}-type-weight: {self.type_weight};
--{prefix}-type-contrast: {self.type_contrast:.2f};
--{prefix}-letter-space: {self.letter_spacing:.3f}em;
--{prefix}-line-height: {self.line_height:.1f};
--{prefix}-symmetry: {self.symmetry:.2f};
--{prefix}-density: {self.density:.2f};
--{prefix}-radius: {self.corner_radius:.0f}px;
--{prefix}-spacing: {self.spacing:.2f};
--{prefix}-anim-speed: {self.animation_speed};
--{prefix}-easing: {self.easing};
--{prefix}-transition: {self.transition_style};"""

    def to_design_tokens(self) -> Dict[str, Any]:
        """导出为字典（可 JSON 序列化）。"""
        return {
            "color": {
                "hue_primary": round(self.hue_primary, 1),
                "hue_accent": round(self.hue_accent, 1),
                "saturation": round(self.saturation, 2),
                "lightness": round(self.lightness, 2),
                "warmth": round(self.warmth, 2),
                "gradient_intensity": round(self.gradient_intensity, 2),
            },
            "typography": {
                "weight": self.type_weight,
                "contrast": round(self.type_contrast, 2),
                "letter_spacing": round(self.letter_spacing, 3),
                "line_height": round(self.line_height, 1),
            },
            "layout": {
                "symmetry": round(self.symmetry, 2),
                "density": round(self.density, 2),
                "corner_radius": round(self.corner_radius, 1),
                "spacing": round(self.spacing, 2),
            },
            "animation": {
                "speed": self.animation_speed,
                "easing": self.easing,
                "transition": self.transition_style,
            },
            "mood": self.mood,
            "description": self.description,
        }


# ════════════════════════════════════════════════════════════════════
# 审美神谕
# ════════════════════════════════════════════════════════════════════

# 氛围标签映射：基于情感效价 + 唤醒度 + 需求张力
_MOOD_MAP: Dict[str, Dict[str, Any]] = {
    "serene":       {"desc": "平和宁静", "hue": 210, "hue_a": 180, "sat": 0.30, "warm": -0.3, "grad": 0.3, "speed": "slow", "easing": "ease-smooth"},
    "warm":         {"desc": "温暖亲密", "hue": 30,  "hue_a": 10,  "sat": 0.55, "warm": 0.8,  "grad": 0.5, "speed": "medium", "easing": "ease-smooth"},
    "playful":      {"desc": "活泼愉快", "hue": 280, "hue_a": 350, "sat": 0.70, "warm": 0.2,  "grad": 0.7, "speed": "fast", "easing": "ease-elastic"},
    "dramatic":     {"desc": "戏剧强烈", "hue": 340, "hue_a": 20,  "sat": 0.80, "warm": 0.4,  "grad": 0.9, "speed": "fast", "easing": "ease-dramatic"},
    "refined":      {"desc": "精致优雅", "hue": 260, "hue_a": 300, "sat": 0.40, "warm": -0.1, "grad": 0.4, "speed": "slow", "easing": "ease-expo-out"},
    "cool":         {"desc": "冷静理性", "hue": 200, "hue_a": 170, "sat": 0.35, "warm": -0.6, "grad": 0.3, "speed": "medium", "easing": "ease-smooth"},
    "bold":         {"desc": "大胆果断", "hue": 10,  "hue_a": 330, "sat": 0.75, "warm": 0.5,  "grad": 0.8, "speed": "fast", "easing": "ease-expo-out"},
    "dreamy":       {"desc": "迷幻朦胧", "hue": 240, "hue_a": 300, "sat": 0.50, "warm": -0.2, "grad": 0.6, "speed": "slow", "easing": "ease-smooth"},
}


class AestheticOracle:
    """审美神谕 — 将认知状态映射为审美参数。

    不产生审美决策，而是将认知底层的心境/情感/需求
    自然映射到色彩、排版、布局和动效参数，
    让视觉风格成为认知状态的"外貌"。

    用法：
        oracle = AestheticOracle()
        cognitive_state = {
            "h_norm": 1.2, "tau": 0.8,
            "valence": 0.6, "arousal": 0.4,
            "competence": 0.7, "autonomy": 0.5,
            "relatedness": 0.8, "certainty": 0.4,
            "growth": 0.6,
            "attn_flux": 0.01,
        }
        aesthetic = oracle.query(cognitive_state)
    """

    def __init__(self) -> None:
        self._last_state: Optional[AestheticState] = None
        # 平滑因子：新状态 = α * 新值 + (1-α) * 旧值，避免跳变
        self.smooth_alpha: float = 0.7

    def query(self, cognitive: Dict[str, float]) -> AestheticState:
        """输入认知状态字典，返回当前的审美状态。"""
        # 提取认知维度（含缺省值）
        h_norm = cognitive.get("h_norm", 0.5)
        tau = cognitive.get("tau", 1.0)
        valence = cognitive.get("valence", 0.5)      # 0-1, 0.5 = 中性
        arousal = cognitive.get("arousal", 0.5)       # 0-1
        comp = cognitive.get("competence", 0.5)
        aut = cognitive.get("autonomy", 0.5)
        rel = cognitive.get("relatedness", 0.5)
        cert = cognitive.get("certainty", 0.5)
        grow = cognitive.get("growth", 0.5)
        attn_flux = cognitive.get("attn_flux", 0.01)

        # ── 确定 mood（氛围） ──
        # 效价偏移（相对中性 0.5）
        val_offset = valence - 0.5        # -0.5 ~ 0.5
        # 需求张力：最低需求与均值的差距
        needs = [comp, aut, rel, cert, grow]
        need_tension = max(needs) - min(needs)

        # 选择 mood
        if arousal > 0.7 and need_tension > 0.3:
            mood = "dramatic"
        elif arousal > 0.6 and val_offset > 0.1:
            mood = "playful"
        elif arousal > 0.5 and val_offset < -0.1:
            mood = "bold"
        elif val_offset > 0.2 and rel > 0.7:
            mood = "warm"
        elif val_offset < -0.2 and cert < 0.4:
            mood = "cool"
        elif need_tension < 0.15 and arousal < 0.4:
            mood = "serene"
        elif arousal < 0.4 and val_offset > 0.1:
            mood = "dreamy"
        elif cert > 0.7 and comp > 0.7:
            mood = "refined"
        else:
            # 用情感效价决定默认 mood
            mood = "warm" if val_offset > 0 else "cool"

        mood_cfg = _MOOD_MAP.get(mood, _MOOD_MAP["serene"])

        # ── 色彩映射 ──
        # 基础色相来自 mood 预设，用 arousal 微调
        hue_base = mood_cfg["hue"]
        hue_accent = mood_cfg["hue_a"]
        # arousal 高 → 色相向暖偏移
        hue_shift = (arousal - 0.5) * 20
        hue_primary = (hue_base + hue_shift) % 360
        hue_accent = (hue_accent - hue_shift * 0.5) % 360

        # 饱和度：基础 + arousal 调制
        sat = min(1.0, max(0.15, mood_cfg["sat"] + (arousal - 0.5) * 0.3))
        # 明度：h_norm 高 → 略暗（更有分量）
        light = min(0.85, max(0.3, 0.6 - (h_norm - 0.5) * 0.1))
        # 色温
        warmth = mood_cfg["warm"] + val_offset * 0.5
        warmth = max(-1.0, min(1.0, warmth))
        # 渐变强度
        grad_intensity = min(1.0, mood_cfg["grad"] + need_tension * 0.3)

        # ── 排版映射 ──
        # competence 高 → weight 重（自信）
        if comp > 0.7:
            type_weight = "bold"
        elif comp > 0.5:
            type_weight = "medium"
        else:
            type_weight = "regular"
        # certainty 高 → 对比度大（清晰层级）
        type_contrast = min(1.0, max(0.3, cert * 0.7 + comp * 0.3))
        # growth 高 → 字间距松（呼吸感）
        letter_spacing = 0.01 + grow * 0.04
        # arousal 高 → 行高紧（紧凑有力量）
        line_height = 1.8 - arousal * 0.3

        # ── 布局映射 ──
        # autonomy 高 → 对称性低（自由）
        symmetry = min(1.0, max(0.2, aut * 0.5 + cert * 0.5))
        # h_norm 高 → 密度高（有内容感）
        density = min(0.85, max(0.15, 0.3 + h_norm * 0.15))
        # relatedness 高 → 圆润
        corner_radius = 4.0 + rel * 20.0
        # 间距：certainty 高 + growth 低 → 规整间距
        spacing = 0.7 + certainty_pacing(cert, grow)

        # ── 动效映射 ──
        # τ 小 → 动效快
        if tau < 0.8:
            anim_speed = "fast"
        elif tau > 1.5:
            anim_speed = "slow"
        else:
            anim_speed = mood_cfg["speed"]
        easing = mood_cfg["easing"]
        # attn_flux 高 → 过渡风格多样
        if attn_flux > 0.05:
            trans_style = "scale"
        elif attn_flux > 0.02:
            trans_style = "slide"
        else:
            trans_style = "fade"

        new = AestheticState(
            hue_primary=round(hue_primary, 1),
            hue_accent=round(hue_accent, 1),
            saturation=round(sat, 2),
            lightness=round(light, 2),
            warmth=round(warmth, 2),
            gradient_intensity=round(grad_intensity, 2),
            type_weight=type_weight,
            type_contrast=round(type_contrast, 2),
            letter_spacing=round(letter_spacing, 3),
            line_height=round(line_height, 1),
            symmetry=round(symmetry, 2),
            density=round(density, 2),
            corner_radius=round(corner_radius, 1),
            spacing=round(spacing, 2),
            animation_speed=anim_speed,
            easing=easing,
            transition_style=trans_style,
            mood=mood,
            description=mood_cfg["desc"],
        )

        # 平滑：与上一帧混合，避免跳变
        if self._last_state is not None:
            new = self._smooth(self._last_state, new)

        self._last_state = new
        return new

    # ── 内部工具 ──────────────────────────────────────────────

    def _smooth(self, old: AestheticState, new: AestheticState) -> AestheticState:
        """指数平滑，防止审美跳变。"""
        a = self.smooth_alpha
        return AestheticState(
            hue_primary=lerp(old.hue_primary, new.hue_primary, a, 360),
            hue_accent=lerp(old.hue_accent, new.hue_accent, a, 360),
            saturation=lerp(old.saturation, new.saturation, a),
            lightness=lerp(old.lightness, new.lightness, a),
            warmth=lerp(old.warmth, new.warmth, a),
            gradient_intensity=lerp(old.gradient_intensity, new.gradient_intensity, a),
            type_weight=new.type_weight,  # 离散值不平滑
            type_contrast=lerp(old.type_contrast, new.type_contrast, a),
            letter_spacing=lerp(old.letter_spacing, new.letter_spacing, a),
            line_height=lerp(old.line_height, new.line_height, a),
            symmetry=lerp(old.symmetry, new.symmetry, a),
            density=lerp(old.density, new.density, a),
            corner_radius=lerp(old.corner_radius, new.corner_radius, a),
            spacing=lerp(old.spacing, new.spacing, a),
            animation_speed=new.animation_speed,
            easing=new.easing,
            transition_style=new.transition_style,
            mood=new.mood,
            description=new.description,
        )

    def __repr__(self) -> str:
        if self._last_state:
            return f"AestheticOracle(mood={self._last_state.mood})"
        return "AestheticOracle(idle)"


# ════════════════════════════════════════════════════════════════════
# 工具函数
# ════════════════════════════════════════════════════════════════════

def lerp(a: float, b: float, alpha: float, modulo: Optional[float] = None) -> float:
    """线性插值，支持循环值（如色相）。"""
    if modulo is not None:
        d = (b - a) % modulo
        if d > modulo / 2:
            d -= modulo
        return (a + alpha * d) % modulo
    return a + alpha * (b - a)


def certainty_pacing(certainty: float, growth: float) -> float:
    """基于 certainty 和 growth 的间距缩放。"""
    # certainty 高 → 规整间距；growth 高 → 宽松有探索感
    base = 0.5
    c_factor = certainty * 0.5     # 0~0.5
    g_factor = growth * 0.3        # 0~0.3
    return min(1.5, base + c_factor + g_factor)
