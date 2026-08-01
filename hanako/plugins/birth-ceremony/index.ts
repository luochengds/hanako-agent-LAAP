/**
 * birth-ceremony plugin entry.
 *
 * 组件本身（CeremonyWizard + 6 个 Step）由 desktop renderer 直接 lazy import
 * 渲染，不经过插件运行时容器。此入口仅声明插件元信息加载日志，
 * 让 plugin-manager 注册 manifest 与 contributes.configuration。
 */

export default class BirthCeremonyPlugin {
  declare ctx: any;

  async onload() {
    this.ctx.log.info("birth-ceremony plugin loaded");
  }
}

export type { CeremonyWizard } from "./CeremonyWizard";
export type { NameStep } from "./steps/NameStep";
export type { AvatarStep } from "./steps/AvatarStep";
export type { PersonalityStep } from "./steps/PersonalityStep";
export type { CharterStep } from "./steps/CharterStep";
export type { PubKeyStep } from "./steps/PubKeyStep";
export type { DoneStep } from "./steps/DoneStep";
export type {
  CeremonyStep,
  CeremonyState,
  CeremonyWizardProps,
  StepProps,
  FinalizedLaaper,
  FinalizeRequest,
  FinalizeResponse,
  PubKeyRequest,
  PubKeyResponse,
  CheckNameResponse,
  CharterArticle,
  AvatarPreset,
  PersonalityQuestion,
} from "./types";
export {
  CEREMONY_STEP_ORDER,
  CEREMONY_STEP_LABELS,
  DEFAULT_AVATAR_PRESETS,
  DEFAULT_PERSONALITY_QUESTIONS,
  DEFAULT_CHARTER_ARTICLES,
} from "./types";
