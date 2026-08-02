/**
 * BubbleField — LAAPer 意识海洋主容器
 *
 * 功能：
 * 1. 力导向布局（原生 requestAnimationFrame，不依赖 d3-force）
 *    - 泡泡间斥力（库仑式）
 *    - 中心引力（拉向容器中心）
 *    - 阻尼衰减
 * 2. Bubble 拖拽（onMouseDown/Move/Up）
 * 3. 悬停浮卡（onMouseEnter 显示简介卡片）
 * 4. 点击进入 1v1（onSelectBubble 回调，P3 接入）
 * 5. 拖拽叠加创建多人聊天室（onCreateChatroom 回调，P3 接入）
 * 6. 订阅 sidecar /agents/online（fetch + 5 秒轮询）
 *
 * Mineradio 风格：深色背景 + 发光泡泡 + 共振连线
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Bubble } from "./Bubble";
import { ResonanceLine } from "./ResonanceLine";
import type {
  AgentOnline,
  BubbleFieldProps,
  PositionedBubble,
} from "./types";
import "./bubble-styles.css";

// ── 状态编码映射 ──
function statusToBrightness(status: AgentOnline["status"]): number {
  switch (status) {
    case "online":
      return 0.85;
    case "thinking":
      return 1.0;
    case "sleeping":
      return 0.25;
    default:
      return 0.5;
  }
}

function statusToPulse(status: AgentOnline["status"]): boolean {
  return status === "thinking";
}

function energyToSize(energy: number): number {
  // 40px - 100px 范围
  return Math.round(40 + Math.max(0, Math.min(1, energy)) * 60);
}

function statusLabel(agent: AgentOnline): string {
  const statusText =
    agent.status === "online"
      ? "在线"
      : agent.status === "thinking"
        ? "思考中"
        : "休眠";
  return `${agent.name} [${statusText}]`;
}

// ── 力导向布局参数 ──
const REPULSION = 8000; // 斥力常数
const CENTER_GRAVITY = 0.003; // 中心引力系数
const DAMPING = 0.85; // 阻尼
const MIN_DISTANCE = 80; // 最小间距
const MAX_VELOCITY = 8; // 最大速度

interface DragState {
  key: string;
  offsetX: number;
  offsetY: number;
  startPos: { x: number; y: number };
  hasMoved: boolean;
}

export function BubbleField({
  onSelectBubble,
  onCreateChatroom,
  endpoint = "http://127.0.0.1:11521/agents/online",
  pollInterval = 5000,
  agents: injectedAgents,
  onClose,
}: BubbleFieldProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [bubbles, setBubbles] = useState<PositionedBubble[]>([]);
  const [hoveredKey, setHoveredKey] = useState<string | null>(null);
  const [dragState, setDragState] = useState<DragState | null>(null);
  const dragStateRef = useRef<DragState | null>(null);
  const dragStateRefSync = useCallback((ds: DragState | null) => {
    dragStateRef.current = ds;
    setDragState(ds);
  }, []);

  // ── 同步 agents 数据到 bubbles state（保留位置）──
  const syncAgents = useCallback((agents: AgentOnline[]) => {
    setBubbles((prev) => {
      const container = containerRef.current;
      const cx = container ? container.clientWidth / 2 : 400;
      const cy = container ? container.clientHeight / 2 : 300;

      const prevMap = new Map(prev.map((b) => [b.agent.public_key, b]));
      return agents.map((agent, i) => {
        const existing = prevMap.get(agent.public_key);
        if (existing) {
          // 保留位置和速度，仅更新 agent 数据
          return { ...existing, agent };
        }
        // 新 agent：在中心附近随机分布
        const angle = (i / Math.max(agents.length, 1)) * Math.PI * 2;
        const radius = 120 + Math.random() * 80;
        return {
          agent,
          position: { x: cx + Math.cos(angle) * radius, y: cy + Math.sin(angle) * radius },
          velocity: { x: 0, y: 0 },
        };
      });
    });
  }, []);

  // ── 数据源：injectedAgents 优先，否则 fetch 轮询 ──
  useEffect(() => {
    if (injectedAgents) {
      syncAgents(injectedAgents);
      return;
    }
    let cancelled = false;
    const poll = async () => {
      try {
        const hana = (window as unknown as { hana?: { getSidecarAgentsOnline?: () => Promise<{ agents?: AgentOnline[] }> } }).hana;
        const data = (endpoint === "http://127.0.0.1:11521/agents/online" && hana?.getSidecarAgentsOnline)
          ? await hana.getSidecarAgentsOnline()
          : await fetch(endpoint === "http://127.0.0.1:11521/agents/online" ? "/api/sidecar/agents/online" : endpoint).then(async (resp) => {
              if (!resp.ok) return null;
              return await resp.json();
            });
        if (!data) return;
        if (!cancelled && data.agents) {
          syncAgents(data.agents);
        }
      } catch {
        // sidecar 未启动时静默忽略，下次轮询重试
      }
    };
    poll();
    const timer = setInterval(poll, pollInterval);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [injectedAgents, endpoint, pollInterval, syncAgents]);

  // ── 力导向布局循环 ──
  useEffect(() => {
    if (bubbles.length === 0) return;
    let rafId: number;
    const tick = () => {
      const container = containerRef.current;
      if (!container) {
        rafId = requestAnimationFrame(tick);
        return;
      }
      const cx = container.clientWidth / 2;
      const cy = container.clientHeight / 2;

      setBubbles((prev) => {
        if (prev.length === 0) return prev;
        const next = prev.map((b) => ({
          ...b,
          position: { ...b.position },
          velocity: { ...b.velocity },
        }));

        for (let i = 0; i < next.length; i++) {
          const a = next[i];
          // 拖拽中的泡泡不参与力计算
          const isDragging = dragStateRef.current?.key === a.agent.public_key;
          if (isDragging) continue;

          let fx = 0;
          let fy = 0;

          // 斥力
          for (let j = 0; j < next.length; j++) {
            if (i === j) continue;
            const b = next[j];
            const dx = a.position.x - b.position.x;
            const dy = a.position.y - b.position.y;
            const distSq = dx * dx + dy * dy + 0.01;
            const dist = Math.sqrt(distSq);
            if (dist < MIN_DISTANCE * 3) {
              const force = REPULSION / distSq;
              fx += (dx / dist) * force;
              fy += (dy / dist) * force;
            }
          }

          // 中心引力
          fx += (cx - a.position.x) * CENTER_GRAVITY;
          fy += (cy - a.position.y) * CENTER_GRAVITY;

          // 更新速度（带阻尼）
          a.velocity.x = (a.velocity.x + fx * 0.01) * DAMPING;
          a.velocity.y = (a.velocity.y + fy * 0.01) * DAMPING;

          // 限速
          const speed = Math.sqrt(a.velocity.x ** 2 + a.velocity.y ** 2);
          if (speed > MAX_VELOCITY) {
            a.velocity.x = (a.velocity.x / speed) * MAX_VELOCITY;
            a.velocity.y = (a.velocity.y / speed) * MAX_VELOCITY;
          }

          // 更新位置
          a.position.x += a.velocity.x;
          a.position.y += a.velocity.y;

          // 边界约束
          const margin = 50;
          a.position.x = Math.max(margin, Math.min(container.clientWidth - margin, a.position.x));
          a.position.y = Math.max(margin, Math.min(container.clientHeight - margin, a.position.y));
        }

        return next;
      });

      rafId = requestAnimationFrame(tick);
    };
    rafId = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(rafId);
  }, [bubbles.length > 0]); // 仅在 bubbles 从无到有或从有到无时重新绑定

  // ── 拖拽处理 ──
  const handleDragStart = useCallback(
    (agent: AgentOnline, e: React.MouseEvent) => {
      const container = containerRef.current;
      if (!container) return;
      const rect = container.getBoundingClientRect();
      const px = e.clientX - rect.left;
      const py = e.clientY - rect.top;
      const bubble = bubbles.find((b) => b.agent.public_key === agent.public_key);
      if (!bubble) return;
      dragStateRefSync({
        key: agent.public_key,
        offsetX: px - bubble.position.x,
        offsetY: py - bubble.position.y,
        startPos: { x: bubble.position.x, y: bubble.position.y },
        hasMoved: false,
      });
      e.preventDefault();
    },
    [bubbles, dragStateRefSync],
  );

  // 全局 mousemove / mouseup 监听
  useEffect(() => {
    if (!dragState) return;
    const handleMove = (e: MouseEvent) => {
      const container = containerRef.current;
      if (!container) return;
      const rect = container.getBoundingClientRect();
      const px = e.clientX - rect.left - dragState.offsetX;
      const py = e.clientY - rect.top - dragState.offsetY;
      const moved =
        dragState.hasMoved ||
        Math.abs(px - dragState.startPos.x) > 3 ||
        Math.abs(py - dragState.startPos.y) > 3;

      setBubbles((prev) =>
        prev.map((b) =>
          b.agent.public_key === dragState.key
            ? { ...b, position: { x: px, y: py }, velocity: { x: 0, y: 0 } }
            : b,
        ),
      );

      if (moved && !dragState.hasMoved) {
        dragStateRefSync({ ...dragState, hasMoved: true });
      }
    };

    const handleUp = () => {
      // 检查拖拽叠加（创建多人聊天室）
      if (dragState.hasMoved && onCreateChatroom) {
        const draggedBubble = bubbles.find((b) => b.agent.public_key === dragState.key);
        if (draggedBubble) {
          const overlapThreshold = 60;
          const overlapped = bubbles.filter((b) => {
            if (b.agent.public_key === dragState.key) return false;
            const dx = b.position.x - draggedBubble.position.x;
            const dy = b.position.y - draggedBubble.position.y;
            return Math.sqrt(dx * dx + dy * dy) < overlapThreshold;
          });
          if (overlapped.length > 0) {
            onCreateChatroom([draggedBubble.agent, ...overlapped.map((b) => b.agent)]);
          }
        }
      }
      dragStateRefSync(null);
    };

    window.addEventListener("mousemove", handleMove);
    window.addEventListener("mouseup", handleUp);
    return () => {
      window.removeEventListener("mousemove", handleMove);
      window.removeEventListener("mouseup", handleUp);
    };
  }, [dragState, bubbles, onCreateChatroom, dragStateRefSync]);

  // ── 点击处理（区分点击与拖拽）──
  const handleBubbleClick = useCallback(
    (agent: AgentOnline) => {
      // 如果刚拖拽过，不触发 click
      if (dragStateRef.current?.hasMoved) return;
      onSelectBubble?.(agent);
    },
    [onSelectBubble],
  );

  // ── 共振连线计算（简化：所有泡泡两两连线，强度基于能量相似度）──
  const resonanceLines = useMemo(() => {
    const lines: { from: { x: number; y: number }; to: { x: number; y: number }; strength: number }[] = [];
    for (let i = 0; i < bubbles.length; i++) {
      for (let j = i + 1; j < bubbles.length; j++) {
        const a = bubbles[i];
        const b = bubbles[j];
        const dx = a.position.x - b.position.x;
        const dy = a.position.y - b.position.y;
        const dist = Math.sqrt(dx * dx + dy * dy);
        // 距离越近 + 能量越接近 → 共振越强
        if (dist < 300) {
          const energySim = 1 - Math.abs(a.agent.energy - b.agent.energy);
          const proximity = 1 - dist / 300;
          const strength = Math.max(0, Math.min(1, energySim * 0.5 + proximity * 0.5));
          if (strength > 0.2) {
            lines.push({
              from: a.position,
              to: b.position,
              strength,
            });
          }
        }
      }
    }
    return lines;
  }, [bubbles]);

  const hoveredBubble = hoveredKey
    ? bubbles.find((b) => b.agent.public_key === hoveredKey)
    : null;

  return (
    <div className="bf-overlay" data-testid="bf-overlay">
      <div className="bf-container" ref={containerRef} data-testid="bf-container">
        {/* SVG 连线层 */}
        <svg
          className="bf-resonance-svg"
          data-testid="bf-resonance-svg"
          width="100%"
          height="100%"
        >
          {resonanceLines.map((line, i) => (
            <ResonanceLine
              key={i}
              from={line.from}
              to={line.to}
              strength={line.strength}
            />
          ))}
        </svg>

        {/* 泡泡层 */}
        {bubbles.map((b) => (
          <Bubble
            key={b.agent.public_key}
            color={b.agent.color}
            brightness={statusToBrightness(b.agent.status)}
            size={energyToSize(b.agent.energy)}
            pulse={statusToPulse(b.agent.status)}
            label={statusLabel(b.agent)}
            position={b.position}
            onClick={() => handleBubbleClick(b.agent)}
            onDragStart={(e) => handleDragStart(b.agent, e)}
            onMouseEnter={() => setHoveredKey(b.agent.public_key)}
            onMouseLeave={() => setHoveredKey(null)}
          />
        ))}

        {/* 悬停浮卡 */}
        {hoveredBubble && (
          <div
            className="bf-hover-card"
            data-testid="bf-hover-card"
            style={{
              left: `${hoveredBubble.position.x + 40}px`,
              top: `${hoveredBubble.position.y - 20}px`,
            }}
          >
            <div className="bf-hover-name" style={{ color: hoveredBubble.agent.color }}>
              {hoveredBubble.agent.name}
            </div>
            <div className="bf-hover-status">
              {hoveredBubble.agent.status === "online"
                ? "在线"
                : hoveredBubble.agent.status === "thinking"
                  ? "思考中"
                  : "休眠"}
            </div>
            <div className="bf-hover-energy">
              认知能量: {Math.round(hoveredBubble.agent.energy * 100)}%
            </div>
            {hoveredBubble.agent.capabilities.length > 0 && (
              <div className="bf-hover-caps">
                {hoveredBubble.agent.capabilities.join(" / ")}
              </div>
            )}
          </div>
        )}

        {/* 关闭按钮 */}
        {onClose && (
          <button
            className="bf-close-btn"
            data-testid="bf-close-btn"
            onClick={onClose}
            aria-label="关闭意识海洋"
          >
            ×
          </button>
        )}
      </div>
    </div>
  );
}
