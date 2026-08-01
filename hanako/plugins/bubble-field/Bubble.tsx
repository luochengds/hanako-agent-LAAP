/**
 * Bubble — 单个 LAAPer 泡泡组件
 *
 * Mineradio 风格：径向渐变 + box-shadow 发光 + 光晕脉冲动画。
 * 状态编码（无需文字辅助）：
 * - color    → 身份主色
 * - brightness → 在线/休眠（透明度 + 发光强度）
 * - size     → 认知能量（活跃度 + 共鸣强度）
 * - pulse    → 思考中（光晕脉冲动画）
 * - label    → 名称 + 状态徽章（悬停时显示）
 */

import { memo, useCallback } from "react";
import type { BubbleProps } from "./types";

function BubbleComponent({
  color,
  brightness,
  size,
  pulse,
  label,
  position,
  onClick,
  onDragStart,
  onMouseEnter,
  onMouseLeave,
}: BubbleProps) {
  const handleClick = useCallback(
    (e: React.MouseEvent) => {
      // 拖拽产生的 click 忽略（由 BubbleField 通过 stopPropagation 处理）
      e.stopPropagation();
      onClick?.();
    },
    [onClick],
  );

  const handleMouseDown = useCallback(
    (e: React.MouseEvent) => {
      onDragStart?.(e);
    },
    [onDragStart],
  );

  // 径向渐变：中心亮色 → 边缘主色
  const opacity = Math.max(0.2, brightness);
  const glowStrength = brightness * (pulse ? 1.5 : 1.0);
  const glowRadius = Math.round(size * 0.6 * glowStrength);

  const style: React.CSSProperties = {
    position: "absolute",
    left: `${position.x}px`,
    top: `${position.y}px`,
    width: `${size}px`,
    height: `${size}px`,
    marginLeft: `-${size / 2}px`,
    marginTop: `-${size / 2}px`,
    opacity,
    background: `radial-gradient(circle at 35% 35%, ${color} 0%, ${color} 40%, rgba(0,0,0,0.4) 100%)`,
    boxShadow: `0 0 ${glowRadius}px ${color}, 0 0 ${glowRadius * 2}px ${color}66`,
    animation: pulse ? "bf-pulse 1.5s ease-in-out infinite" : "none",
    cursor: "pointer",
  };

  return (
    <div
      className="bf-bubble"
      data-pulse={pulse ? "true" : "false"}
      data-brightness={brightness.toFixed(2)}
      style={style}
      onClick={handleClick}
      onMouseDown={handleMouseDown}
      onMouseEnter={onMouseEnter}
      onMouseLeave={onMouseLeave}
    >
      <span className="bf-bubble-label">{label}</span>
    </div>
  );
}

export const Bubble = memo(BubbleComponent);
