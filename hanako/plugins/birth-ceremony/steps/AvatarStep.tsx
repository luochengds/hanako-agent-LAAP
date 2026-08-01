/**
 * AvatarStep — 形象选择步骤
 *
 * 本阶段提供 4 个默认色板预设作为 stub（spec L240）。
 * 用户选色后存入 wizard state 作为 LAAPer 主色。
 * P5 laaper-market 完成后接入真实预设包（预留 import 路径注释）。
 */

import type { StepProps } from "../types";
import { DEFAULT_AVATAR_PRESETS } from "../types";

// P5 laaper-market 完成后改为：
// import { fetchMarketPresets } from "../laaper-market-integration";
// const presets = await fetchMarketPresets();
// 当前用 DEFAULT_AVATAR_PRESETS 作为 stub。

export function AvatarStep({ state, update, next, prev }: StepProps) {
  const handleSelect = (color: string) => {
    update({ color });
  };

  return (
    <div className="bc-step" data-testid="bc-avatar-step">
      <label className="bc-label">选择 LAAPer 主色</label>
      <div className="bc-hint">主色将用于 bubble-field 中的发光泡泡与界面强调色。P5 laaper-market 完成后可加载完整预设包。</div>

      <div className="bc-preset-grid" data-testid="bc-preset-grid">
        {DEFAULT_AVATAR_PRESETS.map((preset) => {
          const selected = state.color === preset.color;
          return (
            <button
              key={preset.id}
              type="button"
              className={`bc-preset-card${selected ? " bc-preset-selected" : ""}`}
              data-testid={`bc-preset-${preset.id}`}
              onClick={() => handleSelect(preset.color)}
              style={{ borderColor: selected ? preset.color : undefined }}
            >
              <div
                className="bc-preset-swatch"
                style={{ backgroundColor: preset.color, boxShadow: `0 0 24px ${preset.color}66` }}
              />
              <div className="bc-preset-label">{preset.label}</div>
              <div className="bc-preset-desc">{preset.description}</div>
              <div className="bc-preset-hex">{preset.color}</div>
            </button>
          );
        })}
      </div>

      <div className="bc-actions">
        <button className="bc-btn bc-btn-secondary" data-testid="bc-avatar-prev" onClick={prev}>
          上一步
        </button>
        <button
          className="bc-btn bc-btn-primary"
          data-testid="bc-avatar-next"
          onClick={next}
          disabled={!state.color}
        >
          下一步
        </button>
      </div>
    </div>
  );
}
