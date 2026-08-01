/**
 * laaper-chat plugin entry.
 *
 * 组件本身（LaaperChatPanel + MessageBubble + CognitionSidebar）由 desktop renderer
 * 直接 lazy import 渲染，不经过插件运行时容器。此入口仅声明插件元信息加载日志，
 * 让 plugin-manager 注册 manifest 与 contributes.configuration。
 *
 * 安全说明：
 * - 私钥永不离开 sidecar（POST /chat/send 由 sidecar 内部从 _PENDING_PRIVATE_KEYS 取私钥）
 * - 消息经 Ed25519 签名 + verify_message 验签，伪造签名被拒绝
 * - vault 永不直接共享：CognitionSidebar 仅展示本机检索的 causal/memory/truth 状态
 */

export default class LaaperChatPlugin {
  declare ctx: any;

  async onload() {
    this.ctx.log.info("laaper-chat plugin loaded");
  }
}

export type { LaaperChatPanel } from "./LaaperChatPanel";
export type { LaaperChatPanelProps } from "./LaaperChatPanel";
export type { ChatMessage, ChatHistoryResult, ChatSendResult, ChatReceiveResult, ChatPeer, CognitionFootprint } from "./types";
export type { MessageBubble } from "./MessageBubble";
export type { MessageBubbleProps } from "./MessageBubble";
export type { CognitionSidebar } from "./CognitionSidebar";
export type { CognitionSidebarProps, CognitionState } from "./CognitionSidebar";
