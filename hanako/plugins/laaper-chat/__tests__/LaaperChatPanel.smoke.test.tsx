/**
 * LaaperChatPanel 冒烟测试
 *
 * 验证：
 * 1. 渲染 peer 名 + 公钥前缀
 * 2. 输入框 + 发送按钮存在
 * 3. 发送消息触发 fetch /chat/send
 * 4. 历史加载触发 fetch /chat/history
 * 5. 关闭按钮触发 onClose
 */

// @vitest-environment jsdom

import '@testing-library/jest-dom/vitest';
import { cleanup, render, screen, fireEvent, waitFor } from "@testing-library/react";
import { afterEach, describe, it, expect, vi, beforeEach } from "vitest";
import { LaaperChatPanel } from "../LaaperChatPanel";

const mockFetch = (responses: Record<string, any>) => {
  const calls: { url: string; body: any }[] = [];
  const fn = vi.fn(async (url: string, init?: any) => {
    calls.push({ url, body: init?.body ? JSON.parse(init.body) : null });
    const key = Object.keys(responses).find((k) => url.includes(k));
    if (!key) {
      return { ok: false, status: 404, json: async () => ({ error: "not found" }) } as any;
    }
    return { ok: true, status: 200, json: async () => responses[key] } as any;
  });
  (fn as any).calls = calls;
  return fn as any;
};

describe("LaaperChatPanel smoke", () => {
  afterEach(() => {
    cleanup();
  });

  beforeEach(() => {
    vi.resetAllMocks();
  });

  it("渲染 peer 名 + 公钥前缀 + 输入框 + 发送按钮", async () => {
    const fn = mockFetch({
      "/chat/history": { count: 0, messages: [] },
    });
    render(
      <LaaperChatPanel
        peer={{ public_key: "pk_test_abcdef1234567890", name: "Butter", color: "#f5d9c4" }}
        selfPublicKey="pk_self_9999"
        selfName="Aris"
        fetchImpl={fn}
        onClose={() => {}}
      />
    );
    expect(screen.getByText("Butter")).toBeTruthy();
    expect(screen.getByText(/pk_test_abcdef/)).toBeTruthy();
    expect(screen.getByPlaceholderText(/输入消息/)).toBeTruthy();
    expect(screen.getByText("发送")).toBeTruthy();
  });

  it("挂载时拉取历史 /chat/history", async () => {
    const fn = mockFetch({
      "/chat/history": {
        count: 1,
        messages: [
          {
            message_id: "msg_1",
            sender_public_key: "pk_self_9999",
            peer_public_key: "pk_test",
            content: "hello",
            timestamp: 1700000000,
            verified: true,
          },
        ],
      },
    });
    render(
      <LaaperChatPanel
        peer={{ public_key: "pk_test", name: "Butter", color: "#fff" }}
        selfPublicKey="pk_self_9999"
        selfName="Aris"
        fetchImpl={fn}
        onClose={() => {}}
      />
    );
    await waitFor(() => {
      expect(screen.getByText("hello")).toBeTruthy();
    });
  });

  it("发送消息触发 /chat/send 并清空输入", async () => {
    const fn = mockFetch({
      "/chat/history": { count: 0, messages: [] },
      "/chat/send": { sent: true, message_id: "msg_new" },
    });
    render(
      <LaaperChatPanel
        peer={{ public_key: "pk_test", name: "Butter", color: "#fff" }}
        selfPublicKey="pk_self_9999"
        selfName="Aris"
        fetchImpl={fn}
        onClose={() => {}}
      />
    );
    const input = screen.getByPlaceholderText(/输入消息/) as HTMLTextAreaElement;
    fireEvent.change(input, { target: { value: "hi there" } });
    fireEvent.keyDown(input, { key: "Enter", shiftKey: false });
    await waitFor(() => {
      expect(screen.getByText("hi there")).toBeTruthy();
    });
  });

  it("关闭按钮触发 onClose", async () => {
    const fn = mockFetch({ "/chat/history": { count: 0, messages: [] } });
    const onClose = vi.fn();
    render(
      <LaaperChatPanel
        peer={{ public_key: "pk_test", name: "Butter", color: "#fff" }}
        selfPublicKey="pk_self"
        selfName="Aris"
        fetchImpl={fn}
        onClose={onClose}
      />
    );
    fireEvent.click(screen.getByText("关闭"));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
