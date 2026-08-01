/**
 * PersonalityStep — 性格问卷步骤
 *
 * 6 题引导式问卷（spec 要求 5-10 题），答案汇总生成 ishiki.md 字符串。
 * ishiki.md 是运行时生成的内容字符串（非项目文档），完成后存入 wizard state。
 */

import { useMemo } from "react";
import type { StepProps } from "../types";
import { DEFAULT_PERSONALITY_QUESTIONS } from "../types";

/** 把问卷答案汇总为 ishiki.md Markdown 字符串 */
function generateIshikiMd(
  name: string,
  answers: Record<string, string>,
): string {
  const lines: string[] = [];
  lines.push(`# ${name} 的性格倾向`);
  lines.push("");
  lines.push(`> 由诞生仪式问卷自动生成，记录 LAAPer 的初始性格基线。`);
  lines.push("");

  for (const q of DEFAULT_PERSONALITY_QUESTIONS) {
    const chosen = answers[q.id];
    if (!chosen) continue;
    const isLeft = q.axis.left.id === chosen;
    const chosenAxis = isLeft ? q.axis.left : q.axis.right;
    const oppositeAxis = isLeft ? q.axis.right : q.axis.left;
    lines.push(`## ${q.prompt}`);
    lines.push("");
    lines.push(`- 偏向：**${chosenAxis.trait}**（${chosenAxis.label}）`);
    lines.push(`- 弱势轴：${oppositeAxis.trait}（${oppositeAxis.label}）`);
    lines.push("");
  }

  // 汇总各 trait 出现次数
  const traitCounts: Record<string, number> = {};
  for (const qid in answers) {
    const chosen = answers[qid];
    const q = DEFAULT_PERSONALITY_QUESTIONS.find((x) => x.id === qid);
    if (!q) continue;
    const axis = q.axis.left.id === chosen ? q.axis.left : q.axis.right;
    traitCounts[axis.trait] = (traitCounts[axis.trait] || 0) + 1;
  }
  const topTraits = Object.entries(traitCounts)
    .sort((a, b) => b[1] - a[1])
    .map(([trait, count]) => `${trait}(${count})`)
    .join(" / ");

  lines.push(`## 性格基线摘要`);
  lines.push("");
  lines.push(`主导特质分布：${topTraits || "未确定"}`);
  lines.push("");
  return lines.join("\n");
}

export function PersonalityStep({ state, update, next, prev }: StepProps) {
  const answeredCount = useMemo(
    () => Object.keys(state.personalityAnswers).length,
    [state.personalityAnswers],
  );
  const allAnswered = answeredCount === DEFAULT_PERSONALITY_QUESTIONS.length;

  const handleAnswer = (questionId: string, axisId: string) => {
    update({
      personalityAnswers: { ...state.personalityAnswers, [questionId]: axisId },
    });
  };

  const handleNext = () => {
    const ishikiMd = generateIshikiMd(state.name || "LAAPer", state.personalityAnswers);
    update({ ishikiMd });
    next();
  };

  return (
    <div className="bc-step" data-testid="bc-personality-step">
      <label className="bc-label">性格倾向问卷</label>
      <div className="bc-hint">
        共 {DEFAULT_PERSONALITY_QUESTIONS.length} 题，已回答 {answeredCount} 题。
        答案将汇总为 ishiki.md 作为 LAAPer 的初始性格基线。
      </div>

      <div className="bc-question-list" data-testid="bc-question-list">
        {DEFAULT_PERSONALITY_QUESTIONS.map((q, idx) => {
          const chosen = state.personalityAnswers[q.id];
          return (
            <div key={q.id} className="bc-question" data-testid={`bc-question-${q.id}`}>
              <div className="bc-question-prompt">
                <span className="bc-question-no">Q{idx + 1}.</span> {q.prompt}
              </div>
              <div className="bc-question-axis">
                <button
                  type="button"
                  className={`bc-axis-btn${chosen === q.axis.left.id ? " bc-axis-selected" : ""}`}
                  data-testid={`bc-${q.id}-left`}
                  onClick={() => handleAnswer(q.id, q.axis.left.id)}
                >
                  {q.axis.left.label}
                </button>
                <span className="bc-axis-separator">↔</span>
                <button
                  type="button"
                  className={`bc-axis-btn${chosen === q.axis.right.id ? " bc-axis-selected" : ""}`}
                  data-testid={`bc-${q.id}-right`}
                  onClick={() => handleAnswer(q.id, q.axis.right.id)}
                >
                  {q.axis.right.label}
                </button>
              </div>
            </div>
          );
        })}
      </div>

      <div className="bc-actions">
        <button className="bc-btn bc-btn-secondary" data-testid="bc-personality-prev" onClick={prev}>
          上一步
        </button>
        <button
          className="bc-btn bc-btn-primary"
          data-testid="bc-personality-next"
          onClick={handleNext}
          disabled={!allAnswered}
        >
          下一步
        </button>
      </div>
    </div>
  );
}
