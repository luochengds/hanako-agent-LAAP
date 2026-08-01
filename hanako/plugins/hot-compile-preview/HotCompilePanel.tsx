/**
 * HotCompilePanel — 组件热编译预览主面板
 *
 * 布局：源码编辑器 + PreviewSandbox + DiffViewer + 确认替换按钮（tasks SubTask 2.1）。
 *
 * 流程：
 * 1. 加载：POST /preview/component { component_path, new_content: "" } 取原文件 + 空 diff
 * 2. 编辑：用户在 textarea 修改新源码
 * 3. 预览：POST /preview/component { component_path, new_content } → 更新 PreviewSandbox + DiffViewer
 * 4. 替换：POST /preview/replace { component_path, new_content, confirmed_by } → 写文件 + 备份 + 见证迹
 *
 * 安全：替换前需用户在确认对话框点击"确认替换"。侧车校验路径仅允许 laap/ 或 hanako/plugins/ 下。
 *
 * Mineradio 风格：深色背景 + 简洁表单 + 发光强调色（参考 bubble-field / birth-ceremony）。
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { PreviewSandbox } from "./PreviewSandbox";
import { DiffViewer, type DiffLine } from "./DiffViewer";
import "./hot-compile-styles.css";

const DEFAULT_SIDECAR = "http://127.0.0.1:11521";
const DEFAULT_COMPONENT_PATH = "hanako/plugins/bubble-field/Bubble.tsx";

/** sidecar /preview/component 响应 */
export interface PreviewResult {
  render_result: {
    success: boolean;
    html_preview?: string;
    error?: string;
  };
  diff: DiffLine[];
  old_source: string;
  new_source: string;
}

/** sidecar /preview/replace 响应 */
export interface HotReplaceResult {
  replaced: boolean;
  witness_trail_id: string;
  backup_path: string;
  /** 幂等跳过：内容相同未触发写入 */
  skipped?: boolean;
  error?: string;
}

export interface HotCompilePanelProps {
  /** 要编辑的组件相对路径（相对仓库根），如 "hanako/plugins/bubble-field/Bubble.tsx"。缺省时使用 DEFAULT_COMPONENT_PATH */
  componentPath?: string;
  /** sidecar 端点基址，默认 http://127.0.0.1:11521 */
  sidecarEndpoint?: string;
  /** 可选：注入 fetch 实现（测试用） */
  fetchImpl?: typeof fetch;
  /** 关闭回调 */
  onClose?: () => void;
  /** 操作者标识（写入见证迹），默认 "user" */
  confirmedBy?: string;
}

type Status =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "previewing" }
  | { kind: "ok"; message: string }
  | { kind: "error"; message: string };

export function HotCompilePanel({
  componentPath = DEFAULT_COMPONENT_PATH,
  sidecarEndpoint = DEFAULT_SIDECAR,
  fetchImpl,
  onClose,
  confirmedBy = "user",
}: HotCompilePanelProps) {
  const fetchFn = fetchImpl || (typeof window !== "undefined" ? window.fetch.bind(window) : fetch);
  const [oldSource, setOldSource] = useState<string>("");
  const [newSource, setNewSource] = useState<string>("");
  const [diff, setDiff] = useState<DiffLine[]>([]);
  const [status, setStatus] = useState<Status>({ kind: "idle" });
  const [replaceResult, setReplaceResult] = useState<HotReplaceResult | null>(null);
  const [confirming, setConfirming] = useState<boolean>(false);
  const loadedRef = useRef<boolean>(false);

  // 初始加载：取原文件内容 + 空 diff
  const loadInitial = useCallback(async () => {
    setStatus({ kind: "loading" });
    try {
      const resp = await fetchFn(`${sidecarEndpoint}/preview/component`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ component_path: componentPath, new_content: "" }),
      });
      if (!resp.ok) {
        const text = await resp.text().catch(() => "");
        throw new Error(`HTTP ${resp.status}: ${text || resp.statusText}`);
      }
      const data = (await resp.json()) as PreviewResult;
      setOldSource(data.old_source || "");
      setNewSource(data.old_source || "");
      setDiff(data.diff || []);
      setStatus({ kind: "ok", message: "已加载原文件" });
    } catch (e) {
      setStatus({ kind: "error", message: (e as Error)?.message || String(e) });
    }
  }, [componentPath, sidecarEndpoint, fetchFn]);

  useEffect(() => {
    if (loadedRef.current) return;
    loadedRef.current = true;
    void loadInitial();
  }, [loadInitial]);

  // 预览：调用 sidecar 生成 diff + render_result，并更新 PreviewSandbox
  const handlePreview = useCallback(async () => {
    setStatus({ kind: "previewing" });
    setReplaceResult(null);
    try {
      const resp = await fetchFn(`${sidecarEndpoint}/preview/component`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ component_path: componentPath, new_content: newSource }),
      });
      if (!resp.ok) {
        const text = await resp.text().catch(() => "");
        throw new Error(`HTTP ${resp.status}: ${text || resp.statusText}`);
      }
      const data = (await resp.json()) as PreviewResult;
      setDiff(data.diff || []);
      if (data.render_result?.success) {
        setStatus({ kind: "ok", message: "预览已更新" });
      } else {
        setStatus({
          kind: "error",
          message: data.render_result?.error || "预览渲染失败",
        });
      }
    } catch (e) {
      setStatus({ kind: "error", message: (e as Error)?.message || String(e) });
    }
  }, [componentPath, newSource, sidecarEndpoint, fetchFn]);

  // 确认替换：调用 sidecar /preview/replace 写文件 + 备份 + 见证迹
  const handleReplace = useCallback(async () => {
    setConfirming(false);
    setStatus({ kind: "previewing" });
    try {
      const resp = await fetchFn(`${sidecarEndpoint}/preview/replace`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          component_path: componentPath,
          new_content: newSource,
          confirmed_by: confirmedBy,
        }),
      });
      if (!resp.ok) {
        const text = await resp.text().catch(() => "");
        throw new Error(`HTTP ${resp.status}: ${text || resp.statusText}`);
      }
      const data = (await resp.json()) as HotReplaceResult;
      setReplaceResult(data);
      if (data.replaced) {
        // 替换成功后，oldSource 更新为 newSource，diff 清空
        setOldSource(newSource);
        setDiff([]);
        if (data.skipped) {
          setStatus({ kind: "ok", message: "内容相同，跳过写入（幂等）" });
        } else {
          setStatus({
            kind: "ok",
            message: `已替换，备份 ${data.backup_path || "（无）"}，见证迹 ${data.witness_trail_id || ""}`,
          });
        }
      } else {
        setStatus({ kind: "error", message: data.error || "替换失败" });
      }
    } catch (e) {
      setStatus({ kind: "error", message: (e as Error)?.message || String(e) });
    }
  }, [componentPath, newSource, sidecarEndpoint, fetchFn, confirmedBy]);

  const hasChanges = newSource !== oldSource;
  const isBusy = status.kind === "loading" || status.kind === "previewing";

  return (
    <div className="hot-compile-overlay" role="dialog" aria-label="hot compile preview">
      <div className="hot-compile-header">
        <div style={{ display: "flex", alignItems: "baseline" }}>
          <span className="hot-compile-title">热编译预览</span>
          <span className="hot-compile-subtitle">{componentPath}</span>
        </div>
        {onClose && (
          <button
            type="button"
            className="hot-compile-close"
            onClick={onClose}
            aria-label="close hot compile preview"
          >
            关闭
          </button>
        )}
      </div>

      <div className="hot-compile-body">
        <div className="hot-compile-pane">
          <div className="hot-compile-pane-header">
            <span>源码编辑器</span>
            <span className="hot-compile-pane-path">{componentPath}</span>
          </div>
          <div className="hot-compile-editor">
            <textarea
              value={newSource}
              onChange={(e) => setNewSource(e.target.value)}
              spellCheck={false}
              aria-label="component source editor"
              placeholder="// 在此编辑组件源码，点击预览查看渲染效果"
            />
          </div>
        </div>

        <div className="hot-compile-pane">
          <div className="hot-compile-pane-header">
            <span>沙箱预览</span>
            <span className="hot-compile-pane-path">iframe sandbox=allow-scripts</span>
          </div>
          <PreviewSandbox componentSource={newSource} />
        </div>

        <div className="hot-compile-pane" style={{ gridColumn: "1 / span 2" }}>
          <div className="hot-compile-pane-header">
            <span>差异对比（行级 diff）</span>
            <span className="hot-compile-pane-path">
              {diff.filter((d) => d.type === "added").length} added /{" "}
              {diff.filter((d) => d.type === "removed").length} removed
            </span>
          </div>
          <DiffViewer oldSource={oldSource} newSource={newSource} />
        </div>
      </div>

      <div className="hot-compile-footer">
        <div
          className={`hot-compile-status ${status.kind === "error" ? "error" : status.kind === "ok" ? "ok" : ""}`}
        >
          {status.kind === "idle" && "就绪"}
          {status.kind === "loading" && "加载中..."}
          {status.kind === "previewing" && "处理中..."}
          {status.kind === "ok" && status.message}
          {status.kind === "error" && "错误: " + status.message}
        </div>
        <div className="hot-compile-actions">
          <button
            type="button"
            className="hot-compile-btn"
            onClick={handlePreview}
            disabled={isBusy || !newSource}
            aria-label="refresh preview"
          >
            预览
          </button>
          <button
            type="button"
            className="hot-compile-btn primary"
            onClick={() => setConfirming(true)}
            disabled={isBusy || !hasChanges}
            aria-label="confirm hot replace"
          >
            确认替换
          </button>
        </div>
      </div>

      {confirming && (
        <div
          className="hot-compile-overlay"
          style={{
            position: "fixed",
            inset: 0,
            background: "rgba(0,0,0,0.5)",
            zIndex: 1500,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
          }}
          role="alertdialog"
          aria-label="confirm replace dialog"
        >
          <div
            style={{
              background: "#1a1f2e",
              border: "1px solid rgba(255,255,255,0.12)",
              borderRadius: 6,
              padding: 22,
              minWidth: 360,
              maxWidth: 480,
            }}
          >
            <div style={{ fontSize: 14, color: "#d7e0ea", marginBottom: 12 }}>
              确认替换 {componentPath}？
            </div>
            <div style={{ fontSize: 12, color: "#7a8699", marginBottom: 18 }}>
              原文件将备份到 .bak.{`{timestamp}`}，并写入见证迹。Vite HMR 将自动触发，无需重启。
            </div>
            <div style={{ display: "flex", justifyContent: "flex-end", gap: 10 }}>
              <button
                type="button"
                className="hot-compile-btn"
                onClick={() => setConfirming(false)}
              >
                取消
              </button>
              <button
                type="button"
                className="hot-compile-btn primary"
                onClick={handleReplace}
              >
                确认替换
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
