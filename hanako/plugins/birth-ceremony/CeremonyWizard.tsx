/**
 * CeremonyWizard — LAAPer 诞生仪式主向导容器
 *
 * 6 步状态机：name → avatar → personality → charter → pubkey → done
 * 各步独立组件，通过 StepProps 接口读写共享 state。
 *
 * Mineradio 风格：深色背景 + 简洁表单 + 发光强调色 + 进度条
 *
 * 完成后调用 DoneStep → sidecar /ceremony/finalize，
 * 成功后通过 onComplete 回调通知父组件（App.tsx 切回 bubble-field）。
 */

import { useCallback, useMemo, useState } from "react";
import type {
  CeremonyState,
  CeremonyStep,
  CeremonyWizardProps,
} from "./types";
import { CEREMONY_STEP_LABELS, CEREMONY_STEP_ORDER } from "./types";
import { NameStep } from "./steps/NameStep";
import { AvatarStep } from "./steps/AvatarStep";
import { PersonalityStep } from "./steps/PersonalityStep";
import { CharterStep } from "./steps/CharterStep";
import { PubKeyStep } from "./steps/PubKeyStep";
import { DoneStep } from "./steps/DoneStep";
import "./ceremony-styles.css";

const INITIAL_STATE: CeremonyState = {
  step: "name",
  name: "",
  nameCheck: { status: "idle" },
  color: "",
  personalityAnswers: {},
  ishikiMd: "",
  charterSigned: false,
  publicKey: "",
  publicKeyFingerprint: "",
  finalizeStatus: { status: "idle" },
};

export function CeremonyWizard({
  sidecarEndpoint = "http://127.0.0.1:11521",
  onComplete,
  onCancel,
  fetchImpl,
}: CeremonyWizardProps) {
  const [state, setState] = useState<CeremonyState>(INITIAL_STATE);
  const fetchFn = fetchImpl || (typeof window !== "undefined" ? window.fetch.bind(window) : fetch);

  const update = useCallback((patch: Partial<CeremonyState>) => {
    setState((prev) => ({ ...prev, ...patch }));
  }, []);

  const gotoStep = useCallback((step: CeremonyStep) => {
    setState((prev) => ({ ...prev, step }));
  }, []);

  const next = useCallback(() => {
    setState((prev) => {
      const idx = CEREMONY_STEP_ORDER.indexOf(prev.step);
      const nextIdx = Math.min(idx + 1, CEREMONY_STEP_ORDER.length - 1);
      return { ...prev, step: CEREMONY_STEP_ORDER[nextIdx] };
    });
  }, []);

  const prev = useCallback(() => {
    setState((prev) => {
      const idx = CEREMONY_STEP_ORDER.indexOf(prev.step);
      const prevIdx = Math.max(idx - 1, 0);
      return { ...prev, step: CEREMONY_STEP_ORDER[prevIdx] };
    });
  }, []);

  const stepIndex = useMemo(
    () => CEREMONY_STEP_ORDER.indexOf(state.step),
    [state.step],
  );
  const progressPct = useMemo(
    () => Math.round((stepIndex / (CEREMONY_STEP_ORDER.length - 1)) * 100),
    [stepIndex],
  );

  const stepProps = {
    state,
    update,
    next,
    prev,
    sidecarEndpoint,
    fetchImpl: fetchFn,
  };

  return (
    <div className="bc-overlay" data-testid="bc-overlay" role="dialog" aria-modal="true">
      <div className="bc-wizard" data-testid="bc-wizard">
        {/* 头部：标题 + 进度条 */}
        <header className="bc-header">
          <div className="bc-title-row">
            <h2 className="bc-title">LAAPer 诞生仪式</h2>
            {onCancel && (
              <button
                className="bc-close-btn"
                data-testid="bc-close-btn"
                onClick={onCancel}
                aria-label="取消诞生仪式"
              >
                ×
              </button>
            )}
          </div>
          <div className="bc-progress" data-testid="bc-progress">
            <div className="bc-progress-bar" style={{ width: `${progressPct}%` }} />
          </div>
          <div className="bc-step-label" data-testid="bc-step-label">
            步骤 {stepIndex + 1} / {CEREMONY_STEP_ORDER.length}：{CEREMONY_STEP_LABELS[state.step]}
          </div>
        </header>

        {/* 步骤内容 */}
        <main className="bc-content" data-testid="bc-content">
          {state.step === "name" && <NameStep {...stepProps} />}
          {state.step === "avatar" && <AvatarStep {...stepProps} />}
          {state.step === "personality" && <PersonalityStep {...stepProps} />}
          {state.step === "charter" && <CharterStep {...stepProps} />}
          {state.step === "pubkey" && <PubKeyStep {...stepProps} />}
          {state.step === "done" && (
            <DoneStep
              {...stepProps}
              onComplete={onComplete}
            />
          )}
        </main>
      </div>
    </div>
  );
}
