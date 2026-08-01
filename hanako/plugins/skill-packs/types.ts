/**
 * skill-packs 共享类型定义
 *
 * SkillPacksPanel 通过 sidecar 5 端点管理技能包：
 * - GET  /skills/list?agent_name=X
 * - POST /skills/export   { skill_id, output_dir? }
 * - POST /skills/import   { zip_path }
 * - POST /skills/install  { agent_name, skill_id }
 * - POST /skills/uninstall { agent_name, skill_id }
 */

/** 已安装技能记录（来自 vault installed_skills 表） */
export interface InstalledSkill {
  skill_id: string;
  agent_name: string;
  version: string;
  author: string;
  charter_compatible: boolean;
  installed_at: string;
}

/** 可用技能记录（来自 laap/skills/{skill_id}/manifest.json 扫描） */
export interface AvailableSkill {
  skill_id: string;
  version: string;
  author: string;
  charter_compatible: boolean;
  description: string;
}

/** GET /skills/list 响应 */
export interface SkillListResponse {
  agent_name: string;
  installed: InstalledSkill[];
  available: AvailableSkill[];
}

/** POST /skills/export 响应 */
export interface SkillExportResponse {
  exported: boolean;
  skill_id: string;
  version: string;
  zip_path: string;
}

/** POST /skills/import 响应 */
export interface SkillImportResponse {
  imported: boolean;
  skill_id: string;
}

/** POST /skills/install 响应 */
export interface SkillInstallResponse {
  installed: boolean;
  skill_id: string;
  version: string;
  agent_name: string;
}

/** POST /skills/uninstall 响应 */
export interface SkillUninstallResponse {
  uninstalled: boolean;
  skill_id: string;
  agent_name: string;
}

/** 错误响应 */
export interface SkillErrorResponse {
  error: string;
}

/** SkillPacksPanel props */
export interface SkillPacksPanelProps {
  /** sidecar 基址，默认 http://127.0.0.1:11521 */
  sidecarEndpoint?: string;
  /** 目标 agent 名称（操作 install/uninstall 时使用），默认 "aris" */
  agentName?: string;
  /** 关闭回调 */
  onClose?: () => void;
  /** 外部注入的 fetch 函数（测试用），默认 window.fetch */
  fetchImpl?: typeof fetch;
}

/** SkillCard props */
export interface SkillCardProps {
  skill: AvailableSkill;
  /** 是否已安装（用于切换 install/uninstall 按钮文案） */
  installed: boolean;
  /** 安装按钮回调 */
  onInstall: (skillId: string) => void;
  /** 卸载按钮回调 */
  onUninstall: (skillId: string) => void;
  /** 导出按钮回调 */
  onExport: (skillId: string) => void;
  /** 操作进行中（按钮 disabled） */
  busy?: boolean;
}
