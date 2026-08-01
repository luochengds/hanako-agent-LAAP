/**
 * MarketBrowser — LAAPer 市场浏览组件 (P5-laaper-market)
 *
 * 布局: 顶部标题栏 + 预设卡片网格 + 克隆弹窗.
 *
 * 流程:
 * 1. 挂载时 fetch /preset/list 获取全部社区预设包
 * 2. 卡片网格展示 名称 / 描述 / 主题色 / 性格标签 (yuan + ishiki)
 * 3. 点击卡片"克隆"按钮 → 弹出克隆弹窗
 * 4. 弹窗输入新名称 + 可选性格自定义 (yuan/ishiki/color)
 * 5. 确认克隆 → POST /preset/clone → 成功后 onClone(config) 切换 birth-ceremony
 *
 * 设计约束:
 * - 克隆不直接创建身份: 仅拿到配置后交给 onClone 回调,
 *   由父组件切换到 birth-ceremony 完成身份创建与公钥签发.
 * - 端点幂等: list 可重复拉取, clone 不写盘仅返回配置.
 *
 * Mineradio 风格: 深色背景 + 各预设主题色点缀.
 */

import { useCallback, useEffect, useState } from "react";
import type {
  PresetPack,
  CloneResult,
  CloneFormState,
  PresetErrorResponse,
} from "./types";
import "./market-styles.css";

const DEFAULT_SIDECAR = "http://127.0.0.1:11521";

export interface MarketBrowserProps {
  /** sidecar 端点基址 */
  sidecarEndpoint?: string;
  /** 可选: 注入 fetch 实现 (测试用) */
  fetchImpl?: typeof fetch;
  /** 关闭回调 */
  onClose: () => void;
  /** 克隆成功回调: 把配置交给父组件切换到 birth-ceremony */
  onClone: (config: CloneResult["config"]) => void;
}

type LoadStatus =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "ok" }
  | { kind: "error"; message: string };

type CloneStatus =
  | { kind: "idle" }
  | { kind: "submitting" }
  | { kind: "error"; message: string };

/** 性格标签拆分: "理性/好奇/创造" → ["理性","好奇","创造"] */
function splitTags(s: string): string[] {
  return s
    .split(/[\/,，、]/)
    .map((t) => t.trim())
    .filter(Boolean);
}

export function MarketBrowser({
  sidecarEndpoint = DEFAULT_SIDECAR,
  fetchImpl,
  onClose,
  onClone,
}: MarketBrowserProps) {
  const fetchFn =
    fetchImpl || (typeof window !== "undefined" ? window.fetch.bind(window) : fetch);

  const [presets, setPresets] = useState<PresetPack[]>([]);
  const [loadStatus, setLoadStatus] = useState<LoadStatus>({ kind: "idle" });

  // 克隆弹窗状态
  const [cloneTarget, setCloneTarget] = useState<PresetPack | null>(null);
  const [cloneForm, setCloneForm] = useState<CloneFormState>({
    newName: "",
    customYuan: "",
    customIshiki: "",
    customColor: "",
    enableCustom: false,
  });
  const [cloneStatus, setCloneStatus] = useState<CloneStatus>({ kind: "idle" });

  // ── 拉取预设列表 ──
  const fetchPresets = useCallback(async () => {
    setLoadStatus({ kind: "loading" });
    try {
      const resp = await fetchFn(`${sidecarEndpoint}/preset/list`);
      const data = await resp.json();
      if (!resp.ok) {
        const err = data as PresetErrorResponse;
        setLoadStatus({
          kind: "error",
          message: err.error || `HTTP ${resp.status}`,
        });
        return;
      }
      setPresets(data.presets || []);
      setLoadStatus({ kind: "ok" });
    } catch (e) {
      setLoadStatus({
        kind: "error",
        message: e instanceof Error ? e.message : String(e),
      });
    }
  }, [fetchFn, sidecarEndpoint]);

  useEffect(() => {
    void fetchPresets();
  }, [fetchPresets]);

  // ── 打开克隆弹窗 ──
  const openCloneModal = useCallback((preset: PresetPack) => {
    setCloneTarget(preset);
    setCloneForm({
      newName: "",
      customYuan: preset.yuan,
      customIshiki: preset.ishiki,
      customColor: preset.color,
      enableCustom: false,
    });
    setCloneStatus({ kind: "idle" });
  }, []);

  // ── 关闭克隆弹窗 ──
  const closeCloneModal = useCallback(() => {
    setCloneTarget(null);
    setCloneStatus({ kind: "idle" });
  }, []);

  // ── 提交克隆 ──
  const submitClone = useCallback(async () => {
    if (!cloneTarget) return;
    const newName = cloneForm.newName.trim();
    if (!newName) {
      setCloneStatus({ kind: "error", message: "请输入新 LAAPer 名称" });
      return;
    }

    const body: Record<string, unknown> = {
      preset_id: cloneTarget.id,
      new_name: newName,
    };
    if (cloneForm.enableCustom) {
      body.customizations = {
        yuan: cloneForm.customYuan.trim() || undefined,
        ishiki: cloneForm.customIshiki.trim() || undefined,
        color: cloneForm.customColor.trim() || undefined,
      };
    }

    setCloneStatus({ kind: "submitting" });
    try {
      const resp = await fetchFn(`${sidecarEndpoint}/preset/clone`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await resp.json();
      if (!resp.ok) {
        const err = data as PresetErrorResponse;
        setCloneStatus({
          kind: "error",
          message: err.error || `HTTP ${resp.status}`,
        });
        return;
      }
      const result = data as CloneResult;
      if (!result.cloned || !result.config) {
        setCloneStatus({
          kind: "error",
          message: "克隆响应格式异常",
        });
        return;
      }
      // 克隆成功: 关闭弹窗, 通过 onClone 把配置交给父组件
      closeCloneModal();
      onClone(result.config);
    } catch (e) {
      setCloneStatus({
        kind: "error",
        message: e instanceof Error ? e.message : String(e),
      });
    }
  }, [cloneTarget, cloneForm, fetchFn, sidecarEndpoint, onClone, closeCloneModal]);

  return (
    <div className="market-overlay" role="dialog" aria-label="LAAPer 市场">
      <div className="market-container">
        {/* ── Header ── */}
        <div className="market-header">
          <h2>LAAPer 市场</h2>
          <span className="market-subtitle">
            社区示例预设包 · 一键克隆并自定义
          </span>
          <button
            className="market-close"
            onClick={onClose}
            aria-label="关闭"
            title="关闭"
          >
            ×
          </button>
        </div>

        {/* ── Body: 预设卡片网格 ── */}
        <div className="market-body">
          {loadStatus.kind === "loading" && (
            <div className="market-placeholder">加载预设包中…</div>
          )}
          {loadStatus.kind === "error" && (
            <div className="market-placeholder market-placeholder-error">
              加载失败: {loadStatus.message}
              <button className="market-retry" onClick={() => void fetchPresets()}>
                重试
              </button>
            </div>
          )}
          {loadStatus.kind === "ok" && presets.length === 0 && (
            <div className="market-placeholder">暂无可用预设包</div>
          )}
          {loadStatus.kind === "ok" && presets.length > 0 && (
            <div className="market-grid">
              {presets.map((preset) => {
                const yuanTags = splitTags(preset.yuan);
                return (
                  <div
                    key={preset.id}
                    className="market-card"
                    style={
                      {
                        "--preset-color": preset.color,
                      } as React.CSSProperties
                    }
                  >
                    <div className="market-card-accent" />
                    <div className="market-card-head">
                      <span className="market-card-avatar" title={preset.avatar_seed}>
                        {preset.name.charAt(0)}
                      </span>
                      <div className="market-card-title">
                        <h3>{preset.name}</h3>
                        <span className="market-card-id">#{preset.id}</span>
                      </div>
                    </div>
                    <p className="market-card-desc">{preset.description}</p>
                    <div className="market-card-tags">
                      {yuanTags.map((tag) => (
                        <span key={tag} className="market-tag market-tag-yuan">
                          {tag}
                        </span>
                      ))}
                      <span className="market-tag market-tag-ishiki">
                        {preset.ishiki}
                      </span>
                    </div>
                    <div className="market-card-meta">
                      <span className="market-meta-item">
                        初始技能:{" "}
                        {preset.initial_skills.length > 0
                          ? preset.initial_skills.join(", ")
                          : "无"}
                      </span>
                      <span className="market-meta-item">
                        宪章 {preset.charter_version}
                      </span>
                    </div>
                    <button
                      className="market-clone-btn"
                      onClick={() => openCloneModal(preset)}
                    >
                      克隆此预设
                    </button>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>

      {/* ── 克隆弹窗 ── */}
      {cloneTarget && (
        <div
          className="market-clone-modal-overlay"
          role="dialog"
          aria-label={`克隆 ${cloneTarget.name}`}
        >
          <div
            className="market-clone-modal"
            style={
              {
                "--preset-color": cloneTarget.color,
              } as React.CSSProperties
            }
          >
            <div className="market-clone-header">
              <h3>克隆 {cloneTarget.name}</h3>
              <button
                className="market-close"
                onClick={closeCloneModal}
                aria-label="关闭"
              >
                ×
              </button>
            </div>
            <div className="market-clone-body">
              <label className="market-field">
                <span className="market-field-label">新 LAAPer 名称 *</span>
                <input
                  className="market-input"
                  type="text"
                  value={cloneForm.newName}
                  onChange={(e) =>
                    setCloneForm({ ...cloneForm, newName: e.target.value })
                  }
                  placeholder="为你的 LAAPer 起个名字"
                  autoFocus
                />
              </label>

              <label className="market-checkbox-row">
                <input
                  type="checkbox"
                  checked={cloneForm.enableCustom}
                  onChange={(e) =>
                    setCloneForm({ ...cloneForm, enableCustom: e.target.checked })
                  }
                />
                <span>自定义性格 (覆盖预设默认值)</span>
              </label>

              {cloneForm.enableCustom && (
                <div className="market-custom-fields">
                  <label className="market-field">
                    <span className="market-field-label">性格核心 (yuan)</span>
                    <input
                      className="market-input"
                      type="text"
                      value={cloneForm.customYuan}
                      onChange={(e) =>
                        setCloneForm({ ...cloneForm, customYuan: e.target.value })
                      }
                      placeholder="如: 理性/好奇/创造"
                    />
                  </label>
                  <label className="market-field">
                    <span className="market-field-label">意识模板 (ishiki)</span>
                    <input
                      className="market-input"
                      type="text"
                      value={cloneForm.customIshiki}
                      onChange={(e) =>
                        setCloneForm({
                          ...cloneForm,
                          customIshiki: e.target.value,
                        })
                      }
                      placeholder="如: 第一性原理思考"
                    />
                  </label>
                  <label className="market-field">
                    <span className="market-field-label">主题色</span>
                    <input
                      className="market-input market-color-input"
                      type="color"
                      value={cloneForm.customColor}
                      onChange={(e) =>
                        setCloneForm({ ...cloneForm, customColor: e.target.value })
                      }
                    />
                  </label>
                </div>
              )}

              <p className="market-clone-hint">
                克隆后将进入诞生仪式, 完成身份创建与公钥签发。
              </p>

              {cloneStatus.kind === "error" && (
                <div className="market-clone-error">{cloneStatus.message}</div>
              )}

              <div className="market-clone-actions">
                <button
                  className="market-btn-secondary"
                  onClick={closeCloneModal}
                  disabled={cloneStatus.kind === "submitting"}
                >
                  取消
                </button>
                <button
                  className="market-btn-primary"
                  onClick={() => void submitClone()}
                  disabled={cloneStatus.kind === "submitting"}
                >
                  {cloneStatus.kind === "submitting" ? "克隆中…" : "确认克隆"}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
