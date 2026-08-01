/**
 * MessageBubble — 单条 1v1 消息气泡 + 认知足迹展开
 *
 * - self/peer 方向区分（右/左对齐 + 不同配色）
 * - 验签状态徽章（verified/fail）
 * - 点击"认知足迹"展开 causal/memory/truth 三栏（数据由 UI 本地填充或 stub）
 */

import { useState } from "react";
import type { ChatMessage } from "./types";

export interface MessageBubbleProps {
  message: ChatMessage;
  /** 当前用户公钥，用于判断 self/peer 方向 */
  selfPublicKey: string;
}

export function MessageBubble({ message, selfPublicKey }: MessageBubbleProps) {
  const isSelf = message.sender_public_key === selfPublicKey;
  const [expanded, setExpanded] = useState(false);
  const cog = message.cognition;

  return (
    <div className={`laaper-msg ${isSelf ? "laaper-msg-self" : "laaper-msg-peer"}`}>
      <div>{message.content}</div>
      <div className={`laaper-msg-verified ${message.verified ? "" : "laaper-msg-verified-fail"}`}>
        {message.verified ? "[verified]" : "[signature invalid]"}
        {"  ·  "}
        {new Date(message.timestamp * 1000).toLocaleTimeString()}
      </div>
      {cog && (
        <div
          className="laaper-msg-toggle"
          role="button"
          tabIndex={0}
          onClick={() => setExpanded((v) => !v)}
          onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") setExpanded((v) => !v); }}
        >
          {expanded ? "▾ 收起认知足迹" : "▸ 展开认知足迹"}
        </div>
      )}
      {expanded && cog && (
        <div className="laaper-msg-cognition">
          <div className="laaper-cog-block laaper-cog-causal">
            <span className="laaper-cog-label">Causal</span>
            {(cog.causal || []).map((c, i) => (
              <span key={i} className="laaper-cog-value">{c}</span>
            ))}
            {(!cog.causal || cog.causal.length === 0) && (
              <span className="laaper-cog-value" style={{ opacity: 0.4 }}>-</span>
            )}
          </div>
          <div className="laaper-cog-block laaper-cog-memory">
            <span className="laaper-cog-label">Memory</span>
            {(cog.memory || []).map((m, i) => (
              <span key={i} className="laaper-cog-value">{m}</span>
            ))}
            {(!cog.memory || cog.memory.length === 0) && (
              <span className="laaper-cog-value" style={{ opacity: 0.4 }}>-</span>
            )}
          </div>
          <div className="laaper-cog-block laaper-cog-truth">
            <span className="laaper-cog-label">Truth</span>
            <span className="laaper-cog-value">{cog.truth || "-"}</span>
          </div>
        </div>
      )}
    </div>
  );
}
