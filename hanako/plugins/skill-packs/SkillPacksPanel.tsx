/**
 * SkillPacksPanel — 技能包管理主面板
 *
 * 功能：
 * 1. 启动时 fetch GET /skills/list?agent_name=X 加载已安装 + 可用技能
 * 2. 可用技能列表渲染为 SkillCard 网格（含版本号 / 作者 / charter 徽章）
 * 3. 安装按钮 → POST /skills/install { agent_name, skill_id } → 重新拉取列表
 * 4. 卸载按钮 → POST /skills/uninstall { agent_name, skill_id } → 重新拉取列表
 * 5. 导出按钮 → POST /skills/export { skill_id } → 弹出 zip_path 提示
 * 6. 导入按钮 → POST /skills/import { zip_path }（zip_path 由用户输入） → 重新拉取列表
 *
 * Mineradio 风格：深色背景 + 卡片网格 + 强调色按钮
 */

import { useCallback, useEffect, useState } from "react";
import { SkillCard } from "./SkillCard";
import type {
  AvailableSkill,
  InstalledSkill,
  SkillListResponse,
  SkillPacksPanelProps,
} from "./types";
import "./skill-packs-styles.css";

type LoadState = "idle" | "loading" | "success" | "error";

export function SkillPacksPanel({
  sidecarEndpoint = "http://127.0.0.1:11521",
  agentName = "aris",
  onClose,
  fetchImpl,
}: SkillPacksPanelProps) {
  const fetchFn = fetchImpl || (typeof window !== "undefined" ? window.fetch.bind(window) : fetch);

  const [installed, setInstalled] = useState<InstalledSkill[]>([]);
  const [available, setAvailable] = useState<AvailableSkill[]>([]);
  const [loadState, setLoadState] = useState<LoadState>("idle");
  const [errorMsg, setErrorMsg] = useState<string>("");
  const [busySkillId, setBusySkillId] = useState<string>("");
  const [importZipPath, setImportZipPath] = useState<string>("");
  const [notice, setNotice] = useState<string>("");

  // ── 拉取技能列表 ──
  const refresh = useCallback(async () => {
    setLoadState("loading");
    setErrorMsg("");
    try {
      const url = `${sidecarEndpoint}/skills/list?agent_name=${encodeURIComponent(agentName)}`;
      const resp = await fetchFn(url, { method: "GET" });
      if (!resp.ok) {
        const errBody = await resp.json().catch(() => ({} as { error?: string }));
        throw new Error(errBody.error || `HTTP ${resp.status}`);
      }
      const data = (await resp.json()) as SkillListResponse;
      setInstalled(data.installed || []);
      setAvailable(data.available || []);
      setLoadState("success");
    } catch (e) {
      setErrorMsg(e instanceof Error ? e.message : String(e));
      setLoadState("error");
    }
  }, [sidecarEndpoint, agentName, fetchFn]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  // ── 操作：install ──
  const handleInstall = useCallback(
    async (skillId: string) => {
      setBusySkillId(skillId);
      setNotice("");
      try {
        const resp = await fetchFn(`${sidecarEndpoint}/skills/install`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ agent_name: agentName, skill_id: skillId }),
        });
        const body = await resp.json().catch(() => ({} as { error?: string }));
        if (!resp.ok) {
          throw new Error(body.error || `HTTP ${resp.status}`);
        }
        setNotice(`已安装: ${skillId}`);
        await refresh();
      } catch (e) {
        setErrorMsg(e instanceof Error ? e.message : String(e));
      } finally {
        setBusySkillId("");
      }
    },
    [sidecarEndpoint, agentName, fetchFn, refresh],
  );

  // ── 操作：uninstall ──
  const handleUninstall = useCallback(
    async (skillId: string) => {
      setBusySkillId(skillId);
      setNotice("");
      try {
        const resp = await fetchFn(`${sidecarEndpoint}/skills/uninstall`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ agent_name: agentName, skill_id: skillId }),
        });
        const body = await resp.json().catch(() => ({} as { error?: string }));
        if (!resp.ok) {
          throw new Error(body.error || `HTTP ${resp.status}`);
        }
        setNotice(`已卸载: ${skillId}`);
        await refresh();
      } catch (e) {
        setErrorMsg(e instanceof Error ? e.message : String(e));
      } finally {
        setBusySkillId("");
      }
    },
    [sidecarEndpoint, agentName, fetchFn, refresh],
  );

  // ── 操作：export ──
  const handleExport = useCallback(
    async (skillId: string) => {
      setBusySkillId(skillId);
      setNotice("");
      try {
        const resp = await fetchFn(`${sidecarEndpoint}/skills/export`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ skill_id: skillId }),
        });
        const body = await resp.json().catch(() => ({} as { error?: string; zip_path?: string }));
        if (!resp.ok) {
          throw new Error(body.error || `HTTP ${resp.status}`);
        }
        setNotice(`已导出: ${body.zip_path || skillId}`);
      } catch (e) {
        setErrorMsg(e instanceof Error ? e.message : String(e));
      } finally {
        setBusySkillId("");
      }
    },
    [sidecarEndpoint, fetchFn],
  );

  // ── 操作：import ──
  const handleImport = useCallback(async () => {
    if (!importZipPath.trim()) {
      setErrorMsg("请输入 zip 文件路径");
      return;
    }
    setBusySkillId("__import__");
    setNotice("");
    try {
      const resp = await fetchFn(`${sidecarEndpoint}/skills/import`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ zip_path: importZipPath.trim() }),
      });
      const body = await resp.json().catch(() => ({} as { error?: string; skill_id?: string }));
      if (!resp.ok) {
        throw new Error(body.error || `HTTP ${resp.status}`);
      }
      setNotice(`已导入: ${body.skill_id || importZipPath}`);
      setImportZipPath("");
      await refresh();
    } catch (e) {
      setErrorMsg(e instanceof Error ? e.message : String(e));
    } finally {
      setBusySkillId("");
    }
  }, [sidecarEndpoint, importZipPath, fetchFn, refresh]);

  const installedIds = new Set(installed.map((s) => s.skill_id));

  return (
    <div className="sp-overlay" data-testid="sp-overlay" role="dialog" aria-modal="true">
      <div className="sp-panel" data-testid="sp-panel">
        {/* 头部 */}
        <header className="sp-header">
          <h2 className="sp-title">技能包管理</h2>
          <div className="sp-header-meta">
            <span className="sp-agent-label">agent:</span>
            <span className="sp-agent-name" data-testid="sp-agent-name">{agentName}</span>
          </div>
          {onClose && (
            <button
              className="sp-close-btn"
              data-testid="sp-close-btn"
              onClick={onClose}
              aria-label="关闭技能包管理"
            >
              ×
            </button>
          )}
        </header>

        {/* 工具栏：导入新技能包 */}
        <div className="sp-toolbar" data-testid="sp-toolbar">
          <input
            className="sp-input"
            data-testid="sp-import-input"
            type="text"
            placeholder="zip 文件绝对路径..."
            value={importZipPath}
            onChange={(e) => setImportZipPath(e.target.value)}
            disabled={busySkillId === "__import__"}
          />
          <button
            className="sp-btn sp-btn-import"
            data-testid="sp-btn-import"
            onClick={handleImport}
            disabled={busySkillId === "__import__" || !importZipPath.trim()}
          >
            导入
          </button>
          <button
            className="sp-btn sp-btn-refresh"
            data-testid="sp-btn-refresh"
            onClick={refresh}
            disabled={loadState === "loading"}
          >
            刷新
          </button>
        </div>

        {/* 通知 / 错误 */}
        {notice ? (
          <div className="sp-notice" data-testid="sp-notice">{notice}</div>
        ) : null}
        {errorMsg ? (
          <div className="sp-error" data-testid="sp-error">{errorMsg}</div>
        ) : null}

        {/* 已安装区 */}
        <section className="sp-section" data-testid="sp-section-installed">
          <h3 className="sp-section-title">
            已安装（{installed.length}）
          </h3>
          {loadState === "loading" && installed.length === 0 ? (
            <div className="sp-empty" data-testid="sp-installed-loading">加载中...</div>
          ) : installed.length === 0 ? (
            <div className="sp-empty" data-testid="sp-installed-empty">尚未安装任何技能包</div>
          ) : (
            <ul className="sp-installed-list" data-testid="sp-installed-list">
              {installed.map((s) => (
                <li key={s.skill_id} className="sp-installed-item" data-testid={`sp-installed-${s.skill_id}`}>
                  <span className="sp-installed-name">{s.skill_id}</span>
                  <span className="sp-installed-version">v{s.version}</span>
                  {s.author ? <span className="sp-installed-author">by {s.author}</span> : null}
                  <span className="sp-installed-at">installed at {s.installed_at}</span>
                </li>
              ))}
            </ul>
          )}
        </section>

        {/* 可用区 */}
        <section className="sp-section" data-testid="sp-section-available">
          <h3 className="sp-section-title">
            可用技能包（{available.length}）
          </h3>
          {loadState === "loading" && available.length === 0 ? (
            <div className="sp-empty" data-testid="sp-available-loading">加载中...</div>
          ) : available.length === 0 ? (
            <div className="sp-empty" data-testid="sp-available-empty">
              未扫描到任何可用技能包（请在 laap/skills/{`{skill_id}`}/manifest.json 添加）
            </div>
          ) : (
            <div className="sp-card-grid" data-testid="sp-card-grid">
              {available.map((s) => (
                <SkillCard
                  key={s.skill_id}
                  skill={s}
                  installed={installedIds.has(s.skill_id)}
                  onInstall={handleInstall}
                  onUninstall={handleUninstall}
                  onExport={handleExport}
                  busy={busySkillId === s.skill_id}
                />
              ))}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
