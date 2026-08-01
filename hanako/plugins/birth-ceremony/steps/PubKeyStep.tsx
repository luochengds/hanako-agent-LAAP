/**
 * PubKeyStep — 公钥生成步骤
 *
 * 调用 sidecar /ceremony/pubkey 端点生成 Ed25519 密钥对。
 * sidecar 内部调 laap/security/crypto/keys.py KeyManager.generate()，
 * 返回 {public_key, fingerprint}，私钥不离开 sidecar（spec L435 硬约束）。
 * 显示公钥指纹（前 16 字符 + ...）。
 */

import { useState } from "react";
import type { StepProps, PubKeyResponse } from "../types";

export function PubKeyStep({ state, update, next, prev, sidecarEndpoint, fetchImpl }: StepProps) {
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleGenerate = async () => {
    setGenerating(true);
    setError(null);
    try {
      const resp = await fetchImpl(`${sidecarEndpoint}/ceremony/pubkey`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: state.name } as { name: string }),
      });
      if (!resp.ok) {
        const errBody = await resp.json().catch(() => ({})) as { error?: string };
        throw new Error(errBody.error || `HTTP ${resp.status}`);
      }
      const data = (await resp.json()) as PubKeyResponse;
      update({
        publicKey: data.public_key,
        publicKeyFingerprint: data.fingerprint,
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setGenerating(false);
    }
  };

  const handleNext = () => {
    if (state.publicKey) next();
  };

  const fingerprintDisplay = state.publicKeyFingerprint
    ? `${state.publicKeyFingerprint.slice(0, 16)}${state.publicKeyFingerprint.length > 16 ? "..." : ""}`
    : "";

  return (
    <div className="bc-step" data-testid="bc-pubkey-step">
      <label className="bc-label">生成社区公钥</label>
      <div className="bc-hint">
        点击下方按钮生成 Ed25519 密钥对。公钥将公开作为 LAAPer 身份标识，
        私钥由 sidecar 安全保管，永不通过网络返回（spec 硬约束）。
      </div>

      <div className="bc-pubkey-area" data-testid="bc-pubkey-area">
        {!state.publicKey && (
          <button
            className="bc-btn bc-btn-primary"
            data-testid="bc-pubkey-generate"
            onClick={handleGenerate}
            disabled={generating}
          >
            {generating ? "正在生成…" : "生成密钥对"}
          </button>
        )}

        {state.publicKey && (
          <div className="bc-pubkey-result" data-testid="bc-pubkey-result">
            <div className="bc-pubkey-row">
              <span className="bc-pubkey-label">公钥指纹</span>
              <code className="bc-pubkey-fingerprint" data-testid="bc-pubkey-fingerprint">
                {fingerprintDisplay}
              </code>
            </div>
            <div className="bc-pubkey-row">
              <span className="bc-pubkey-label">公钥全文</span>
              <code className="bc-pubkey-full">{state.publicKey}</code>
            </div>
          </div>
        )}

        {error && (
          <div className="bc-status bc-status-error" data-testid="bc-pubkey-error">
            生成失败：{error}
          </div>
        )}
      </div>

      <div className="bc-actions">
        <button className="bc-btn bc-btn-secondary" data-testid="bc-pubkey-prev" onClick={prev}>
          上一步
        </button>
        <button
          className="bc-btn bc-btn-primary"
          data-testid="bc-pubkey-next"
          onClick={handleNext}
          disabled={!state.publicKey}
        >
          完成
        </button>
      </div>
    </div>
  );
}
