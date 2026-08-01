/**
 * DiffViewer — 行级 diff 显示
 *
 * 简易行级 diff：基于最长公共子序列（LCS）算法（tasks SubTask 2.3）。
 * 不引入新 npm 依赖，纯原生 JS 实现。
 *
 * 行类型：
 * - added（+，绿色）：新文件中新增的行
 * - removed（-，红色）：原文件中删除的行
 * - unchanged（空，灰色）：两文件相同的行
 */

import { useMemo } from "react";

export interface DiffViewerProps {
  /** 原组件源码 */
  oldSource: string;
  /** 新组件源码 */
  newSource: string;
  /** 最大比对行数（超过则截断），默认 5000。防止超大文件 OOM。 */
  maxLines?: number;
}

export interface DiffLine {
  type: "added" | "removed" | "unchanged";
  content: string;
  oldLineNo?: number;
  newLineNo?: number;
}

/**
 * 计算两段文本的行级 diff（基于 LCS 动态规划）。
 *
 * 时间复杂度 O(m*n)，空间复杂度 O(m*n)（Uint32Array 节省内存）。
 * 对冒烟测试用例（< 100 行）足够；超大文件应预先截断。
 */
export function computeLineDiff(
  oldSource: string,
  newSource: string,
  maxLines = 5000,
): DiffLine[] {
  const oldLines = (oldSource || "").split("\n").slice(0, maxLines);
  const newLines = (newSource || "").split("\n").slice(0, maxLines);
  const m = oldLines.length;
  const n = newLines.length;

  // LCS DP 表：(m+1) x (n+1)，用 Uint32Array 减少内存
  const dp: Uint32Array[] = new Array(m + 1);
  for (let i = 0; i <= m; i++) {
    dp[i] = new Uint32Array(n + 1);
  }
  // 自底向上填表
  for (let i = m - 1; i >= 0; i--) {
    for (let j = n - 1; j >= 0; j--) {
      if (oldLines[i] === newLines[j]) {
        dp[i][j] = dp[i + 1][j + 1] + 1;
      } else {
        dp[i][j] = Math.max(dp[i + 1][j], dp[i][j + 1]);
      }
    }
  }
  // 回溯生成 diff 行
  const result: DiffLine[] = [];
  let i = 0;
  let j = 0;
  while (i < m && j < n) {
    if (oldLines[i] === newLines[j]) {
      result.push({
        type: "unchanged",
        content: oldLines[i],
        oldLineNo: i + 1,
        newLineNo: j + 1,
      });
      i++;
      j++;
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      result.push({ type: "removed", content: oldLines[i], oldLineNo: i + 1 });
      i++;
    } else {
      result.push({ type: "added", content: newLines[j], newLineNo: j + 1 });
      j++;
    }
  }
  while (i < m) {
    result.push({ type: "removed", content: oldLines[i], oldLineNo: i + 1 });
    i++;
  }
  while (j < n) {
    result.push({ type: "added", content: newLines[j], newLineNo: j + 1 });
    j++;
  }
  return result;
}

export function DiffViewer({ oldSource, newSource, maxLines }: DiffViewerProps) {
  const diff = useMemo(
    () => computeLineDiff(oldSource, newSource, maxLines),
    [oldSource, newSource, maxLines],
  );

  if (!diff.length) {
    return <div className="hot-compile-empty">无内容可对比</div>;
  }

  return (
    <div className="hot-compile-diff" role="log" aria-label="source diff">
      {diff.map((line, idx) => {
        const marker = line.type === "added" ? "+" : line.type === "removed" ? "-" : " ";
        return (
          <div key={idx} className={`hot-compile-diff-line ${line.type}`}>
            <span className="hot-compile-diff-marker">{marker}</span>
            <span className="hot-compile-diff-content">{line.content || " "}</span>
          </div>
        );
      })}
    </div>
  );
}
