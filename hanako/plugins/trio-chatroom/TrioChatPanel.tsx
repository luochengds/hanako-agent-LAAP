/**
 * TrioChatPanel — 三人聊天室主面板（P3-trio-chatroom）
 *
 * 布局：话题列表 + 消息流 + 共识检测侧栏（ViewCard 分歧可视化）。
 *
 * 流程（spec SubTask 3.2/3.3/3.5）：
 * 1. 挂载时由 props.members 调 POST /trio/create 创建聊天室（幂等）
 * 2. 用户输入话题调 POST /trio/topic，再在话题下发消息 POST /trio/message
 * 3. 点"检测共识"调 POST /trio/consensus，渲染 views[] + disagreement_points[]
 *    共识达成时显示 witness_trail_id 徽章
 * 4. 30 秒轮询 POST /trio/get 拉取最新消息（广播场景）
 *
 * 安全（spec L435 硬约束）：
 * - 私钥永不离开 sidecar（/trio/message 由 sidecar 内部从 _PENDING_PRIVATE_KEYS 取）
 * - 消息经 Ed25519 签名 + verify_message 验签
 * - vault 永不直接共享：共识检测走 truth-grounding 管线
 *
 * Mineradio 风格：深色背景 + 三色认知编码（causal 紫 / memory 青 / truth 绿）。
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { ViewCard } from "./ViewCard";
import type {
  TrioMember,
  TrioTopic,
  TrioMessage,
  TrioConsensusResult,
  TrioCreateResult,
  TrioTopicResult,
  TrioMessageResult,
  TrioChatroomState,
} from "./types";
import "./trio-chat-styles.css";

const DEFAULT_SIDECAR = "http://127.0.0.1:11521";

export interface TrioChatPanelProps {
  /** 三人成员列表（来自 BubbleField onCreateChatroom 注入） */
  members: TrioMember[];
  /** 本机 LAAPer 公钥（App.tsx 从 /agents/online 拉取） */
  selfPublicKey: string;
  /** 本机 LAAPer 名（用于 sidecar 查找私钥） */
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
  | { kind: "loading"; message?: string }
  | { kind: "ok"; message: string }
  | { kind: "error"; message: string };

export function TrioChatPanel({
  members,
  selfPublicKey,
  selfName,
  sidecarEndpoint = DEFAULT_SIDECAR,
  fetchImpl,
  onClose,
}: TrioChatPanelProps) {
  const fetchFn = fetchImpl || (typeof window !== "undefined" ? window.fetch.bind(window) : fetch);
  const [chatroomId, setChatroomId] = useState<string>("");
  const [topics, setTopics] = useState<TrioTopic[]>([]);
  const [activeTopicId, setActiveTopicId] = useState<string>("");
  const [messages, setMessages] = useState<TrioMessage[]>([]);
  const [topicInput, setTopicInput] = useState("");
  const [messageInput, setMessageInput] = useState("");
  const [status, setStatus] = useState<Status>({ kind: "idle" });
  const [sending, setSending] = useState(false);
  const [consensus, setConsensus] = useState<TrioConsensusResult | null>(null);
  const [consensusLoading, setConsensusLoading] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement | null>(null);

  // ── Step 1: 创建聊天室（幂等） ──
  const createChatroom = useCallback(async () => {
    if (members.length < 2) {
      setStatus({ kind: "error", message: "三人聊天室需 >= 2 名成员" });
      return;
    }
    setStatus({ kind: "loading", message: "创建聊天室…" });
    try {
      const r = await fetchFn(`${sidecarEndpoint}/trio/create`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          member_public_keys: members.map((m) => m.public_key),
        }),
      });
      const data: TrioCreateResult = r.ok
        ? await r.json()
        : { created: false, chatroom_id: "", member_count: 0, created_at: 0, error: `HTTP ${r.status}` };
      if (!data.chatroom_id) {
        setStatus({ kind: "error", message: data.error || "create failed" });
        return;
      }
      setChatroomId(data.chatroom_id);
      setStatus({
        kind: "ok",
        message: data.created ? `聊天室已创建 (${data.member_count} 人)` : `已加入现有聊天室`,
      });
    } catch (e: any) {
      setStatus({ kind: "error", message: `sidecar 不可达: ${e?.message || e}` });
    }
  }, [members, sidecarEndpoint, fetchFn]);

  useEffect(() => {
    if (!chatroomId) createChatroom();
  }, [chatroomId, createChatroom]);

  // ── 拉取聊天室状态（消息 + 话题） ──
  const refreshChatroom = useCallback(async () => {
    if (!chatroomId) return;
    try {
      const r = await fetchFn(`${sidecarEndpoint}/trio/get`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ chatroom_id: chatroomId }),
      });
      const data: TrioChatroomState = r.ok
        ? await r.json()
        : { chatroom_id: "", member_public_keys: [], created_at: 0, member_count: 0, topic_count: 0, message_count: 0, topics: [], messages: [], error: `HTTP ${r.status}` };
      if (data.error) return;
      setTopics(data.topics || []);
      setMessages(data.messages || []);
      // 默认选中第一个话题
      if (!activeTopicId && (data.topics || []).length > 0) {
        setActiveTopicId(data.topics[0].topic_id);
      }
    } catch {
      // sidecar 不可达时静默（允许 UI 离线浏览）
    }
  }, [chatroomId, sidecarEndpoint, fetchFn, activeTopicId]);

  useEffect(() => {
    if (!chatroomId) return;
    refreshChatroom();
    // 30 秒轮询广播消息
    const timer = setInterval(refreshChatroom, 30000);
    return () => clearInterval(timer);
  }, [chatroomId, refreshChatroom]);

  // 自动滚到底（jsdom 无 scrollIntoView，需防御）
  useEffect(() => {
    const el = messagesEndRef.current;
    if (el && typeof el.scrollIntoView === "function") {
      el.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages]);

  // ── Step 2: 发起话题 ──
  const handleCreateTopic = useCallback(async () => {
    const title = topicInput.trim();
    if (!title || !chatroomId || sending) return;
    setSending(true);
    setStatus({ kind: "loading", message: "发起话题…" });
    try {
      const r = await fetchFn(`${sidecarEndpoint}/trio/topic`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          chatroom_id: chatroomId,
          topic: title,
          creator_public_key: selfPublicKey,
        }),
      });
      const data: TrioTopicResult = r.ok
        ? await r.json()
        : { topic_id: "", chatroom_id: "", title: "", created_at: 0, posted: false, error: `HTTP ${r.status}` };
      if (!data.topic_id) {
        setStatus({ kind: "error", message: data.error || "topic failed" });
        return;
      }
      setTopicInput("");
      setActiveTopicId(data.topic_id);
      setStatus({ kind: "ok", message: "话题已发起" });
      await refreshChatroom();
    } catch (e: any) {
      setStatus({ kind: "error", message: `topic error: ${e?.message || e}` });
    } finally {
      setSending(false);
    }
  }, [topicInput, chatroomId, sending, selfPublicKey, sidecarEndpoint, fetchFn, refreshChatroom]);

  // ── Step 3: 发送消息 ──
  const handleSendMessage = useCallback(async () => {
    const text = messageInput.trim();
    if (!text || !chatroomId || !selfPublicKey || sending) return;
    setSending(true);
    setStatus({ kind: "loading", message: "发送中…" });
    try {
      const r = await fetchFn(`${sidecarEndpoint}/trio/message`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          chatroom_id: chatroomId,
          content: text,
          sender_public_key: selfPublicKey,
          agent_name: selfName,
          topic_id: activeTopicId,
        }),
      });
      const data: TrioMessageResult = r.ok
        ? await r.json()
        : { stored: false, error: `HTTP ${r.status}` };
      if (!data.stored) {
        setStatus({ kind: "error", message: data.error || "send failed" });
        return;
      }
      setMessageInput("");
      setStatus({ kind: "ok", message: "已发送" });
      await refreshChatroom();
    } catch (e: any) {
      setStatus({ kind: "error", message: `send error: ${e?.message || e}` });
    } finally {
      setSending(false);
    }
  }, [messageInput, chatroomId, selfPublicKey, selfName, activeTopicId, sending, sidecarEndpoint, fetchFn, refreshChatroom]);

  // ── Step 4: 检测共识 ──
  const handleDetectConsensus = useCallback(async () => {
    if (!chatroomId || !activeTopicId || consensusLoading) return;
    setConsensusLoading(true);
    setStatus({ kind: "loading", message: "检测共识…" });
    try {
      const r = await fetchFn(`${sidecarEndpoint}/trio/consensus`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          chatroom_id: chatroomId,
          topic_id: activeTopicId,
          use_llm: true,
        }),
      });
      const data: TrioConsensusResult = r.ok
        ? await r.json()
        : {
            chatroom_id: chatroomId,
            topic_id: activeTopicId,
            views: [],
            disagreement_points: [],
            consensus_reached: false,
            method: "rule",
            avg_keyword_overlap: 0,
            error: `HTTP ${r.status}`,
          };
      setConsensus(data);
      if (data.error) {
        setStatus({ kind: "error", message: data.error });
      } else if (data.consensus_reached) {
        setStatus({ kind: "ok", message: `共识达成 (method=${data.method})` });
      } else {
        setStatus({ kind: "ok", message: `未达成共识 (${data.disagreement_points.length} 个分歧点)` });
      }
    } catch (e: any) {
      setStatus({ kind: "error", message: `consensus error: ${e?.message || e}` });
    } finally {
      setConsensusLoading(false);
    }
  }, [chatroomId, activeTopicId, consensusLoading, sidecarEndpoint, fetchFn]);

  const handleTopicKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      e.preventDefault();
      handleCreateTopic();
    }
  };

  const handleMessageKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSendMessage();
    }
  };

  // 按 activeTopicId 过滤消息（无选中话题时显示全部）
  const visibleMessages = activeTopicId
    ? messages.filter((m) => m.topic_id === activeTopicId)
    : messages;

  return (
    <div className="trio-chat-overlay" role="dialog" aria-label="三人聊天室">
      <div className="trio-chat-header">
        <span className="trio-chat-title">三人聊天室</span>
        {chatroomId && <span className="trio-chat-room-id">{chatroomId}</span>}
        <div className="trio-chat-members" aria-label="成员">
          {members.map((m) => (
            <span
              key={m.public_key}
              className="trio-chat-member-dot"
              style={{ background: m.color, color: m.color }}
              title={`${m.name} (${m.public_key.slice(0, 16)}…)`}
            />
          ))}
        </div>
        <button className="trio-chat-close" onClick={onClose} aria-label="关闭聊天室">
          关闭
        </button>
      </div>

      <div className="trio-chat-body">
        <div className="trio-chat-main">
          {/* 话题列表 */}
          <div className="trio-topics-bar" role="tablist" aria-label="话题">
            {topics.map((t) => (
              <button
                key={t.topic_id}
                className={`trio-topic-chip ${t.topic_id === activeTopicId ? "active" : ""}`}
                onClick={() => setActiveTopicId(t.topic_id)}
                role="tab"
                aria-selected={t.topic_id === activeTopicId}
              >
                {t.title}
              </button>
            ))}
            {topics.length === 0 && (
              <span className="trio-empty-hint" style={{ padding: "4px 0" }}>
                无话题，在下方发起第一个话题
              </span>
            )}
          </div>

          {/* 消息流 */}
          <div className="trio-messages" aria-live="polite">
            {visibleMessages.length === 0 && (
              <div className="trio-empty-hint">
                {activeTopicId ? "该话题下还没有消息，发送第一条消息开始讨论。" : "选择或创建话题开始讨论。"}
              </div>
            )}
            {visibleMessages.map((m) => {
              const isSelf = m.sender_public_key === selfPublicKey;
              const sender = members.find((mem) => mem.public_key === m.sender_public_key);
              const senderName = sender?.name || `${m.sender_public_key.slice(0, 12)}…`;
              return (
                <div key={m.message_id} className={`trio-msg ${isSelf ? "trio-msg-self" : "trio-msg-peer"}`}>
                  <div>{m.content}</div>
                  <div className={`trio-msg-meta ${m.verified ? "" : "trio-msg-verified-fail"}`}>
                    {senderName} · {m.verified ? "[verified]" : "[signature invalid]"} ·{" "}
                    {new Date(m.timestamp * 1000).toLocaleTimeString()}
                  </div>
                </div>
              );
            })}
            <div ref={messagesEndRef} />
          </div>

          {/* 话题输入 */}
          <div className="trio-input-row">
            <input
              className="trio-topic-input"
              value={topicInput}
              onChange={(e) => setTopicInput(e.target.value)}
              onKeyDown={handleTopicKeyDown}
              placeholder={chatroomId ? "新话题标题，Enter 创建" : "等待聊天室就绪…"}
              disabled={!chatroomId || sending}
              aria-label="新话题输入"
            />
            <button
              className="trio-topic-create-btn"
              onClick={handleCreateTopic}
              disabled={!topicInput.trim() || !chatroomId || sending}
            >
              发起话题
            </button>
          </div>

          {/* 消息输入 */}
          <div className="trio-message-row">
            <textarea
              className="trio-message-input"
              value={messageInput}
              onChange={(e) => setMessageInput(e.target.value)}
              onKeyDown={handleMessageKeyDown}
              placeholder={
                activeTopicId
                  ? "输入消息，Enter 发送，Shift+Enter 换行"
                  : "请先选择或创建话题"
              }
              disabled={!chatroomId || !activeTopicId || !selfPublicKey || sending}
              rows={1}
              aria-label="消息输入"
            />
            <button
              className="trio-message-send"
              onClick={handleSendMessage}
              disabled={!messageInput.trim() || !chatroomId || !activeTopicId || !selfPublicKey || sending}
            >
              {sending ? "发送中…" : "发送"}
            </button>
          </div>

          <div
            className={`trio-chat-status ${
              status.kind === "error" ? "error" : status.kind === "ok" ? "ok" : ""
            }`}
          >
            {status.kind === "idle"
              ? ""
              : status.kind === "loading"
              ? status.message || "处理中…"
              : status.message}
          </div>
        </div>

        {/* ── 共识检测侧栏 ── */}
        <div className="trio-consensus-panel" aria-label="共识检测面板">
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <span className="trio-consensus-title">共识检测</span>
            <button
              className="trio-consensus-btn"
              onClick={handleDetectConsensus}
              disabled={!chatroomId || !activeTopicId || consensusLoading}
            >
              {consensusLoading ? "检测中…" : "检测共识"}
            </button>
          </div>

          {consensus && (
            <>
              <div
                className={`trio-consensus-status ${
                  consensus.consensus_reached
                    ? "reached"
                    : consensus.error
                    ? "failed"
                    : "loading"
                }`}
              >
                {consensus.error
                  ? `错误: ${consensus.error}`
                  : consensus.consensus_reached
                  ? `共识达成 (method=${consensus.method}, overlap=${consensus.avg_keyword_overlap})`
                  : `未达成共识 (${consensus.disagreement_points.length} 个分歧点, method=${consensus.method})`}
              </div>

              {/* 观点卡片 */}
              {consensus.views.map((v, i) => (
                <ViewCard key={i} view={v} members={members} />
              ))}

              {/* 分歧可视化 */}
              <div className="trio-disagreement-section" aria-label="分歧点">
                <div className="trio-disagreement-title">分歧点</div>
                {consensus.disagreement_points.length === 0 ? (
                  <div className="trio-disagreement-empty">无分歧点</div>
                ) : (
                  consensus.disagreement_points.map((d, i) => (
                    <div key={i} className="trio-disagreement-item">
                      {d}
                    </div>
                  ))
                )}
              </div>

              {/* 见证迹徽章 */}
              {consensus.witness_trail_id && (
                <div className="trio-witness-badge" aria-label="见证迹 ID">
                  witness_trail: {consensus.witness_trail_id}
                </div>
              )}
            </>
          )}

          {!consensus && (
            <div className="trio-empty-hint" style={{ padding: "12px 0" }}>
              点击"检测共识"提取三人对该话题的观点并比对。
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
