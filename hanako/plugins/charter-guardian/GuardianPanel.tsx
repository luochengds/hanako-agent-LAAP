/**
 * GuardianPanel — 宪章守护者治理面板（P4-charter-guardian）
 *
 * 布局：社区健康仪表盘（顶部）+ 行使表单（左侧）+ 行使记录时间线（右侧）.
 *
 * 流程（spec L364-369）：
 * 1. 挂载时拉取 /guardian/stats + /guardian/list 渲染仪表盘 + 历史
 * 2. 用户在表单选择 action + 填写 target/reason → POST /guardian/act
 * 3. 行使成功后刷新 stats + list，时间线显示新记录（含 trail_id 徽章）
 * 4. 守护者注册子表单：public_key → POST /guardian/register（仅 sidecar）
 * 5. 30 秒轮询刷新 stats（实时反映其他守护者的行使）
 *
 * 安全（spec L435 硬约束）：
 * - 私钥永不离开 sidecar：本面板不传 guardian_private_key_b64
 *   （签名仅在 sidecar 内部完成，UI 不暴露私钥输入）
 * - 行使记录不可篡改：每条记录含 trail_id + trail_hash（链式 SHA-256）
 * - 白名单校验：未注册公钥调用 /guardian/act 返回 unauthorized
 *
 * Mineradio 风格：深色背景 + 守护主题色
 *   suspend 橙 / warn 黄 / expel 红 / restore 绿
 */

import { useCallback, useEffect, useRef, useState } from "react";
import type {
  GuardianAction,
  GuardianAct,
  GuardianStats,
  GuardianActResult,
  GuardianRegisterResult,
  TargetStatus,
} from "./types";
import "./guardian-styles.css";

const DEFAULT_SIDECAR = "http://127.0.0.1:11521";

export interface GuardianPanelProps {
  /** 本机 LAAPer 公钥（用于默认填入 guardian_public_key 字段） */
  selfPublicKey?: string;
  /** 本机 LAAPer 名（仅用于显示） */
  selfName?: string;
  /** sidecar 端点基址 */
  sidecarEndpoint?: string;
  /** 可选：注入 fetch 实现（测试用） */
  fetchImpl?: typeof fetch;
  /** 关闭回调 */
  onClose: () => void;
}

type Status =
  | { kind: "idle" }
  | { kind: "loading"; message?: string }
  | { kind: "ok"; message: string }
  | { kind: "error"; message: string };

const ACTION_LABELS: Record<GuardianAction, string> = {
  suspend: "暂停",
  warn: "警告",
  expel: "封禁",
  restore: "恢复",
};

const ACTION_COLORS: Record<GuardianAction, string> = {
  suspend: "guardian-action-suspend",
  warn: "guardian-action-warn",
  expel: "guardian-action-expel",
  restore: "guardian-action-restore",
};

const STATUS_LABELS: Record<TargetStatus, string> = {
  active: "活跃",
  suspended: "已暂停",
  warned: "已警告",
  expelled: "已封禁",
  restored: "已恢复",
};

export function GuardianPanel({
  selfPublicKey = "",
  selfName = "",
  sidecarEndpoint = DEFAULT_SIDECAR,
  fetchImpl,
  onClose,
}: GuardianPanelProps) {
  const fetchFn = fetchImpl || (typeof window !== "undefined" ? window.fetch.bind(window) : fetch);
  const [stats, setStats] = useState<GuardianStats | null>(null);
  const [acts, setActs] = useState<GuardianAct[]>([]);
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState<Status>({ kind: "idle" });

  // 行使表单状态
  const [action, setAction] = useState<GuardianAction>("warn");
  const [target, setTarget] = useState("");
  const [reason, setReason] = useState("");
  const [guardianPublicKey, setGuardianPublicKey] = useState(selfPublicKey);
  const [acting, setActing] = useState(false);

  // 守护者注册表单状态
  const [registerPk, setRegisterPk] = useState(selfPublicKey);
  const [registering, setRegistering] = useState(false);

  const refreshTimerRef = useRef<number | null>(null);

  // ── 拉取 stats + list ──
  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [statsRes, listRes] = await Promise.all([
        fetchFn(`${sidecarEndpoint}/guardian/stats`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: "{}",
        }),
        fetchFn(`${sidecarEndpoint}/guardian/list`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ limit: 50 }),
        }),
      ]);
      if (statsRes.ok) {
        const s = await statsRes.json();
        setStats(s);
      }
      if (listRes.ok) {
        const l = await listRes.json();
        setActs(l.acts || []);
      }
    } catch (e) {
      // 静默降级：sidecar 离线时保持空状态
      // eslint-disable-next-line no-console
      console.warn("GuardianPanel refresh failed:", e);
    } finally {
      setLoading(false);
    }
  }, [fetchFn, sidecarEndpoint]);

  useEffect(() => {
    refresh();
    // 30 秒轮询刷新 stats
    refreshTimerRef.current = window.setInterval(refresh, 30000);
    return () => {
      if (refreshTimerRef.current) {
        window.clearInterval(refreshTimerRef.current);
      }
    };
  }, [refresh]);

  // ── 行使守护权力 ──
  const handleAct = useCallback(async () => {
    if (!target.trim() || !reason.trim() || !guardianPublicKey.trim()) {
      setStatus({ kind: "error", message: "请填写 target / reason / guardian_public_key" });
      return;
    }
    setActing(true);
    setStatus({ kind: "loading", message: "行使中..." });
    try {
      const res = await fetchFn(`${sidecarEndpoint}/guardian/act`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          action,
          target: target.trim(),
          reason: reason.trim(),
          guardian_public_key: guardianPublicKey.trim(),
          // guardian_private_key_b64 不在 UI 暴露（spec L435 私钥永不离开 sidecar）
        }),
      });
      const result: GuardianActResult = await res.json();
      if (result.acted) {
        setStatus({
          kind: "ok",
          message: `已行使 ${ACTION_LABELS[action]} → ${target}（trail: ${result.trail_id?.slice(0, 16)}...）`,
        });
        setTarget("");
        setReason("");
        await refresh();
      } else {
        const failReason = result.reason_if_failed || result.error || "行使失败";
        setStatus({ kind: "error", message: `${failReason}${result.reason ? `（${result.reason}）` : ""}` });
      }
    } catch (e) {
      setStatus({ kind: "error", message: `网络错误: ${e}` });
    } finally {
      setActing(false);
    }
  }, [action, target, reason, guardianPublicKey, fetchFn, sidecarEndpoint]);

  // ── 注册守护者 ──
  const handleRegister = useCallback(async () => {
    if (!registerPk.trim()) {
      setStatus({ kind: "error", message: "请填写 public_key" });
      return;
    }
    setRegistering(true);
    setStatus({ kind: "loading", message: "注册守护者..." });
    try {
      const res = await fetchFn(`${sidecarEndpoint}/guardian/register`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ public_key: registerPk.trim() }),
      });
      const result: GuardianRegisterResult = await res.json();
      if (result.registered) {
        setStatus({
          kind: "ok",
          message: `守护者已注册（共 ${result.total_guardians} 位守护者）`,
        });
        await refresh();
      } else {
        setStatus({ kind: "error", message: `注册失败: ${result.reason || result.error}` });
      }
    } catch (e) {
      setStatus({ kind: "error", message: `网络错误: ${e}` });
    } finally {
      setRegistering(false);
    }
  }, [registerPk, fetchFn, sidecarEndpoint]);

  return (
    <div className="guardian-panel-overlay" role="dialog" aria-label="宪章守护者治理面板">
      <div className="guardian-panel-container">
        <header className="guardian-panel-header">
          <h2>宪章守护者 · Charter Guardian</h2>
          <div className="guardian-panel-subtitle">
            {selfName ? `当前守护者: ${selfName}` : "未署名守护者"}
            <span className="guardian-panel-status-dot" aria-hidden="true" />
          </div>
          <button className="guardian-panel-close" onClick={onClose} aria-label="关闭">
            ×
          </button>
        </header>

        {/* ── 社区健康仪表盘 ── */}
        <section className="guardian-dashboard">
          <h3>社区健康仪表盘</h3>
          {stats ? (
            <div className="guardian-dashboard-grid">
              <div className="guardian-metric">
                <span className="guardian-metric-label">总行使次数</span>
                <span className="guardian-metric-value">{stats.total_acts}</span>
              </div>
              <div className="guardian-metric">
                <span className="guardian-metric-label">活跃守护者</span>
                <span className="guardian-metric-value">{stats.active_guardians}</span>
              </div>
              <div className="guardian-metric">
                <span className="guardian-metric-label">跟踪目标数</span>
                <span className="guardian-metric-value">{stats.targets_count}</span>
              </div>
              <div className="guardian-metric">
                <span className="guardian-metric-label">近期滥用事件</span>
                <span className="guardian-metric-value">
                  {stats.recent_abuse_events.length}
                </span>
              </div>
            </div>
          ) : (
            <div className="guardian-empty">{loading ? "加载中..." : "暂无数据"}</div>
          )}

          {/* 目标状态快照 */}
          {stats && stats.target_status_snapshot && (
            <div className="guardian-status-snapshot">
              <h4>目标状态分布</h4>
              <div className="guardian-status-pills">
                {Object.entries(stats.target_status_snapshot).map(([status, count]) => (
                  <span
                    key={status}
                    className={`guardian-status-pill guardian-status-${status}`}
                    title={`${status}: ${count}`}
                  >
                    {STATUS_LABELS[status as TargetStatus] || status}: {count}
                  </span>
                ))}
                {Object.keys(stats.target_status_snapshot).length === 0 && (
                  <span className="guardian-empty-inline">无</span>
                )}
              </div>
            </div>
          )}

          {/* action 分布 */}
          {stats && stats.by_action && (
            <div className="guardian-action-distribution">
              <h4>action 分布</h4>
              <div className="guardian-action-bars">
                {(Object.entries(stats.by_action) as [GuardianAction, number][])
                  .map(([a, count]) => (
                    <div
                      key={a}
                      className={`guardian-action-bar ${ACTION_COLORS[a]}`}
                      title={`${ACTION_LABELS[a]}: ${count}`}
                    >
                      <span className="guardian-action-bar-label">
                        {ACTION_LABELS[a]}
                      </span>
                      <span className="guardian-action-bar-count">{count}</span>
                    </div>
                  ))}
              </div>
            </div>
          )}
        </section>

        <div className="guardian-panel-body">
          {/* ── 左：行使表单 + 守护者注册 ── */}
          <section className="guardian-form-section">
            <h3>行使守护权力</h3>
            <p className="guardian-form-hint">
              每次行使将写入见证迹（不可篡改），事后无法删除。
            </p>
            <label className="guardian-form-field">
              <span>Action</span>
              <select
                value={action}
                onChange={(e) => setAction(e.target.value as GuardianAction)}
                className="guardian-action-select"
              >
                <option value="warn">警告 (warn)</option>
                <option value="suspend">暂停 (suspend)</option>
                <option value="expel">封禁 (expel)</option>
                <option value="restore">恢复 (restore)</option>
              </select>
            </label>
            <label className="guardian-form-field">
              <span>Target (目标 agent)</span>
              <input
                type="text"
                value={target}
                onChange={(e) => setTarget(e.target.value)}
                placeholder="如 agent_X 或 LAAPer 公钥"
              />
            </label>
            <label className="guardian-form-field">
              <span>Reason (行使理由)</span>
              <textarea
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                placeholder="描述行使理由，将永久记录..."
                rows={3}
              />
            </label>
            <label className="guardian-form-field">
              <span>守护者公钥 (guardian_public_key)</span>
              <input
                type="text"
                value={guardianPublicKey}
                onChange={(e) => setGuardianPublicKey(e.target.value)}
                placeholder="base64 Ed25519 公钥（必须在白名单中）"
              />
            </label>
            <button
              className="guardian-act-button"
              onClick={handleAct}
              disabled={acting || !target.trim() || !reason.trim() || !guardianPublicKey.trim()}
            >
              {acting ? "行使中..." : `行使 ${ACTION_LABELS[action]}`}
            </button>

            <hr className="guardian-divider" />

            <h3>注册守护者公钥</h3>
            <p className="guardian-form-hint">
              将公钥加入白名单（仅 sidecar 端点，不暴露为 MCP 工具）。
            </p>
            <label className="guardian-form-field">
              <span>Public Key</span>
              <input
                type="text"
                value={registerPk}
                onChange={(e) => setRegisterPk(e.target.value)}
                placeholder="base64 Ed25519 公钥"
              />
            </label>
            <button
              className="guardian-register-button"
              onClick={handleRegister}
              disabled={registering || !registerPk.trim()}
            >
              {registering ? "注册中..." : "注册守护者"}
            </button>

            {status.kind !== "idle" && (
              <div
                className={`guardian-status-box guardian-status-${status.kind}`}
                role="status"
              >
                {status.message}
              </div>
            )}
          </section>

          {/* ── 右：行使记录时间线 + 近期滥用事件 ── */}
          <section className="guardian-timeline-section">
            <h3>
              行使记录时间线
              <button
                className="guardian-refresh-button"
                onClick={refresh}
                disabled={loading}
                aria-label="刷新"
              >
                {loading ? "..." : "↻"}
              </button>
            </h3>
            {acts.length === 0 ? (
              <div className="guardian-empty">暂无行使记录</div>
            ) : (
              <ul className="guardian-timeline-list">
                {acts.map((act) => (
                  <li
                    key={act.act_id}
                    className={`guardian-timeline-item ${ACTION_COLORS[act.action]}`}
                  >
                    <div className="guardian-timeline-header">
                      <span className="guardian-timeline-action">
                        {ACTION_LABELS[act.action]}
                      </span>
                      <span className="guardian-timeline-target">{act.target}</span>
                      <span className="guardian-timeline-time">
                        {new Date((act.timestamp || 0) * 1000).toLocaleString()}
                      </span>
                    </div>
                    <div className="guardian-timeline-reason">{act.reason}</div>
                    <div className="guardian-timeline-meta">
                      <span className="guardian-timeline-status">
                        {STATUS_LABELS[act.previous_status]} →{" "}
                        {STATUS_LABELS[act.new_status]}
                      </span>
                      <span
                        className="guardian-timeline-trail"
                        title={act.trail_id}
                      >
                        trail: {act.trail_id.slice(0, 20)}...
                      </span>
                    </div>
                  </li>
                ))}
              </ul>
            )}

            {stats && stats.recent_abuse_events.length > 0 && (
              <div className="guardian-abuse-section">
                <h4>近期滥用事件</h4>
                <ul className="guardian-abuse-list">
                  {stats.recent_abuse_events.slice(0, 10).map((ev) => (
                    <li
                      key={ev.act_id}
                      className={`guardian-abuse-item ${ACTION_COLORS[ev.action]}`}
                    >
                      <span className="guardian-abuse-action">
                        {ACTION_LABELS[ev.action]}
                      </span>
                      <span className="guardian-abuse-target">{ev.target}</span>
                      <span className="guardian-abuse-time">
                        {new Date((ev.timestamp || 0) * 1000).toLocaleString()}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}
