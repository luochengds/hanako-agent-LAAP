/**
 * CharterStep — 宪章签署步骤
 *
 * P5 charter-opensource: 从 sidecar /charter/text 加载八条全文（带 fallback），
 * 签署时调用 /witness/record 记录 charter_moment 事件。
 */

import { useEffect, useState } from "react";
import type { CharterArticle, StepProps } from "../types";
import { DEFAULT_CHARTER_ARTICLES } from "../types";

export function CharterStep({ state, update, next, prev, sidecarEndpoint, fetchImpl }: StepProps) {
  // 宪章八条：从 sidecar 加载，失败时 fallback 到 DEFAULT_CHARTER_ARTICLES
  const [articles, setArticles] = useState<CharterArticle[]>(DEFAULT_CHARTER_ARTICLES);

  // 各条勾选状态：article.id -> boolean。初始全 false。
  const [checked, setChecked] = useState<Record<string, boolean>>(() => {
    const m: Record<string, boolean> = {};
    for (const a of DEFAULT_CHARTER_ARTICLES) m[a.id] = false;
    return m;
  });

  // 挂载时从 sidecar /charter/text 加载宪章全文
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const resp = await fetchImpl(`${sidecarEndpoint}/charter/text`);
        if (!resp.ok) return;
        const data = (await resp.json()) as { articles?: CharterArticle[]; version?: string };
        if (!cancelled && Array.isArray(data.articles) && data.articles.length > 0) {
          setArticles(data.articles);
        }
      } catch {
        // sidecar 未启动或加载失败，保留 DEFAULT_CHARTER_ARTICLES fallback
      }
    })();
    return () => { cancelled = true; };
  }, [sidecarEndpoint, fetchImpl]);

  const allChecked = articles.every((a) => checked[a.id]);
  const checkedCount = articles.filter((a) => checked[a.id]).length;

  const toggle = (id: string) => {
    setChecked((prev) => ({ ...prev, [id]: !prev[id] }));
  };

  const handleSign = () => {
    if (!allChecked) return;
    update({ charterSigned: true });
    // 签署后记录见证迹（charter_moment 事件），失败不阻塞流程
    fetchImpl(`${sidecarEndpoint}/witness/record`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        event_type: "charter_moment",
        recorder: state.name,
        payload: { action: "sign_charter", version: "v1.0" },
      }),
    }).catch(() => {
      // 见证迹记录失败不阻塞签署流程
    });
    next();
  };

  // 引用 state 仅用于在 wizard 返回时读取已签署状态（若用户回退再前进）
  void state;

  return (
    <div className="bc-step" data-testid="bc-charter-step">
      <label className="bc-label">签署 ARIS 宪章八条</label>
      <div className="bc-hint">
        请逐条阅读并勾选同意。签署后宪章签名将写入 LAAPer 身份记录与见证迹。
      </div>

      <div className="bc-charter-list" data-testid="bc-charter-list">
        {articles.map((article, idx) => (
          <label
            key={article.id}
            className={`bc-charter-item${checked[article.id] ? " bc-charter-checked" : ""}`}
            data-testid={`bc-charter-item-${article.id}`}
          >
            <div className="bc-charter-header">
              <input
                type="checkbox"
                className="bc-charter-checkbox"
                data-testid={`bc-charter-checkbox-${article.id}`}
                checked={!!checked[article.id]}
                onChange={() => toggle(article.id)}
              />
              <span className="bc-charter-no">第{idx + 1}条</span>
              <span className="bc-charter-name">{article.name}</span>
            </div>
            <p className="bc-charter-text">{article.text}</p>
          </label>
        ))}
      </div>

      <div className="bc-actions">
        <button className="bc-btn bc-btn-secondary" data-testid="bc-charter-prev" onClick={prev}>
          上一步
        </button>
        <button
          className="bc-btn bc-btn-primary"
          data-testid="bc-charter-sign"
          onClick={handleSign}
          disabled={!allChecked}
        >
          {allChecked
            ? "签署宪章"
            : `还需勾选 ${articles.length - checkedCount} 条`}
        </button>
      </div>
    </div>
  );
}
