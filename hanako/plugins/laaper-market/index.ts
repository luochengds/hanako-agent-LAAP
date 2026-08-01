/**
 * laaper-market plugin entry (P5-laaper-market)
 *
 * 组件本身 (MarketBrowser) 由 desktop renderer 直接 lazy import 渲染,
 * 不经过插件运行时容器。此入口仅声明插件元信息加载日志, 让 plugin-manager
 * 注册 manifest 与 contributes.commands.
 *
 * 设计说明:
 * - 克隆不直接创建身份: MarketBrowser 调 /preset/clone 拿到配置后,
 *   通过 onClone(config) 回调让父组件 (App.tsx) 切换到 birth-ceremony,
 *   由诞生仪式完成真正的身份创建与公钥签发.
 * - 预设包元数据由 laap/skills/preset_registry.py 维护, 端点幂等.
 *
 * 印记: 一键克隆, 各自绽放 — 预设是起点, 不是终点.
 */

export default class LaaperMarketPlugin {
  declare ctx: any;

  async onload() {
    this.ctx.log.info("laaper-market plugin loaded");
  }
}

export type { MarketBrowser } from "./MarketBrowser";
export type { MarketBrowserProps } from "./MarketBrowser";
export type {
  PresetPack,
  PresetListResponse,
  PresetGetResponse,
  CloneResult,
  CloneRequest,
  ClonedConfig,
  CloneFormState,
  PresetErrorResponse,
} from "./types";
