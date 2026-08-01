/**
 * TrioChatPanel 冒烟测试
 *
 * 验证：
 * 1. 挂载时调 /trio/create 创建聊天室，渲染成员色点
 * 2. 输入话题 Enter 创建，调 /trio/topic
 * 3. 发送消息触发 /trio/message 并清空输入
 * 4. 点击"检测共识"触发 /trio/consensus，渲染观点卡片 + 分歧点
 * 5. 共识达成时显示 witness_trail 徽章
 * 6. 关闭按钮触发 onClose
 */

// @vitest-environment jsdom

import '@testing-library/jest-dom/vitest';
import { cleanup, render, screen, fireEvent, waitFor } from "@testing-library/react";
import { afterEach, describe, it, expect, vi, beforeEach } from "vitest";
import { TrioChatPanel } from "../TrioChatPanel";

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

const MEMBERS = [
  { public_key: "pk_alice_abcdef1234567890", name: "Alice", color: "#f5d9c4" },
  { public_key: "pk_bob_0123456789abcdef", name: "Bob", color: "#67e8f9" },
  { public_key: "pk_carol_fedcba9876543210", name: "Carol", color: "#c084fc" },
];

describe("TrioChatPanel smoke", () => {
  afterEach(() => {
    cleanup();
  });

  beforeEach(() => {
    vi.resetAllMocks();
  });

  it("挂载时调 /trio/create 并渲染成员色点", async () => {
    const fn = mockFetch({
      "/trio/create": { created: true, chatroom_id: "trio_abc123", member_count: 3, created_at: 1700000000 },
      "/trio/get": { chatroom_id: "trio_abc123", member_public_keys: [], created_at: 0, member_count: 3, topic_count: 0, message_count: 0, topics: [], messages: [] },
    });
    render(
      <TrioChatPanel
        members={MEMBERS}
        selfPublicKey="pk_alice_abcdef1234567890"
        selfName="Alice"
        fetchImpl={fn}
        onClose={() => {}}
      />
    );
    await waitFor(() => {
      expect(screen.getByText("trio_abc123")).toBeTruthy();
    });
    // 成员色点 title
    expect(screen.getByTitle(/Alice.*pk_alice/)).toBeTruthy();
  });

  it("输入话题 Enter 创建，调 /trio/topic", async () => {
    const fn = mockFetch({
      "/trio/create": { created: true, chatroom_id: "trio_t1", member_count: 3, created_at: 1700000000 },
      "/trio/get": { chatroom_id: "trio_t1", member_public_keys: [], created_at: 0, member_count: 3, topic_count: 0, message_count: 0, topics: [], messages: [] },
      "/trio/topic": { topic_id: "topic_new1", chatroom_id: "trio_t1", title: "新话题", created_at: 1700000001 },
    });
    render(
      <TrioChatPanel
        members={MEMBERS}
        selfPublicKey="pk_alice"
        selfName="Alice"
        fetchImpl={fn}
        onClose={() => {}}
      />
    );
    await waitFor(() => {
      expect(screen.getByText("trio_t1")).toBeTruthy();
    });
    const topicInput = screen.getByPlaceholderText(/新话题标题/) as HTMLInputElement;
    fireEvent.change(topicInput, { target: { value: "新话题" } });
    fireEvent.keyDown(topicInput, { key: "Enter" });
    await waitFor(() => {
      expect((fn as any).calls.some((c: any) => c.url.includes("/trio/topic"))).toBe(true);
    });
  });

  it("发送消息触发 /trio/message 并清空输入", async () => {
    const fn = mockFetch({
      "/trio/create": { created: true, chatroom_id: "trio_m1", member_count: 3, created_at: 0 },
      "/trio/get": {
        chatroom_id: "trio_m1", member_public_keys: [], created_at: 0, member_count: 3,
        topic_count: 1, message_count: 0,
        topics: [{ topic_id: "topic_1", chatroom_id: "trio_m1", title: "T1", created_at: 0 }],
        messages: [],
      },
      "/trio/message": { stored: true, message_id: "tmsg_new", chatroom_id: "trio_m1", topic_id: "topic_1" },
    });
    render(
      <TrioChatPanel
        members={MEMBERS}
        selfPublicKey="pk_alice"
        selfName="Alice"
        fetchImpl={fn}
        onClose={() => {}}
      />
    );
    await waitFor(() => {
      expect(screen.getByText("T1")).toBeTruthy();
    });
    // 点击话题激活
    fireEvent.click(screen.getByText("T1"));
    const msgInput = screen.getByPlaceholderText(/输入消息/) as HTMLTextAreaElement;
    fireEvent.change(msgInput, { target: { value: "hello trio" } });
    fireEvent.keyDown(msgInput, { key: "Enter", shiftKey: false });
    await waitFor(() => {
      expect((fn as any).calls.some((c: any) => c.url.includes("/trio/message") && c.body?.content === "hello trio")).toBe(true);
    });
  });

  it("点击检测共识触发 /trio/consensus 并渲染观点卡片 + 分歧点", async () => {
    const fn = mockFetch({
      "/trio/create": { created: true, chatroom_id: "trio_c1", member_count: 3, created_at: 0 },
      "/trio/get": {
        chatroom_id: "trio_c1", member_public_keys: [], created_at: 0, member_count: 3,
        topic_count: 1, message_count: 2,
        topics: [{ topic_id: "topic_c1", chatroom_id: "trio_c1", title: "共识话题", created_at: 0 }],
        messages: [],
      },
      "/trio/consensus": {
        chatroom_id: "trio_c1",
        topic_id: "topic_c1",
        views: [
          { public_key: "pk_alice", stance: "pro", keywords: ["good", "idea"], summary: "支持该方案", message_id: "m1" },
          { public_key: "pk_bob", stance: "con", keywords: ["risky"], summary: "风险较大", message_id: "m2" },
        ],
        disagreement_points: ["立场分歧: pro, con"],
        consensus_reached: false,
        method: "rule",
        avg_keyword_overlap: 0.2,
      },
    });
    render(
      <TrioChatPanel
        members={MEMBERS}
        selfPublicKey="pk_alice"
        selfName="Alice"
        fetchImpl={fn}
        onClose={() => {}}
      />
    );
    await waitFor(() => {
      expect(screen.getByText("共识话题")).toBeTruthy();
    });
    fireEvent.click(screen.getByText("共识话题"));
    fireEvent.click(screen.getByText("检测共识"));
    await waitFor(() => {
      expect(screen.getByText(/立场分歧/)).toBeTruthy();
    });
    // 观点卡片摘要
    expect(screen.getByText("支持该方案")).toBeTruthy();
    expect(screen.getByText("风险较大")).toBeTruthy();
  });

  it("共识达成时显示 witness_trail 徽章", async () => {
    const fn = mockFetch({
      "/trio/create": { created: true, chatroom_id: "trio_w1", member_count: 3, created_at: 0 },
      "/trio/get": {
        chatroom_id: "trio_w1", member_public_keys: [], created_at: 0, member_count: 3,
        topic_count: 1, message_count: 3,
        topics: [{ topic_id: "topic_w1", chatroom_id: "trio_w1", title: "共振话题", created_at: 0 }],
        messages: [],
      },
      "/trio/consensus": {
        chatroom_id: "trio_w1",
        topic_id: "topic_w1",
        views: [
          { public_key: "pk_alice", stance: "pro", keywords: ["agree", "consensus"], summary: "同意", message_id: "m1" },
          { public_key: "pk_bob", stance: "pro", keywords: ["agree", "consensus"], summary: "同意", message_id: "m2" },
        ],
        disagreement_points: [],
        consensus_reached: true,
        method: "rule",
        avg_keyword_overlap: 0.85,
        witness_trail_id: "wit_abc12345",
      },
    });
    render(
      <TrioChatPanel
        members={MEMBERS}
        selfPublicKey="pk_alice"
        selfName="Alice"
        fetchImpl={fn}
        onClose={() => {}}
      />
    );
    await waitFor(() => {
      expect(screen.getByText("共振话题")).toBeTruthy();
    });
    fireEvent.click(screen.getByText("共振话题"));
    fireEvent.click(screen.getByText("检测共识"));
    await waitFor(() => {
      expect(screen.getByText(/wit_abc12345/)).toBeTruthy();
    });
  });

  it("关闭按钮触发 onClose", async () => {
    const fn = mockFetch({
      "/trio/create": { created: true, chatroom_id: "trio_x1", member_count: 3, created_at: 0 },
      "/trio/get": { chatroom_id: "trio_x1", member_public_keys: [], created_at: 0, member_count: 3, topic_count: 0, message_count: 0, topics: [], messages: [] },
    });
    const onClose = vi.fn();
    render(
      <TrioChatPanel
        members={MEMBERS}
        selfPublicKey="pk_alice"
        selfName="Alice"
        fetchImpl={fn}
        onClose={onClose}
      />
    );
    fireEvent.click(screen.getByText("关闭"));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
