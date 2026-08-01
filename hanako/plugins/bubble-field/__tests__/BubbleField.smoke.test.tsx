/**
 * BubbleField.smoke.test.tsx — P2-bubble-field 冒烟测试
 *
 * 验证项：
 * (a) 渲染 BubbleField 至少 1 个 Bubble
 * (b) 状态变化（online → thinking）反映为 pulse 视觉变化
 * (c) ResonanceLine 实线/虚线切换
 *
 * 使用 injectedAgents prop 避免 fetch 依赖，直接注入 stub 数据。
 */

// @vitest-environment jsdom

import '@testing-library/jest-dom/vitest';
import React from 'react';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { BubbleField } from '../BubbleField';
import { Bubble } from '../Bubble';
import { ResonanceLine } from '../ResonanceLine';
import type { AgentOnline } from '../types';

// jsdom 不提供 requestAnimationFrame，mock 为同步回调
const rafMock = vi.fn((cb: FrameRequestCallback) => {
  return 0 as number;
});
const cafMock = vi.fn();
vi.stubGlobal('requestAnimationFrame', rafMock);
vi.stubGlobal('cancelAnimationFrame', cafMock);

const STUB_AGENT: AgentOnline = {
  public_key: 'aris_local',
  name: 'Aris',
  color: '#4a9eff',
  status: 'online',
  energy: 0.8,
  capabilities: ['code-review', 'architecture'],
};

const STUB_AGENT_THINKING: AgentOnline = {
  ...STUB_AGENT,
  status: 'thinking',
};

const STUB_AGENT_SLEEPING: AgentOnline = {
  ...STUB_AGENT,
  public_key: 'butter_local',
  name: 'Butter',
  color: '#ffc857',
  status: 'sleeping',
  energy: 0.2,
};

afterEach(() => {
  cleanup();
  rafMock.mockClear();
  cafMock.mockClear();
});

describe('BubbleField 冒烟测试', () => {
  it('(a) 渲染 BubbleField 至少 1 个 Bubble', async () => {
    render(<BubbleField agents={[STUB_AGENT]} />);

    // 等待 useEffect 同步 agents 后渲染
    await waitFor(() => {
      const bubbles = screen.getAllByTestId('bf-container');
      expect(bubbles.length).toBeGreaterThan(0);
    });

    // 容器内应有 bf-bubble 元素
    const container = screen.getByTestId('bf-container');
    const bubbleEls = container.querySelectorAll('.bf-bubble');
    expect(bubbleEls.length).toBeGreaterThanOrEqual(1);
  });

  it('(a.2) 渲染多个 Bubble', async () => {
    render(<BubbleField agents={[STUB_AGENT, STUB_AGENT_SLEEPING]} />);

    await waitFor(() => {
      const container = screen.getByTestId('bf-container');
      const bubbleEls = container.querySelectorAll('.bf-bubble');
      expect(bubbleEls.length).toBe(2);
    });
  });
});

describe('Bubble 状态视觉编码', () => {
  it('(b) online 状态 pulse=false，thinking 状态 pulse=true', () => {
    // online: pulse=false
    const { rerender } = render(
      <Bubble
        color={STUB_AGENT.color}
        brightness={0.85}
        size={80}
        pulse={false}
        label="Aris [在线]"
        position={{ x: 100, y: 100 }}
      />,
    );

    const bubbleOnline = screen.getByText('Aris [在线]').closest('.bf-bubble') as HTMLElement;
    expect(bubbleOnline).toBeTruthy();
    expect(bubbleOnline.getAttribute('data-pulse')).toBe('false');
    expect(bubbleOnline.style.animation).toBe('none');

    // thinking: pulse=true
    rerender(
      <Bubble
        color={STUB_AGENT_THINKING.color}
        brightness={1.0}
        size={80}
        pulse={true}
        label="Aris [思考中]"
        position={{ x: 100, y: 100 }}
      />,
    );

    const bubbleThinking = screen.getByText('Aris [思考中]').closest('.bf-bubble') as HTMLElement;
    expect(bubbleThinking).toBeTruthy();
    expect(bubbleThinking.getAttribute('data-pulse')).toBe('true');
    expect(bubbleThinking.style.animation).toContain('bf-pulse');
  });

  it('(b.2) brightness 影响 opacity', () => {
    render(
      <Bubble
        color="#4a9eff"
        brightness={0.25}
        size={60}
        pulse={false}
        label="Sleeping"
        position={{ x: 50, y: 50 }}
      />,
    );

    const bubble = screen.getByText('Sleeping').closest('.bf-bubble') as HTMLElement;
    // brightness 0.25 → opacity 0.25
    expect(parseFloat(bubble.style.opacity)).toBe(0.25);
  });
});

describe('ResonanceLine 实线/虚线', () => {
  it('(c) strength > 0.7 渲染实线', () => {
    const { container } = render(
      <svg>
        <ResonanceLine
          from={{ x: 0, y: 0 }}
          to={{ x: 100, y: 100 }}
          strength={0.85}
        />
      </svg>,
    );

    const line = container.querySelector('.bf-resonance-line') as SVGLineElement;
    expect(line).toBeTruthy();
    expect(line.getAttribute('data-style')).toBe('solid');
    expect(line.getAttribute('stroke-dasharray')).toBe('none');
  });

  it('(c.2) strength <= 0.7 渲染虚线', () => {
    const { container } = render(
      <svg>
        <ResonanceLine
          from={{ x: 0, y: 0 }}
          to={{ x: 100, y: 100 }}
          strength={0.4}
        />
      </svg>,
    );

    const line = container.querySelector('.bf-resonance-line') as SVGLineElement;
    expect(line).toBeTruthy();
    expect(line.getAttribute('data-style')).toBe('dashed');
    expect(line.getAttribute('stroke-dasharray')).toBe('6 4');
  });

  it('(c.3) strength 边界值 0.7 为虚线', () => {
    const { container } = render(
      <svg>
        <ResonanceLine
          from={{ x: 0, y: 0 }}
          to={{ x: 100, y: 100 }}
          strength={0.7}
        />
      </svg>,
    );

    const line = container.querySelector('.bf-resonance-line') as SVGLineElement;
    expect(line.getAttribute('data-style')).toBe('dashed');
  });
});

describe('BubbleField 状态变化集成', () => {
  it('(d) agent status 从 online 变为 thinking 时 pulse 属性变化', async () => {
    const { rerender } = render(<BubbleField agents={[STUB_AGENT]} />);

    // 等待初始渲染
    await waitFor(() => {
      const container = screen.getByTestId('bf-container');
      expect(container.querySelectorAll('.bf-bubble').length).toBe(1);
    });

    // 初始 online → pulse=false
    let bubble = screen.getByTestId('bf-container').querySelector('.bf-bubble') as HTMLElement;
    expect(bubble.getAttribute('data-pulse')).toBe('false');

    // 重新渲染 thinking 状态
    rerender(<BubbleField agents={[STUB_AGENT_THINKING]} />);

    await waitFor(() => {
      const bubbleEl = screen.getByTestId('bf-container').querySelector('.bf-bubble') as HTMLElement;
      expect(bubbleEl.getAttribute('data-pulse')).toBe('true');
    });
  });
});
