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
