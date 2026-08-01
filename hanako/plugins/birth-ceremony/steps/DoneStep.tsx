/**
 * DoneStep — 完成步骤
 *
 * 调用 sidecar /ceremony/finalize 端点，传入 {name, color, ishiki_md, charter_signed, public_key}。
 * sidecar 完成四件事（spec SubTask 2.7）：
 *  1. vault_manager.init_for_agent(name) 初始化 vault
 *  2. ishiki.md 写入 vault 语义记忆表
 *  3. 身份记录写入本地 hanako/data/identity_registry.json
 *  4. 诞生事件写入 vault witness_trail_local 表（P4 stub）
 * 完成后通过 onComplete 回调通知父组件（App.tsx 切回 bubble-field）。
 */

import { useEffect, useState } from "react";
import type { CeremonyWizardProps, FinalizeRequest, FinalizeResponse, StepProps } from "../types";

type DoneStepProps = StepProps & {
  onComplete?: CeremonyWizardProps["onComplete"];
};

export function DoneStep({ state, update, onComplete, sidecarEndpoint, fetchImpl }: DoneStepProps) {
  const [autoTriggered, setAutoTriggered] = useState(false);

  // 进入 done 步骤后自动触发 finalize（仅一次）
  useEffect(() => {
    if (autoTriggered) return;
    if (state.finalizeStatus.status === "submitting" || state.finalizeStatus.status === "success") {
      return;
    }
    setAutoTriggered(true);
    void doFinalize();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoTriggered]);

  const doFinalize = async () => {
    update({ finalizeStatus: { status: "submitting" } });
    try {
      const reqBody: FinalizeRequest = {
        name: state.name,
        color: state.color,
        ishiki_md: state.ishikiMd,
        charter_signed: state.charterSigned,
        public_key: state.publicKey,
      };
      const resp = await fetchImpl(`${sidecarEndpoint}/ceremony/finalize`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(reqBody),
      });
      const data = (await resp.json()) as FinalizeResponse;
      if (!resp.ok || !data.success) {
        const errMsg = data.error || `HTTP ${resp.status}`;
        update({ finalizeStatus: { status: "error", error: errMsg } });
        return;
      }
      update({ finalizeStatus: { status: "success", laaper: data.laaper } });
    } catch (e) {
      const errMsg = e instanceof Error ? e.message : String(e);
      update({ finalizeStatus: { status: "error", error: errMsg } });
    }
  };

  const handleComplete = () => {
    if (state.finalizeStatus.laaper) {
      onComplete?.(state.finalizeStatus.laaper);
    }
  };

  const handleRetry = () => {
    setAutoTriggered(false);
    update({ finalizeStatus: { status: "idle" } });
  };

  if (state.finalizeStatus.status === "submitting") {
    return (
      <div className="bc-step" data-testid="bc-done-step">
        <div className="bc-done-icon bc-done-loading" data-testid="bc-done-loading">
          <div className="bc-spinner" />
        </div>
        <h3 className="bc-done-title">正在注册 LAAPer 身份…</h3>
        <p className="bc-done-desc">
          初始化 memory vault · 写入 ishiki.md · 注册身份 · 记录诞生见证迹
        </p>
      </div>
    );
  }

  if (state.finalizeStatus.status === "error") {
    return (
      <div className="bc-step" data-testid="bc-done-step">
        <div className="bc-done-icon bc-done-error">!</div>
        <h3 className="bc-done-title">注册失败</h3>
        <p className="bc-done-desc bc-status-error" data-testid="bc-done-error">
          {state.finalizeStatus.error}
        </p>
        <div className="bc-actions">
          <button
            className="bc-btn bc-btn-primary"
            data-testid="bc-done-retry"
            onClick={handleRetry}
          >
            重试
          </button>
        </div>
      </div>
    );
  }

  if (state.finalizeStatus.status === "success" && state.finalizeStatus.laaper) {
    const laaper = state.finalizeStatus.laaper;
    return (
      <div className="bc-step" data-testid="bc-done-step">
        <div className="bc-done-icon bc-done-success" data-testid="bc-done-success">
          <div
            className="bc-done-bubble"
            style={{ backgroundColor: laaper.color, boxShadow: `0 0 40px ${laaper.color}` }}
          />
        </div>
        <h3 className="bc-done-title">LAAPer {laaper.name} 诞生完成</h3>
        <p className="bc-done-desc">
          memory vault 已初始化 · 身份已注册 · 见证迹已记录
        </p>
        <div className="bc-done-summary" data-testid="bc-done-summary">
          <div className="bc-pubkey-row">
            <span className="bc-pubkey-label">名称</span>
            <code>{laaper.name}</code>
          </div>
          <div className="bc-pubkey-row">
            <span className="bc-pubkey-label">主色</span>
            <code>{laaper.color}</code>
          </div>
          <div className="bc-pubkey-row">
            <span className="bc-pubkey-label">公钥指纹</span>
            <code>{laaper.public_key.slice(0, 16)}...</code>
          </div>
        </div>
        <div className="bc-actions">
          <button
            className="bc-btn bc-btn-primary"
            data-testid="bc-done-complete"
            onClick={handleComplete}
          >
            进入意识海洋
          </button>
        </div>
      </div>
    );
  }

  // idle 状态：显示触发按钮（通常不会出现，因为 useEffect 会自动触发）
  return (
    <div className="bc-step" data-testid="bc-done-step">
      <p className="bc-done-desc">准备完成注册</p>
      <div className="bc-actions">
        <button
          className="bc-btn bc-btn-primary"
          data-testid="bc-done-trigger"
          onClick={doFinalize}
        >
          完成注册
        </button>
      </div>
    </div>
  );
}
