/**
 * ViewCard — 单个成员的观点卡片（共识检测结果可视化）
 *
 * 展示：
 * - 成员色点 + 公钥前缀 + 立场徽章（pro/con/neutral）
 * - 观点摘要
 * - 关键词标签（紫色，causal 编码）
 * - truth-grounding 状态徽章（绿/红）
 *
 * Mineradio 风格：三色认知编码（causal 紫 / memory 青 / truth 绿）。
 */

import type { TrioView, TrioMember } from "./types";

export interface ViewCardProps {
  view: TrioView;
  /** 成员信息（用于显示色点与名称），未匹配时降级显示公钥前缀 */
  members: TrioMember[];
}

export function ViewCard({ view, members }: ViewCardProps) {
  const member = members.find((m) => m.public_key === view.public_key);
  const color = member?.color || "#8b93a8";
  const name = member?.name || `${view.public_key.slice(0, 12)}…`;
  const stanceLabel =
    view.stance === "pro" ? "PRO" :
    view.stance === "con" ? "CON" : "NEU";

  const grounding = view.grounding;
  const groundingRejected = grounding?.rejected === true;
  const groundingState = grounding?.state || "n/a";

  return (
    <div className="trio-view-card" role="article" aria-label={`观点 ${name}`}>
      <div className="trio-view-card-header">
        <span
          className="trio-chat-member-dot"
          style={{ background: color, color }}
          aria-hidden="true"
        />
        <span className="trio-view-name" style={{ fontSize: "11px", color: "#c9d1e3" }}>
          {name}
        </span>
        <span className={`trio-view-stance ${view.stance}`} aria-label={`立场 ${stanceLabel}`}>
          {stanceLabel}
        </span>
      </div>

      <div className="trio-view-summary">{view.summary || "(无摘要)"}</div>

      {view.keywords.length > 0 && (
        <div className="trio-view-keywords" aria-label="关键词">
          {view.keywords.map((k, i) => (
            <span key={i} className="trio-view-keyword">{k}</span>
          ))}
        </div>
      )}

      {grounding && (
        <div
          className={`trio-view-grounding ${groundingRejected ? "rejected" : ""}`}
          aria-label="truth-grounding 状态"
        >
          [truth] state={groundingState}
          {typeof grounding.confidence === "number" &&
            ` conf=${grounding.confidence.toFixed(2)}`}
          {groundingRejected && " [rejected]"}
        </div>
      )}
    </div>
  );
}
