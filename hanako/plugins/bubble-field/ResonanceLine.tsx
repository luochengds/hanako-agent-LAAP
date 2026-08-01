/**
 * ResonanceLine — 两个 Bubble 之间的共振连线
 *
 * strength > 0.7 实线（强共振），否则虚线（弱关联）。
 * SVG 渲染，线条颜色随强度从冷色到暖色过渡。
 */

import { memo } from "react";
import type { ResonanceLineProps } from "./types";

function ResonanceLineComponent({
  from,
  to,
  strength,
  color,
}: ResonanceLineProps) {
  // strength > 0.7 → 实线；否则虚线
  const isSolid = strength > 0.7;
  const dashArray = isSolid ? "none" : "6 4";

  // 默认颜色：高强度暖色（金色），低强度冷色（蓝紫）
  const lineColor =
    color ??
    (strength > 0.7 ? "#ffc857" : strength > 0.4 ? "#7eb3ff" : "#4a5a7a");

  const lineWidth = 1 + strength * 2; // 1-3px
  const opacity = 0.3 + strength * 0.5; // 0.3-0.8

  return (
    <line
      className="bf-resonance-line"
      data-strength={strength.toFixed(2)}
      data-style={isSolid ? "solid" : "dashed"}
      x1={from.x}
      y1={from.y}
      x2={to.x}
      y2={to.y}
      stroke={lineColor}
      strokeWidth={lineWidth}
      strokeOpacity={opacity}
      strokeDasharray={dashArray}
      strokeLinecap="round"
    />
  );
}

export const ResonanceLine = memo(ResonanceLineComponent);
