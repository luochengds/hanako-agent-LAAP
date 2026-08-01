/**
 * SkillCard — 单技能卡片
 *
 * 显示技能名称、版本号、作者、charter_compatible 徽章，
 * 以及 安装/卸载/导出 三个操作按钮。
 *
 * Mineradio 风格：深色卡片 + 强调色边框 + 简洁按钮
 */

import React from "react";
import type { SkillCardProps } from "./types";

export function SkillCard({
  skill,
  installed,
  onInstall,
  onUninstall,
  onExport,
  busy = false,
}: SkillCardProps) {
  return (
    <div
      className="sp-card"
      data-testid={`sp-card-${skill.skill_id}`}
      data-installed={installed ? "true" : "false"}
    >
      <div className="sp-card-header">
        <span className="sp-card-name" data-testid="sp-card-name">
          {skill.skill_id}
        </span>
        {skill.charter_compatible ? (
          <span
            className="sp-badge sp-badge-ok"
            data-testid="sp-charter-badge"
            title="通过宪章八条检查"
          >
            charter ok
          </span>
        ) : (
          <span
            className="sp-badge sp-badge-warn"
            data-testid="sp-charter-badge"
            title="未通过宪章检查，安装需谨慎"
          >
            charter warn
          </span>
        )}
      </div>

      <div className="sp-card-meta">
        <span className="sp-meta-version" data-testid="sp-card-version">
          v{skill.version}
        </span>
        {skill.author ? (
          <span className="sp-meta-author" data-testid="sp-card-author">
            by {skill.author}
          </span>
        ) : null}
      </div>

      {skill.description ? (
        <p className="sp-card-desc" data-testid="sp-card-desc">
          {skill.description}
        </p>
      ) : null}

      <div className="sp-card-actions">
        {installed ? (
          <button
            className="sp-btn sp-btn-uninstall"
            data-testid="sp-btn-uninstall"
            onClick={() => onUninstall(skill.skill_id)}
            disabled={busy}
          >
            卸载
          </button>
        ) : (
          <button
            className="sp-btn sp-btn-install"
            data-testid="sp-btn-install"
            onClick={() => onInstall(skill.skill_id)}
            disabled={busy}
          >
            安装
          </button>
        )}
        <button
          className="sp-btn sp-btn-export"
          data-testid="sp-btn-export"
          onClick={() => onExport(skill.skill_id)}
          disabled={busy}
        >
          导出
        </button>
      </div>
    </div>
  );
}
