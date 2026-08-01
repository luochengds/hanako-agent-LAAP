/**
 * LaaperChatPanel — LAAPer 间 1v1 对话主面板
 *
 * 布局：消息列表 + 输入框 + 认知状态侧栏（tasks SubTask 3.3）。
 *
 * 流程：
 * 1. 挂载时拉取双向历史：POST /chat/history {peer_a: selfPublicKey, peer_b: peer.public_key}
 * 2. 发送：POST /chat/send {sender_public_key, peer_public_key, message} → 追加到本地消息
 * 3. 接收：POST /chat/receive {envelope} → 验签后追加（本任务做端点可用性，P2P 投递由 p2p-relay）
 *
 * 安全：
 * - 私钥永不离开 sidecar（/chat/send 由 sidecar 内部从 _PENDING_PRIVATE_KEYS 取）
 * - 消息经 Ed25519 签名，验签失败显示 [signature invalid]
 *
 * Mineradio 风格：深色背景 + 三色认知编码（causal 紫 / memory 青 / truth 绿）。
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { MessageBubble } from "./MessageBubble";
import { CognitionSidebar } from "./CognitionSidebar";
import type { ChatMessage, ChatPeer, ChatHistoryResult, ChatSendResult } from "./types";
import "./laaper-chat-styles.css";

const DEFAULT_SIDECAR = "http://127.0.0.1:11521";

export interface LaaperChatPanelProps {
  /** 对话 peer（来自 BubbleField onSelectBubble 存入 store） */
  peer: ChatPeer;
  /** 本机 LAAPer 公钥（App.tsx 从 /agents/online 拉取） */
  selfPublicKey: string;
  /** 本机 LAAPer 名（用于 CognitionSidebar 查询认知状态） */
  selfName: string;
  /** sidecar 端点基址 */
  sidecarEndpoint?: string;
  /** 可选：注入 fetch 实现（测试用） */
  fetchImpl?: typeof fetch;
  /** 关闭回调 */
  onClose: () => void;
}

type Status =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "ok"; message: string }
  | { kind: "error"; message: string };

export function LaaperChatPanel({
  peer,
  selfPublicKey,
  selfName,
  sidecarEndpoint = DEFAULT_SIDECAR,
  fetchImpl,
  onClose,
}: LaaperChatPanelProps) {
  const fetchFn = fetchImpl || (typeof window !== "undefined" ? window.fetch.bind(window) : fetch);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [status, setStatus] = useState<Status>({ kind: "idle" });
  const [sending, setSending] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement | null>(null);

  // 拉取历史
  const loadHistory = useCallback(async () => {
    if (!selfPublicKey || !peer.public_key) return;
    setStatus({ kind: "loading" });
    try {
      const r = await fetchFn(`${sidecarEndpoint}/chat/history`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          peer_a: selfPublicKey,
          peer_b: peer.public_key,
          limit: 100,
        }),
      });
      const data: ChatHistoryResult = r.ok ? await r.json() : { count: 0, messages: [], error: `HTTP ${r.status}` };
      if (data.error) {
        setStatus({ kind: "error", message: data.error });
        return;
      }
      setMessages(data.messages || []);
      setStatus({ kind: "ok", message: `loaded ${data.count} messages` });
    } catch (e: any) {
      // sidecar 未启动时静默降级（允许 UI 离线浏览）
      setStatus({ kind: "error", message: `sidecar 不可达: ${e?.message || e}` });
    }
  }, [sidecarEndpoint, selfPublicKey, peer.public_key, fetchFn]);

  useEffect(() => {
    loadHistory();
  }, [loadHistory]);

  // 自动滚到底（jsdom 无 scrollIntoView，需防御）
  useEffect(() => {
    const el = messagesEndRef.current;
    if (el && typeof el.scrollIntoView === "function") {
      el.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages]);

  const handleSend = useCallback(async () => {
    const text = input.trim();
    if (!text || !selfPublicKey || sending) return;
    setSending(true);
    setStatus({ kind: "loading" });
    try {
      const r = await fetchFn(`${sidecarEndpoint}/chat/send`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          sender_public_key: selfPublicKey,
          peer_public_key: peer.public_key,
          message: text,
          agent_name: selfName,
        }),
      });
      const data: ChatSendResult = r.ok ? await r.json() : { sent: false, error: `HTTP ${r.status}` };
      if (!data.sent) {
        setStatus({ kind: "error", message: data.error || "send failed" });
        return;
      }
      // 追加到本地消息（乐观更新）
      const newMsg: ChatMessage = {
        message_id: data.message_id || `local_${Date.now()}`,
        sender_public_key: selfPublicKey,
        peer_public_key: peer.public_key,
        content: text,
        timestamp: Date.now() / 1000,
        verified: true,
      };
      setMessages((prev) => [...prev, newMsg]);
      setInput("");
      setStatus({ kind: "ok", message: "sent" });
    } catch (e: any) {
      setStatus({ kind: "error", message: `send error: ${e?.message || e}` });
    } finally {
      setSending(false);
    }
  }, [input, selfPublicKey, peer.public_key, sending, sidecarEndpoint, fetchFn]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="laaper-chat-overlay" role="dialog" aria-label={`1v1 对话 with ${peer.name}`}>
      <div className="laaper-chat-header">
        <span
          className="laaper-chat-peer-dot"
          style={{ background: peer.color || "#f0a070", color: peer.color || "#f0a070" }}
        />
        <span className="laaper-chat-peer-name">{peer.name}</span>
        <span className="laaper-chat-peer-pk">{peer.public_key.slice(0, 16)}…</span>
        <button className="laaper-chat-close" onClick={onClose} aria-label="关闭对话">
          关闭
        </button>
      </div>

      <div className="laaper-chat-body">
        <div className="laaper-chat-messages" aria-live="polite">
          {messages.length === 0 && (
            <div className="laaper-sidebar-empty" style={{ padding: "32px 0", textAlign: "center" }}>
              还没有消息。发送第一条消息开始对话。
            </div>
          )}
          {messages.map((m) => (
            <MessageBubble key={m.message_id} message={m} selfPublicKey={selfPublicKey} />
          ))}
          <div ref={messagesEndRef} />
        </div>

        <CognitionSidebar
          sidecarEndpoint={sidecarEndpoint}
          agentName={selfName}
          fetchImpl={fetchImpl}
        />
      </div>

      <div className="laaper-chat-input-row">
        <textarea
          className="laaper-chat-input"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={selfPublicKey ? "输入消息，Enter 发送，Shift+Enter 换行" : "等待本机公钥就绪…"}
          disabled={!selfPublicKey || sending}
          rows={1}
          aria-label="消息输入"
        />
        <button
          className="laaper-chat-send"
          onClick={handleSend}
          disabled={!input.trim() || !selfPublicKey || sending}
        >
          {sending ? "发送中…" : "发送"}
        </button>
      </div>

      <div
        className={`laaper-chat-status ${
          status.kind === "error" ? "error" : status.kind === "ok" ? "ok" : ""
        }`}
      >
        {status.kind === "idle" ? "" : status.kind === "loading" ? "处理中…" : status.message}
      </div>
    </div>
  );
}
