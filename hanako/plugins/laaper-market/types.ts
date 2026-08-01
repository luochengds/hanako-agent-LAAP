/**
 * laaper-market plugin 类型定义 (P5-laaper-market)
 *
 * 社区示例 LAAPer 预设包市场数据契约.
 * 与 laap/skills/preset_registry.py 中 PresetPack 字段一一对应.
 */

/** 社区预设包 (对应 Python 端 PresetPack) */
export interface PresetPack {
  id: string;
  name: string;
  description: string;
  yuan: string;
  ishiki: string;
  avatar_seed: string;
  color: string;
  initial_skills: string[];
  charter_version: string;
}

/** /preset/list 端点返回结构 */
export interface PresetListResponse {
  presets: PresetPack[];
}

/** /preset/get 端点返回结构 */
export interface PresetGetResponse {
  preset: PresetPack;
}

/** 克隆后新 LAAPer 的配置 (不直接创建身份, 交给 birth-ceremony) */
export interface ClonedConfig {
  name: string;
  yuan: string;
  ishiki: string;
  avatar_seed: string;
  color: string;
  initial_skills: string[];
  charter_version: string;
  source_preset_id: string;
}

/** /preset/clone 端点返回结构 */
export interface CloneResult {
  cloned: boolean;
  config: ClonedConfig;
}

/** 克隆请求体 */
export interface CloneRequest {
  preset_id: string;
  new_name: string;
  customizations?: {
    yuan?: string;
    ishiki?: string;
    avatar_seed?: string;
    color?: string;
    initial_skills?: string[];
  };
}

/** 克隆弹窗的自定义字段表单 */
export interface CloneFormState {
  newName: string;
  customYuan: string;
  customIshiki: string;
  customColor: string;
  /** 是否启用性格自定义覆盖 */
  enableCustom: boolean;
}

/** 端点错误响应 */
export interface PresetErrorResponse {
  error: string;
}
