/**
 * laaper-chat 共享类型。
 *
 * 与 sidecar /chat/* 端点契约对齐：
 * - POST /chat/send {sender_public_key, peer_public_key, message} -> {sent, message_id, envelope}
 * - POST /chat/receive {envelope} -> {verified, content, sender_public_key, message_id, stored}
 * - POST /chat/history {peer_a, peer_b, limit?} -> {count, messages[]}
 */

/** 对话 peer 信息（来自 BubbleField onSelectBubble 存入 store） */
export interface ChatPeer {
  public_key: string;
  name: string;
  color: string;
}

/** 单条 1v1 消息记录（sidecar /chat/history 返回项） */
export interface ChatMessage {
  message_id: string;
  sender_public_key: string;
  peer_public_key: string;
  content: string;
  timestamp: number;
  verified: boolean;
  /** 可选：认知足迹展开数据（UI 本地填充，sidecar 不返回） */
  cognition?: CognitionFootprint;
}

/** 认知足迹（消息展开后显示的因果/记忆/真值状态） */
export interface CognitionFootprint {
  causal?: string[];
  memory?: string[];
  truth?: string;
}

/** /chat/history 响应 */
export interface ChatHistoryResult {
  count: number;
  messages: ChatMessage[];
  error?: string;
}

/** /chat/send 响应 */
export interface ChatSendResult {
  sent: boolean;
  message_id?: string;
  envelope?: {
    message: string;
    signature: string;
    public_key: string;
    peer_public_key?: string;
  };
  error?: string;
}

/** /chat/receive 响应 */
export interface ChatReceiveResult {
  verified: boolean;
  content?: string;
  sender_public_key?: string;
  message_id?: string;
  stored?: boolean;
  error?: string;
}
