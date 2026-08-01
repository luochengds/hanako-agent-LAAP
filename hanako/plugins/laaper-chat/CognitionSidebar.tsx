/**
 * CognitionSidebar — 认知状态侧栏
 *
 * 三栏展示本机 LAAPer 的当前认知状态（数据从 sidecar /causal/* /vault/* /truth/* 拉，
 * 本组件做 UI 骨架，数据未就绪时显示 stub）。
 *
 * 数据源（vault 永不直接共享，仅本机检索结果）：
 * - causal: sidecar /causal/query 返回的近期因果链
 * - memory: sidecar /vault/retrieve 返回的近期记忆片段
 * - truth:  sidecar /truth/ground 返回的最新真值状态
 */

import { useEffect, useState } from "react";

export interface CognitionState {
  causal: string[];
  memory: string[];
  truth: string;
}

export interface CognitionSidebarProps {
  /** sidecar 基址 */
  sidecarEndpoint?: string;
  /** 本机 agent 名（用于 sidecar 查询） */
  agentName?: string;
  /** 可选：注入 fetch（测试用） */
  fetchImpl?: typeof fetch;
}

const DEFAULT_SIDECAR = "http://127.0.0.1:11521";

const EMPTY_STATE: CognitionState = { causal: [], memory: [], truth: "" };


export function CognitionSidebar({
  sidecarEndpoint = DEFAULT_SIDECAR,
  agentName = "",
  fetchImpl,
}: CognitionSidebarProps) {
  const fetchFn = fetchImpl || (typeof window !== "undefined" ? window.fetch.bind(window) : fetch);
  const [state, setState] = useState<CognitionState>(EMPTY_STATE);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    if (!agentName) return;
    setLoading(true);

    const safeGet = async (path: string): Promise<any> => {
      try {
        const r = await fetchFn(`${sidecarEndpoint}${path}`);
        return r.ok ? await r.json() : null;
      } catch {
        return null;
      }
    };

    Promise.all([
      safeGet(`/causal/query?agent=${encodeURIComponent(agentName)}&limit=5`),
      safeGet(`/vault/retrieve?agent=${encodeURIComponent(agentName)}&q=&limit=5`),
      safeGet(`/truth/ground?agent=${encodeURIComponent(agentName)}`),
    ]).then(([c, m, t]) => {
      if (cancelled) return;
      setState({
        causal: Array.isArray(c?.chains) ? c.chains.map((x: any) => String(x)) : [],
        memory: Array.isArray(m?.memories) ? m.memories.map((x: any) => String(x)) : [],
        truth: typeof t?.status === "string" ? t.status : "",
      });
      setLoading(false);
    });

    return () => { cancelled = true; };
  }, [agentName, sidecarEndpoint, fetchFn]);

  return (
    <div className="laaper-chat-sidebar">
      <div className="laaper-sidebar-title">认知状态侧栏</div>

      <div className="laaper-sidebar-section causal">
        <div className="laaper-sidebar-title">Causal 链</div>
        {loading && <div className="laaper-sidebar-empty">加载中…</div>}
        {!loading && state.causal.length === 0 && (
          <div className="laaper-sidebar-empty">无近期因果链</div>
        )}
        {state.causal.map((c, i) => (
          <div key={i} className="laaper-sidebar-item">{c}</div>
        ))}
      </div>

      <div className="laaper-sidebar-section memory">
        <div className="laaper-sidebar-title">Memory 片段</div>
        {loading && <div className="laaper-sidebar-empty">加载中…</div>}
        {!loading && state.memory.length === 0 && (
          <div className="laaper-sidebar-empty">无近期记忆</div>
        )}
        {state.memory.map((m, i) => (
          <div key={i} className="laaper-sidebar-item">{m}</div>
        ))}
      </div>

      <div className="laaper-sidebar-section truth">
        <div className="laaper-sidebar-title">Truth 状态</div>
        {loading && <div className="laaper-sidebar-empty">加载中…</div>}
        {!loading && (
          <div className="laaper-sidebar-item">{state.truth || "未就绪"}</div>
        )}
      </div>
    </div>
  );
}
