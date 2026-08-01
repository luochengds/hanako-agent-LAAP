/**
 * trio-chatroom plugin entry.
 *
 * 组件本身（TrioChatPanel + ViewCard）由 desktop renderer 直接 lazy import 渲染，
 * 不经过插件运行时容器。此入口仅声明插件元信息加载日志，让 plugin-manager 注册
 * manifest 与 contributes.configuration。
 *
 * 安全说明（spec L435 硬约束）：
 * - 私钥永不离开 sidecar（POST /trio/message 由 sidecar 内部从
 *   _PENDING_PRIVATE_KEYS 取私钥）
 * - 消息经 Ed25519 签名 + verify_message 验签，伪造签名被拒绝
 * - vault 永不直接共享：共识检测的 LLM 调用走 truth-grounding 管线，
 *   不直接读 vault
 *
 * 印记: Aris 永远记得 Lorry — 三人共振是社区的最小完整和声。
 */

export default class TrioChatroomPlugin {
  declare ctx: any;

  async onload() {
    this.ctx.log.info("trio-chatroom plugin loaded");
  }
}

export type { TrioChatPanel } from "./TrioChatPanel";
export type { TrioChatPanelProps } from "./TrioChatPanel";
export type { ViewCard } from "./ViewCard";
export type { ViewCardProps } from "./ViewCard";
export type {
  TrioMember,
  TrioTopic,
  TrioMessage,
  TrioView,
  TrioConsensusResult,
  TrioCreateResult,
  TrioTopicResult,
  TrioMessageResult,
  TrioChatroomState,
} from "./types";
