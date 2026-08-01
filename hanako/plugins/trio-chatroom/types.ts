/**
 * trio-chatroom 共享类型。
 *
 * 与 sidecar /trio/* 端点契约对齐：
 * - POST /trio/create  {member_public_keys}                    -> {created, chatroom_id, member_count, created_at}
 * - POST /trio/topic   {chatroom_id, topic, creator_public_key?}-> {topic_id, chatroom_id, title, created_at}
 * - POST /trio/message {chatroom_id, content, sender_public_key, agent_name?, topic_id?} -> {stored, message_id, ...}
 * - POST /trio/consensus {chatroom_id, topic_id, use_llm?}     -> {consensus_reached, views[], disagreement_points[], ...}
 * - POST /trio/get     {chatroom_id}                           -> {chatroom_id, member_public_keys[], topics[], messages[]}
 *
 * 数据结构镜像 laap/protocol/laap_coop.py 的 dataclass to_dict() 输出。
 */

/** 成员信息（来自 BubbleField onCreateChatroom 注入） */
export interface TrioMember {
  public_key: string;
  name: string;
  color: string;
}

/** 聊天室话题（sidecar /trio/topic 与 /trio/get 返回项） */
export interface TrioTopic {
  topic_id: string;
  chatroom_id: string;
  title: string;
  created_at: number;
  creator_public_key?: string;
}

/** 单条聊天室消息（sidecar /trio/get 返回项） */
export interface TrioMessage {
  message_id: string;
  chatroom_id: string;
  sender_public_key: string;
  content: string;
  timestamp: number;
  topic_id: string;
  verified: boolean;
}

/** 成员观点卡片（consensus 检测结果中的 views[] 项） */
export interface TrioView {
  public_key: string;
  stance: "pro" | "con" | "neutral";
  keywords: string[];
  summary: string;
  grounding?: {
    state?: string;
    confidence?: number;
    evidence?: string[];
    rejected?: boolean;
  } | null;
  message_id: string;
}

/** /trio/consensus 响应 */
export interface TrioConsensusResult {
  chatroom_id: string;
  topic_id: string;
  views: TrioView[];
  disagreement_points: string[];
  consensus_reached: boolean;
  method: "llm" | "rule";
  avg_keyword_overlap: number;
  /** 仅共识达成时返回 */
  witness_trail_id?: string;
  error?: string;
}

/** /trio/create 响应 */
export interface TrioCreateResult {
  created: boolean;
  chatroom_id: string;
  member_count: number;
  created_at: number;
  error?: string;
}

/** /trio/topic 响应 */
export interface TrioTopicResult {
  topic_id: string;
  chatroom_id: string;
  title: string;
  created_at: number;
  posted?: boolean;
  error?: string;
}

/** /trio/message 响应 */
export interface TrioMessageResult {
  stored: boolean;
  message_id?: string;
  chatroom_id?: string;
  topic_id?: string;
  envelope?: {
    message: string;
    signature: string;
    public_key: string;
    peer_public_key?: string;
  };
  error?: string;
}

/** /trio/get 响应（聊天室完整状态） */
export interface TrioChatroomState {
  chatroom_id: string;
  member_public_keys: string[];
  created_at: number;
  member_count: number;
  topic_count: number;
  message_count: number;
  topics: TrioTopic[];
  messages: TrioMessage[];
  error?: string;
}
