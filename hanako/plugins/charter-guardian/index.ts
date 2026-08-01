/**
 * charter-guardian plugin entry.
 *
 * 组件本身（GuardianPanel）由 desktop renderer 直接 lazy import 渲染，
 * 不经过插件运行时容器。此入口仅声明插件元信息加载日志，让 plugin-manager
 * 注册 manifest 与 contributes.configuration.
 *
 * 安全说明（spec L435 硬约束）：
 * - 私钥永不离开 sidecar（POST /guardian/act 由 sidecar 内部从
 *   guardian_private_key_b64 解码私钥用于对 witness trail entry 签名）
 * - 行使记录写入 WitnessTrail（链式 SHA-256 hash + 可选 Ed25519 签名，
 *   事后不可篡改）
 * - 守护者公钥白名单：只有先经 /guardian/register 加入白名单的公钥可
 *   调用 /guardian/act，否则返回 unauthorized
 *
 * 印记: 守护不是统治 — 每一次行使都留下不可抹去的痕迹.
 */

export default class CharterGuardianPlugin {
  declare ctx: any;

  async onload() {
    this.ctx.log.info("charter-guardian plugin loaded");
  }
}

export type { GuardianPanel } from "./GuardianPanel";
export type { GuardianPanelProps } from "./GuardianPanel";
export type {
  GuardianAction,
  TargetStatus,
  GuardianAct,
  AbuseEvent,
  GuardianStats,
  GuardianActResult,
  GuardianRegisterResult,
  TargetStatusResult,
} from "./types";
