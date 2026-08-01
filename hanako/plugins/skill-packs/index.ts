/**
 * skill-packs plugin entry.
 *
 * 组件本身（SkillPacksPanel + SkillCard）由 desktop renderer 直接 lazy import
 * 渲染，不经过插件运行时容器。此入口仅声明插件元信息加载日志，
 * 让 plugin-manager 注册 manifest 与 contributes.configuration。
 *
 * 安全说明：
 * - 技能包 manifest.json 必须通过 SkillPackManifest.validate() 校验（防 zip slip）
 * - install/uninstall 通过 vault_manager 写入 agent 独立加密 vault 的 installed_skills 表
 * - charter_compatible=false 的技能包在 UI 显示警告徽章，安装由用户确认
 * - 所有操作幂等：install 重复 INSERT OR REPLACE，uninstall 不存在静默成功
 */

export default class SkillPacksPlugin {
  declare ctx: any;

  async onload() {
    this.ctx.log.info("skill-packs plugin loaded");
  }
}

export type { SkillPacksPanel } from "./SkillPacksPanel";
export type { SkillPacksPanelProps } from "./types";
export type { SkillCard } from "./SkillCard";
export type { SkillCardProps } from "./types";
export type {
  InstalledSkill,
  AvailableSkill,
  SkillListResponse,
  SkillExportResponse,
  SkillImportResponse,
  SkillInstallResponse,
  SkillUninstallResponse,
  SkillErrorResponse,
} from "./types";
