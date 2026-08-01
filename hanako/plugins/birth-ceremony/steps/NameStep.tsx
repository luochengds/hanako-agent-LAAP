/**
 * NameStep — 命名步骤
 *
 * 输入框 + onChange 防抖查询 sidecar /ceremony/check-name。
 * 重名校验：fetch {endpoint}/ceremony/check-name?name=X → {available, reason?}
 */

import { useEffect, useRef } from "react";
import type { StepProps } from "../types";

const NAME_MIN_LEN = 2;
const NAME_MAX_LEN = 32;
const NAME_PATTERN = /^[A-Za-z0-9_\u4e00-\u9fa5-]+$/;
const DEBOUNCE_MS = 400;

export function NameStep({ state, update, next, sidecarEndpoint, fetchImpl }: StepProps) {
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // 防抖查询重名
  useEffect(() => {
    const name = state.name.trim();
    if (!name) {
      update({ nameCheck: { status: "idle" } });
      return;
    }
    if (name.length < NAME_MIN_LEN) {
      update({ nameCheck: { status: "idle" } });
      return;
    }
    if (!NAME_PATTERN.test(name)) {
      update({ nameCheck: { status: "taken", reason: "名称仅允许字母、数字、中文、下划线、连字符" } });
      return;
    }
    update({ nameCheck: { status: "checking" } });
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(async () => {
      try {
        const resp = await fetchImpl(
          `${sidecarEndpoint}/ceremony/check-name?name=${encodeURIComponent(name)}`,
        );
        if (!resp.ok) {
          update({ nameCheck: { status: "idle" } });
          return;
        }
        const data = (await resp.json()) as { available: boolean; reason?: string };
        update({
          nameCheck: data.available
            ? { status: "available" }
            : { status: "taken", reason: data.reason || "名称已被占用" },
        });
      } catch {
        // sidecar 未启动时静默放行（测试/离线场景），不阻塞流程
        update({ nameCheck: { status: "available" } });
      }
    }, DEBOUNCE_MS);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.name]);

  const canAdvance =
    state.name.trim().length >= NAME_MIN_LEN &&
    state.nameCheck.status === "available";

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    update({ name: e.target.value, nameCheck: { status: "idle" } });
  };

  return (
    <div className="bc-step" data-testid="bc-name-step">
      <label className="bc-label" htmlFor="bc-name-input">为你的 LAAPer 命名</label>
      <input
        id="bc-name-input"
        className="bc-input"
        data-testid="bc-name-input"
        type="text"
        value={state.name}
        onChange={handleInputChange}
        maxLength={NAME_MAX_LEN}
        placeholder="例如：Miku / Aris / Hanako"
        autoFocus
      />
      <div className="bc-hint">2-32 字符，支持中英文、数字、下划线、连字符</div>

      {state.nameCheck.status === "checking" && (
        <div className="bc-status bc-status-checking" data-testid="bc-name-checking">
          正在检查名称可用性…
        </div>
      )}
      {state.nameCheck.status === "available" && (
        <div className="bc-status bc-status-ok" data-testid="bc-name-available">
          名称可用
        </div>
      )}
      {state.nameCheck.status === "taken" && (
        <div className="bc-status bc-status-error" data-testid="bc-name-taken">
          {state.nameCheck.reason || "名称已被占用"}
        </div>
      )}

      <div className="bc-actions">
        <button
          className="bc-btn bc-btn-primary"
          data-testid="bc-name-next"
          onClick={next}
          disabled={!canAdvance}
        >
          下一步
        </button>
      </div>
    </div>
  );
}
