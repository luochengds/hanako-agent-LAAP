/**
 * PreviewSandbox — 隔离 iframe 渲染组件源码
 *
 * 在 sandbox="allow-scripts" 的 iframe 中通过 srcDoc 注入完整 HTML 文档，
 * 主应用 DOM 不受影响（spec L262-269 + tasks SubTask 2.2）。
 *
 * 简化实现（spec 明示："本阶段不要求完整 JSX 转译"）：
 * - 若源码是纯 HTML（以 <!DOCTYPE 或 <html> 开头），直接当完整文档渲染
 * - 若含 JSX 标记，尝试用 Babel standalone CDN 转译 + React UMD 渲染
 * - 否则用 eval 在 iframe 内执行（受 iframe sandbox 隔离）
 * - 网络不可用 / Babel 加载失败时降级为源码 <pre> 显示
 *
 * 安全：仅用于本地开发预览。iframe sandbox="allow-scripts" 隔离主应用，
 * 但 srcDoc 中的脚本仍可发起同源请求；切勿用于渲染不可信第三方代码。
 */

import { useEffect, useMemo, useRef, useState } from "react";

export interface PreviewSandboxProps {
  /** 组件源码（TSX/JSX/HTML 字符串）。空字符串时渲染空白预览。 */
  componentSource: string;
  /** 可选：React UMD CDN URL（默认 unpkg React 18 development） */
  reactCdnUrl?: string;
  /** 可选：ReactDOM UMD CDN URL（默认 unpkg React DOM 18 development） */
  reactDomCdnUrl?: string;
  /** 可选：Babel standalone CDN URL（默认 unpkg） */
  babelCdnUrl?: string;
  /** 可选：注入到 iframe <head> 的额外 CSS */
  extraCss?: string;
}

const DEFAULT_REACT_CDN = "https://unpkg.com/react@18/umd/react.development.js";
const DEFAULT_REACT_DOM_CDN = "https://unpkg.com/react-dom@18/umd/react-dom.development.js";
const DEFAULT_BABEL_CDN = "https://unpkg.com/@babel/standalone/babel.min.js";

/**
 * 预处理源码：剥离 import/export/interface/type 声明行，保留函数体。
 * 极简化处理，仅用于本地预览；复杂 TS 泛型 / 嵌套类型可能无法完全剥离。
 */
function preprocessSource(source: string): string {
  return source
    .split("\n")
    .filter((line) => {
      const trimmed = line.trim();
      if (/^(import|export)\s/.test(trimmed)) return false;
      if (/^(export\s+)?(interface|type)\s+\w+/.test(trimmed)) return false;
      return true;
    })
    .join("\n");
}

/**
 * 判断是否是纯 HTML 文档（直接当完整文档渲染，不再包裹）。
 */
function isPureHtml(source: string): boolean {
  const trimmed = source.trim().toLowerCase();
  return trimmed.startsWith("<!doctype") || trimmed.startsWith("<html");
}

/**
 * 检测源码是否含 JSX 标记（如 <Component 或 <div>）。
 */
function hasJsx(source: string): boolean {
  return /<[A-Za-z][\w.]*[\s/>]/.test(source);
}

/**
 * 构造 iframe srcDoc 内容。
 */
function buildSrcDoc(
  source: string,
  reactCdn: string,
  reactDomCdn: string,
  babelCdn: string,
  extraCss?: string,
): string {
  if (!source.trim()) {
    return `<!DOCTYPE html><html><head><meta charset="utf-8"></head><body></body></html>`;
  }
  if (isPureHtml(source)) {
    return source;
  }
  const preprocessed = preprocessSource(source);
  const cssBlock = extraCss ? `<style>${extraCss}</style>` : "";
  const baseStyles =
    "body{font-family:-apple-system,sans-serif;padding:16px;color:#222;margin:0}" +
    "#error{color:#c33;font-family:monospace;white-space:pre-wrap;padding:8px 16px}" +
    "#src-fallback{font-family:monospace;white-space:pre;color:#444;padding:8px 16px}";

  if (!hasJsx(preprocessed)) {
    // 无 JSX，直接 eval（在 iframe 内受 sandbox 隔离）
    return `<!DOCTYPE html>
<html>
<head><meta charset="utf-8">${cssBlock}
<style>${baseStyles}</style>
</head>
<body>
<div id="root"></div>
<div id="error"></div>
<script>
window.onerror = function(msg, src, line, col, err) {
  var e = document.getElementById('error');
  if (e) e.textContent = 'Error: ' + (err && err.stack || msg);
  if (window.parent) window.parent.postMessage({__previewError: true, message: String(err && err.stack || msg)}, '*');
};
try {
${preprocessed}
} catch (e) {
  var el = document.getElementById('error');
  if (el) el.textContent = (e && e.stack) || String(e);
}
</script>
</body>
</html>`;
  }

  // 含 JSX，用 Babel standalone 转译 + React UMD 渲染
  return `<!DOCTYPE html>
<html>
<head><meta charset="utf-8">${cssBlock}
<style>${baseStyles}</style>
</head>
<body>
<div id="root"></div>
<div id="error"></div>
<div id="src-fallback" style="display:none"></div>
<script src="${reactCdn}" crossorigin></script>
<script src="${reactDomCdn}" crossorigin></script>
<script src="${babelCdn}" crossorigin></script>
<script>
window.onerror = function(msg, src, line, col, err) {
  var e = document.getElementById('error');
  if (e) e.textContent = 'Error: ' + (err && err.stack || msg);
  if (window.parent) window.parent.postMessage({__previewError: true, message: String(err && err.stack || msg)}, '*');
};
function showFallback() {
  var f = document.getElementById('src-fallback');
  if (f) { f.style.display = 'block'; f.textContent = ${JSON.stringify(preprocessed)}; }
}
if (typeof Babel === 'undefined') {
  showFallback();
} else {
  try {
    var transformed = Babel.transform(${JSON.stringify(preprocessed)}, {presets: ['react']}).code;
    var fn = new Function('React', 'ReactDOM', transformed + '\\nreturn (typeof App !== "undefined") ? App : (typeof default !== "undefined" ? default : null);');
    var rootEl = document.getElementById('root');
    if (rootEl && typeof ReactDOM !== 'undefined' && ReactDOM.createRoot) {
      var root = ReactDOM.createRoot(rootEl);
      var Comp = fn(React, ReactDOM);
      if (Comp) root.render(React.createElement(Comp));
    }
  } catch (e) {
    var el = document.getElementById('error');
    if (el) el.textContent = (e && e.stack) || String(e);
    showFallback();
  }
}
</script>
</body>
</html>`;
}

export function PreviewSandbox({
  componentSource,
  reactCdnUrl,
  reactDomCdnUrl,
  babelCdnUrl,
  extraCss,
}: PreviewSandboxProps) {
  const iframeRef = useRef<HTMLIFrameElement | null>(null);
  const [error, setError] = useState<string | null>(null);

  const reactCdn = reactCdnUrl || DEFAULT_REACT_CDN;
  const reactDomCdn = reactDomCdnUrl || DEFAULT_REACT_DOM_CDN;
  const babelCdn = babelCdnUrl || DEFAULT_BABEL_CDN;

  const srcDoc = useMemo(
    () => buildSrcDoc(componentSource || "", reactCdn, reactDomCdn, babelCdn, extraCss),
    [componentSource, reactCdn, reactDomCdn, babelCdn, extraCss],
  );

  useEffect(() => {
    function onMessage(ev: MessageEvent) {
      if (ev.data && typeof ev.data === "object" && ev.data.__previewError) {
        setError(String(ev.data.message || ""));
      }
    }
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, []);

  return (
    <div
      className="hot-compile-preview-wrapper"
      style={{ display: "flex", flex: 1, minHeight: 0, flexDirection: "column" }}
    >
      <iframe
        ref={iframeRef}
        className="hot-compile-preview-frame"
        title="component-preview"
        sandbox="allow-scripts"
        srcDoc={srcDoc}
      />
      {error && (
        <div
          className="hot-compile-status error"
          style={{ padding: "4px 12px", fontSize: "11px" }}
        >
          {error}
        </div>
      )}
    </div>
  );
}
