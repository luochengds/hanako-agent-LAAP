/**
 * SkillPacksPanel.smoke.test.tsx — P2-skill-packs 冒烟测试
 *
 * 验证项（spec L427: P2 冒烟测试即可，不需要完整单元测试覆盖率）：
 * (a) 渲染 SkillPacksPanel 显示 overlay + panel + header
 * (b) 启动时 fetch GET /skills/list?agent_name=X 调用一次
 * (c) 已安装区 + 可用技能包网格渲染 SkillCard
 * (d) 安装按钮 → POST /skills/install 后 refresh 列表
 * (e) 卸载按钮 → POST /skills/uninstall 后 refresh 列表
 * (f) 导出按钮 → POST /skills/export 显示 zip_path 通知
 * (g) 导入按钮 → POST /skills/import 后 refresh 列表
 * (h) charter_compatible=false 显示警告徽章
 * (i) fetch 失败时显示错误消息
 *
 * 使用注入的 fetchImpl mock 避免 sidecar 依赖。
 */

// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest";
import React from "react";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SkillPacksPanel } from "../SkillPacksPanel";
import type { SkillListResponse } from "../types";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

// ── mock fetch 工厂 ──────────────────────────────────────

interface FetchCall {
  url: string;
  method?: string;
  body?: unknown;
}

function makeMockFetch() {
  const calls: FetchCall[] = [];
  const installed = new Map<string, boolean>();

  const mockFetch = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    const method = init?.method || "GET";
    let body: unknown = undefined;
    if (init?.body) {
      try {
        body = JSON.parse(init.body as string);
      } catch {
        body = init.body;
      }
    }
    calls.push({ url, method, body });

    // GET /skills/list?agent_name=X
    if (url.includes("/skills/list")) {
      const u = new URL(url);
      const agent = u.searchParams.get("agent_name") || "aris";
      const response: SkillListResponse = {
        agent_name: agent,
        installed: installed.has("code-review")
          ? [
              {
                skill_id: "code-review",
                agent_name: agent,
                version: "1.2.0",
                author: "aris",
                charter_compatible: true,
                installed_at: "2026-08-01T00:00:00Z",
              },
            ]
          : [],
        available: [
          {
            skill_id: "code-review",
            version: "1.2.0",
            author: "aris",
            charter_compatible: true,
            description: "Code review skill",
          },
          {
            skill_id: "warn-skill",
            version: "0.9.0",
            author: "test",
            charter_compatible: false,
            description: "Skill with charter warning",
          },
        ],
      };
      return new Response(JSON.stringify(response), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }

    // POST /skills/install
    if (url.endsWith("/skills/install") && method === "POST") {
      const skillId = (body as { skill_id?: string })?.skill_id || "";
      installed.set(skillId, true);
      return new Response(
        JSON.stringify({
          installed: true,
          skill_id: skillId,
          version: "1.2.0",
          agent_name: (body as { agent_name?: string })?.agent_name || "aris",
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );
    }

    // POST /skills/uninstall
    if (url.endsWith("/skills/uninstall") && method === "POST") {
      const skillId = (body as { skill_id?: string })?.skill_id || "";
      installed.delete(skillId);
      return new Response(
        JSON.stringify({
          uninstalled: true,
          skill_id: skillId,
          agent_name: (body as { agent_name?: string })?.agent_name || "aris",
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );
    }

    // POST /skills/export
    if (url.endsWith("/skills/export") && method === "POST") {
      const skillId = (body as { skill_id?: string })?.skill_id || "x";
      return new Response(
        JSON.stringify({
          exported: true,
          skill_id: skillId,
          version: "1.2.0",
          zip_path: `/tmp/${skillId}-v1.2.0.zip`,
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );
    }

    // POST /skills/import
    if (url.endsWith("/skills/import") && method === "POST") {
      return new Response(
        JSON.stringify({
          imported: true,
          skill_id: "imported-skill",
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );
    }

    return new Response(JSON.stringify({ error: "not mocked" }), { status: 404 });
  });

  return { mockFetch, calls, installed };
}

// ── 测试用例 ─────────────────────────────────────────────

describe("SkillPacksPanel 冒烟测试", () => {
  it("(a) 渲染 overlay + panel + header", async () => {
    const { mockFetch } = makeMockFetch();
    render(<SkillPacksPanel fetchImpl={mockFetch as unknown as typeof fetch} />);

    expect(screen.getByTestId("sp-overlay")).toBeInTheDocument();
    expect(screen.getByTestId("sp-panel")).toBeInTheDocument();
    expect(screen.getByTestId("sp-agent-name")).toHaveTextContent("aris");
  });

  it("(b) 启动时 fetch GET /skills/list 调用一次", async () => {
    const { mockFetch, calls } = makeMockFetch();
    render(<SkillPacksPanel fetchImpl={mockFetch as unknown as typeof fetch} />);

    await waitFor(() => {
      const listCalls = calls.filter((c) => c.url.includes("/skills/list"));
      expect(listCalls).toHaveLength(1);
    });
    expect(calls[0].url).toContain("/skills/list?agent_name=aris");
  });

  it("(c) 渲染已安装区 + 可用技能包网格 SkillCard", async () => {
    const { mockFetch } = makeMockFetch();
    render(<SkillPacksPanel fetchImpl={mockFetch as unknown as typeof fetch} />);

    // 等待可用区出现两个 SkillCard
    await waitFor(() => {
      expect(screen.getByTestId("sp-card-code-review")).toBeInTheDocument();
      expect(screen.getByTestId("sp-card-warn-skill")).toBeInTheDocument();
    });

    // 已安装区初始为空
    expect(screen.getByTestId("sp-installed-empty")).toBeInTheDocument();
  });

  it("(d) 安装按钮 → POST /skills/install 后 refresh 列表", async () => {
    const { mockFetch, calls } = makeMockFetch();
    render(<SkillPacksPanel fetchImpl={mockFetch as unknown as typeof fetch} />);

    // 等待卡片渲染
    await waitFor(() => {
      expect(screen.getByTestId("sp-card-code-review")).toBeInTheDocument();
    });

    // 点击 code-review 卡片的安装按钮（限定在卡片范围内，避免多卡片多按钮）
    const card = screen.getByTestId("sp-card-code-review");
    fireEvent.click(within(card).getByTestId("sp-btn-install"));

    // 等待 install + refresh（list 再次调用）完成
    await waitFor(() => {
      const installCalls = calls.filter(
        (c) => c.url.endsWith("/skills/install") && c.method === "POST",
      );
      expect(installCalls).toHaveLength(1);
      expect(installCalls[0].body).toMatchObject({
        agent_name: "aris",
        skill_id: "code-review",
      });
    });

    // refresh 后 installed list 应包含 code-review
    await waitFor(() => {
      expect(screen.getByTestId("sp-installed-code-review")).toBeInTheDocument();
    });
  });

  it("(e) 卸载按钮 → POST /skills/uninstall 后 refresh 列表", async () => {
    const { mockFetch, calls, installed } = makeMockFetch();
    // 预设已安装
    installed.set("code-review", true);

    render(<SkillPacksPanel fetchImpl={mockFetch as unknown as typeof fetch} />);

    // 等待列表加载完成（已安装区显示 code-review）
    await waitFor(() => {
      expect(screen.getByTestId("sp-installed-code-review")).toBeInTheDocument();
    });

    // code-review 卡片应显示卸载按钮（已安装）
    fireEvent.click(screen.getByTestId("sp-btn-uninstall"));

    await waitFor(() => {
      const uninstallCalls = calls.filter(
        (c) => c.url.endsWith("/skills/uninstall") && c.method === "POST",
      );
      expect(uninstallCalls).toHaveLength(1);
      expect(uninstallCalls[0].body).toMatchObject({
        agent_name: "aris",
        skill_id: "code-review",
      });
    });

    // refresh 后 installed list 不再包含 code-review
    await waitFor(() => {
      expect(screen.queryByTestId("sp-installed-code-review")).not.toBeInTheDocument();
    });
  });

  it("(f) 导出按钮 → POST /skills/export 显示 zip_path 通知", async () => {
    const { mockFetch, calls } = makeMockFetch();
    render(<SkillPacksPanel fetchImpl={mockFetch as unknown as typeof fetch} />);

    await waitFor(() => {
      expect(screen.getByTestId("sp-card-code-review")).toBeInTheDocument();
    });

    // 点击 code-review 卡片的导出按钮（限定在卡片范围内，避免多卡片多按钮）
    const card = screen.getByTestId("sp-card-code-review");
    fireEvent.click(within(card).getByTestId("sp-btn-export"));

    await waitFor(() => {
      const exportCalls = calls.filter(
        (c) => c.url.endsWith("/skills/export") && c.method === "POST",
      );
      expect(exportCalls).toHaveLength(1);
      expect(exportCalls[0].body).toMatchObject({ skill_id: "code-review" });
    });

    // 通知应包含 zip_path
    await waitFor(() => {
      expect(screen.getByTestId("sp-notice")).toHaveTextContent(
        "/tmp/code-review-v1.2.0.zip",
      );
    });
  });

  it("(g) 导入按钮 → POST /skills/import 后 refresh 列表", async () => {
    const { mockFetch, calls } = makeMockFetch();
    render(<SkillPacksPanel fetchImpl={mockFetch as unknown as typeof fetch} />);

    await waitFor(() => {
      expect(screen.getByTestId("sp-import-input")).toBeInTheDocument();
    });

    const input = screen.getByTestId("sp-import-input") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "/tmp/some-pack-v1.0.0.zip" } });

    fireEvent.click(screen.getByTestId("sp-btn-import"));

    await waitFor(() => {
      const importCalls = calls.filter(
        (c) => c.url.endsWith("/skills/import") && c.method === "POST",
      );
      expect(importCalls).toHaveLength(1);
      expect(importCalls[0].body).toMatchObject({
        zip_path: "/tmp/some-pack-v1.0.0.zip",
      });
    });

    // 导入后通知 + 刷新列表
    await waitFor(() => {
      expect(screen.getByTestId("sp-notice")).toHaveTextContent("imported-skill");
    });
  });

  it("(h) charter_compatible=false 显示 charter warn 徽章", async () => {
    const { mockFetch } = makeMockFetch();
    render(<SkillPacksPanel fetchImpl={mockFetch as unknown as typeof fetch} />);

    await waitFor(() => {
      expect(screen.getByTestId("sp-card-warn-skill")).toBeInTheDocument();
    });

    // warn-skill 卡片应有 warn 徽章（多个 charter badge 取第二个）
    const badges = screen.getAllByTestId("sp-charter-badge");
    const warnBadge = badges.find((b) => b.textContent?.includes("warn"));
    expect(warnBadge).toBeDefined();
    expect(warnBadge?.className).toContain("sp-badge-warn");
  });

  it("(i) fetch 失败时显示错误消息", async () => {
    const failingFetch = vi.fn(async () => {
      throw new Error("network down");
    });

    render(<SkillPacksPanel fetchImpl={failingFetch as unknown as typeof fetch} />);

    await waitFor(() => {
      expect(screen.getByTestId("sp-error")).toHaveTextContent("network down");
    });
  });

  it("(j) onClose 回调触发关闭", async () => {
    const { mockFetch } = makeMockFetch();
    const onClose = vi.fn();
    render(
      <SkillPacksPanel
        fetchImpl={mockFetch as unknown as typeof fetch}
        onClose={onClose}
      />,
    );

    await waitFor(() => {
      expect(screen.getByTestId("sp-close-btn")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId("sp-close-btn"));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
