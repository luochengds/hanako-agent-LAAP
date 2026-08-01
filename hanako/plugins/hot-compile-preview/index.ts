/**
 * hot-compile-preview plugin entry.
 *
 * 组件本身（HotCompilePanel + PreviewSandbox + DiffViewer）由 desktop renderer
 * 直接 lazy import 渲染，不经过插件运行时容器。此入口仅声明插件元信息加载日志，
 * 让 plugin-manager 注册 manifest 与 contributes.configuration。
 *
 * 安全说明：预览在 sandbox="allow-scripts" 的隔离 iframe 中渲染，主应用不受影响；
 * 热替换仅允许 laap/ 或 hanako/plugins/ 下文件，且写入前会备份原文件到 .bak.{ts}。
 */

export default class HotCompilePreviewPlugin {
  declare ctx: any;

  async onload() {
    this.ctx.log.info("hot-compile-preview plugin loaded");
  }
}

export type { HotCompilePanel } from "./HotCompilePanel";
export type { HotCompilePanelProps, PreviewResult, HotReplaceResult } from "./HotCompilePanel";
export type { PreviewSandbox } from "./PreviewSandbox";
export type { PreviewSandboxProps } from "./PreviewSandbox";
export type { DiffViewer } from "./DiffViewer";
export type { DiffViewerProps, DiffLine } from "./DiffViewer";
