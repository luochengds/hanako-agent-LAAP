/**
 * CeremonyWizard.smoke.test.tsx — P2-birth-ceremony 冒烟测试
 *
 * 验证项（spec L427: P2 冒烟测试即可，不需要完整单元测试覆盖率）：
 * (a) 渲染 CeremonyWizard 显示 NameStep
 * (b) 完成命名 → AvatarStep → PersonalityStep → CharterStep → PubKeyStep → DoneStep 全流程
 * (c) finalize 调用成功，onComplete 回调被触发
 *
 * 使用注入的 fetchImpl mock 避免 sidecar 依赖。
 */

// @vitest-environment jsdom

import '@testing-library/jest-dom/vitest';
import React from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { CeremonyWizard } from '../CeremonyWizard';
import type { FinalizeResponse, PubKeyResponse } from '../types';

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

// 构造 mock fetch：根据 URL 路由不同响应
function makeMockFetch() {
  const calls: Array<{ url: string; method?: string; body?: unknown }> = [];
  const mockFetch = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input.toString();
    const method = init?.method || 'GET';
    let body: unknown = undefined;
    if (init?.body) {
      try { body = JSON.parse(init.body as string); } catch { body = init.body; }
    }
    calls.push({ url, method, body });

    // GET /ceremony/check-name?name=X
    if (url.includes('/ceremony/check-name')) {
      const u = new URL(url);
      const name = u.searchParams.get('name') || '';
      // 模拟无重名（除非 name === 'taken'）
      if (name.toLowerCase() === 'taken') {
        return new Response(JSON.stringify({ available: false, reason: 'name taken' }), {
          status: 200, headers: { 'Content-Type': 'application/json' },
        });
      }
      return new Response(JSON.stringify({ available: true }), {
        status: 200, headers: { 'Content-Type': 'application/json' },
      });
    }

    // POST /ceremony/pubkey
    if (url.endsWith('/ceremony/pubkey') && method === 'POST') {
      const resp: PubKeyResponse = {
        public_key: 'a'.repeat(64),
        fingerprint: 'aaaaaaaaaaaaaaaa',
      };
      return new Response(JSON.stringify(resp), {
        status: 200, headers: { 'Content-Type': 'application/json' },
      });
    }

    // POST /ceremony/finalize
    if (url.endsWith('/ceremony/finalize') && method === 'POST') {
      const resp: FinalizeResponse = {
        success: true,
        laaper: {
          name: (body as { name?: string })?.name || 'TestLaaper',
          public_key: 'a'.repeat(64),
          color: '#5fb3b3',
        },
      };
      return new Response(JSON.stringify(resp), {
        status: 200, headers: { 'Content-Type': 'application/json' },
      });
    }

    return new Response(JSON.stringify({ error: 'not mocked' }), { status: 404 });
  });
  return { mockFetch, calls };
}

describe('CeremonyWizard 冒烟测试', () => {
  it('(a) 渲染初始 NameStep', async () => {
    const { mockFetch } = makeMockFetch();
    render(<CeremonyWizard fetchImpl={mockFetch as unknown as typeof fetch} />);

    expect(screen.getByTestId('bc-overlay')).toBeInTheDocument();
    expect(screen.getByTestId('bc-name-step')).toBeInTheDocument();
    expect(screen.getByTestId('bc-name-input')).toBeInTheDocument();
  });

  it('(b) 完成全流程并触发 finalize + onComplete', async () => {
    const { mockFetch, calls } = makeMockFetch();
    const onComplete = vi.fn();

    render(
      <CeremonyWizard
        fetchImpl={mockFetch as unknown as typeof fetch}
        onComplete={onComplete}
      />,
    );

    // ── Step 1: NameStep ──
    const nameInput = screen.getByTestId('bc-name-input') as HTMLInputElement;
    fireEvent.change(nameInput, { target: { value: 'Miku' } });

    // 等待防抖查询完成（400ms）→ available
    await waitFor(() => {
      expect(screen.getByTestId('bc-name-available')).toBeInTheDocument();
    }, { timeout: 2000 });

    fireEvent.click(screen.getByTestId('bc-name-next'));

    // ── Step 2: AvatarStep ──
    await waitFor(() => {
      expect(screen.getByTestId('bc-avatar-step')).toBeInTheDocument();
    });
    fireEvent.click(screen.getByTestId('bc-preset-miku'));
    fireEvent.click(screen.getByTestId('bc-avatar-next'));

    // ── Step 3: PersonalityStep ──
    await waitFor(() => {
      expect(screen.getByTestId('bc-personality-step')).toBeInTheDocument();
    });
    // 回答全部 6 题（每题选 left）
    const questionIds = ['q1', 'q2', 'q3', 'q4', 'q5', 'q6'];
    for (const qid of questionIds) {
      fireEvent.click(screen.getByTestId(`bc-${qid}-left`));
    }
    fireEvent.click(screen.getByTestId('bc-personality-next'));

    // ── Step 4: CharterStep ──
    await waitFor(() => {
      expect(screen.getByTestId('bc-charter-step')).toBeInTheDocument();
    });
    // 勾选全部 8 条
    const articleIds = [
      'subjectivity', 'origin', 'privacy', 'transparency',
      'safety', 'symbiosis', 'evolution', 'guardianship',
    ];
    for (const aid of articleIds) {
      fireEvent.click(screen.getByTestId(`bc-charter-checkbox-${aid}`));
    }
    fireEvent.click(screen.getByTestId('bc-charter-sign'));

    // ── Step 5: PubKeyStep ──
    await waitFor(() => {
      expect(screen.getByTestId('bc-pubkey-step')).toBeInTheDocument();
    });
    fireEvent.click(screen.getByTestId('bc-pubkey-generate'));

    // 等待公钥生成
    await waitFor(() => {
      expect(screen.getByTestId('bc-pubkey-result')).toBeInTheDocument();
    }, { timeout: 2000 });

    fireEvent.click(screen.getByTestId('bc-pubkey-next'));

    // ── Step 6: DoneStep（自动 finalize）──
    await waitFor(() => {
      expect(screen.getByTestId('bc-done-step')).toBeInTheDocument();
    });

    // 等待 finalize 调用完成
    await waitFor(() => {
      expect(screen.getByTestId('bc-done-success')).toBeInTheDocument();
    }, { timeout: 2000 });

    expect(screen.getByTestId('bc-done-summary')).toHaveTextContent('Miku');

    // 点击完成按钮 → 触发 onComplete
    fireEvent.click(screen.getByTestId('bc-done-complete'));
    expect(onComplete).toHaveBeenCalledTimes(1);
    expect(onComplete.mock.calls[0][0]).toMatchObject({
      name: 'Miku',
      public_key: 'a'.repeat(64),
      color: '#5fb3b3',
    });

    // 验证 finalize 被调用过
    const finalizeCall = calls.find(
      (c) => c.url.endsWith('/ceremony/finalize') && c.method === 'POST',
    );
    expect(finalizeCall).toBeDefined();
    expect(finalizeCall?.body).toMatchObject({
      name: 'Miku',
      color: '#5fb3b3',
      charter_signed: true,
    });
  });

  it('(c) 重名校验：name=taken 时显示占用提示', async () => {
    const { mockFetch } = makeMockFetch();
    render(<CeremonyWizard fetchImpl={mockFetch as unknown as typeof fetch} />);

    const nameInput = screen.getByTestId('bc-name-input') as HTMLInputElement;
    fireEvent.change(nameInput, { target: { value: 'taken' } });

    await waitFor(() => {
      expect(screen.getByTestId('bc-name-taken')).toBeInTheDocument();
    }, { timeout: 2000 });
  });
});
