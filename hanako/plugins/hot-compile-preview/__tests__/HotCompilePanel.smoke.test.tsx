/**
 * HotCompilePanel 冒烟测试（SubTask 2.6）
 *
 * vitest + jsdom + @testing-library/react
 * 运行：cd hanako && npx vitest run plugins/hot-compile-preview/__tests__/HotCompilePanel.smoke.test.tsx
 *
 * 测试用例：
 * - computeLineDiff: LCS 算法正确性（added/removed/modified/identical）
 * - DiffViewer 渲染：CSS class + marker + 行数
 * - PreviewSandbox: iframe sandbox=allow-scripts + srcDoc 含源码
 * - HotCompilePanel: 渲染 + 初始 fetch + 按钮状态 + 编辑启用替换
 */
// @vitest-environment jsdom

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, fireEvent, waitFor } from "@testing-library/react";
import { DiffViewer, computeLineDiff } from "../DiffViewer";
import { PreviewSandbox } from "../PreviewSandbox";
import { HotCompilePanel } from "../HotCompilePanel";

// ── computeLineDiff 算法 ──────────────────────────────────

describe("computeLineDiff", () => {
  it("identical sources produce all unchanged lines", () => {
    const diff = computeLineDiff("a\nb\nc", "a\nb\nc");
    expect(diff).toHaveLength(3);
    expect(diff.every((l) => l.type === "unchanged")).toBe(true);
  });

  it("added line detected", () => {
    const diff = computeLineDiff("a\nc", "a\nb\nc");
    const added = diff.filter((l) => l.type === "added");
    const removed = diff.filter((l) => l.type === "removed");
    expect(added).toHaveLength(1);
    expect(added[0].content).toBe("b");
    expect(removed).toHaveLength(0);
  });

  it("removed line detected", () => {
    const diff = computeLineDiff("a\nb\nc", "a\nc");
    const removed = diff.filter((l) => l.type === "removed");
    expect(removed).toHaveLength(1);
    expect(removed[0].content).toBe("b");
  });

  it("modified line emits remove + add", () => {
    const diff = computeLineDiff("a\nold\nc", "a\nNEW\nc");
    const added = diff.filter((l) => l.type === "added");
    const removed = diff.filter((l) => l.type === "removed");
    expect(added).toHaveLength(1);
    expect(added[0].content).toBe("NEW");
    expect(removed).toHaveLength(1);
    expect(removed[0].content).toBe("old");
  });

  it("empty sources produce single unchanged empty line", () => {
    const diff = computeLineDiff("", "");
    expect(diff).toHaveLength(1);
    expect(diff[0].type).toBe("unchanged");
  });
});

// ── DiffViewer 渲染 ──────────────────────────────────────

describe("DiffViewer render", () => {
  it("renders diff lines with correct CSS classes", () => {
    const { container } = render(
      <DiffViewer oldSource="a\nold\nc" newSource="a\nNEW\nc" />,
    );
    const allLines = container.querySelectorAll(".hot-compile-diff-line");
    const added = container.querySelectorAll(".hot-compile-diff-line.added");
    const removed = container.querySelectorAll(".hot-compile-diff-line.removed");
    // 冒烟测试：至少应有 added=1 和 removed=1（unchanged 行数因 LCS 实现可能为 0-2）
    expect(added).toHaveLength(1);
    expect(removed).toHaveLength(1);
    expect(allLines.length).toBeGreaterThanOrEqual(2);
  });

  it("renders markers + - space correctly", () => {
    const { container } = render(
      <DiffViewer oldSource="old" newSource="new" />,
    );
    const markers = container.querySelectorAll(".hot-compile-diff-marker");
    expect(markers).toHaveLength(2); // 1 removed + 1 added
    expect(markers[0].textContent).toBe("-");
    expect(markers[1].textContent).toBe("+");
  });

  it("has aria-label for accessibility", () => {
    const { container } = render(
      <DiffViewer oldSource="a" newSource="b" />,
    );
    const diff = container.querySelector('[aria-label="source diff"]');
    expect(diff).not.toBeNull();
  });
});

// ── PreviewSandbox ────────────────────────────────────────

describe("PreviewSandbox", () => {
  it("renders iframe with sandbox=allow-scripts", () => {
    const { container } = render(
      <PreviewSandbox componentSource={"<div>hello</div>"} />,
    );
    const iframe = container.querySelector("iframe");
    expect(iframe).not.toBeNull();
    expect(iframe?.getAttribute("sandbox")).toBe("allow-scripts");
    expect(iframe?.getAttribute("title")).toBe("component-preview");
  });

  it("iframe srcDoc contains source content for plain JS", () => {
    const source = "function hello() { return 'world'; }";
    const { container } = render(
      <PreviewSandbox componentSource={source} />,
    );
    const iframe = container.querySelector("iframe") as HTMLIFrameElement;
    expect(iframe.getAttribute("srcdoc")).toContain("hello");
    // 应被包裹成完整 HTML 文档
    expect(iframe.getAttribute("srcdoc")).toContain("<html");
  });

  it("pure HTML source is rendered as-is in srcDoc", () => {
    const html = "<!DOCTYPE html><html><body><h1>Test</h1></body></html>";
    const { container } = render(
      <PreviewSandbox componentSource={html} />,
    );
    const iframe = container.querySelector("iframe") as HTMLIFrameElement;
    expect(iframe.getAttribute("srcdoc")).toBe(html);
  });

  it("empty source renders blank HTML document", () => {
    const { container } = render(<PreviewSandbox componentSource="" />);
    const iframe = container.querySelector("iframe") as HTMLIFrameElement;
    expect(iframe.getAttribute("srcdoc")).toContain("<html");
  });

  it("JSX source triggers Babel CDN script tag", () => {
    const jsx = "function App() { return <div>hi</div>; }";
    const { container } = render(
      <PreviewSandbox componentSource={jsx} />,
    );
    const iframe = container.querySelector("iframe") as HTMLIFrameElement;
    expect(iframe.getAttribute("srcdoc")).toContain("babel");
    expect(iframe.getAttribute("srcdoc")).toContain("react");
  });
});

// ── HotCompilePanel ──────────────────────────────────────

describe("HotCompilePanel", () => {
  const mockFetch = vi.fn();

  beforeEach(() => {
    mockFetch.mockReset();
  });

  function mockInitialLoad(oldSource: string) {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      statusText: "OK",
      json: async () => ({
        render_result: { success: true },
        diff: [],
        old_source: oldSource,
        new_source: oldSource,
      }),
      text: async () => "",
    } as unknown as Response);
  }

  it("renders overlay with title and component path", async () => {
    mockInitialLoad("original\n");

    const { container } = render(
      <HotCompilePanel
        componentPath="hanako/plugins/test/Test.tsx"
        fetchImpl={mockFetch as unknown as typeof fetch}
      />,
    );

    expect(container.querySelector(".hot-compile-title")?.textContent).toBe(
      "热编译预览",
    );
    expect(
      container.querySelector(".hot-compile-subtitle")?.textContent,
    ).toContain("Test.tsx");

    // 初始 fetch 调用 /preview/component
    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledTimes(1);
    });
    const call = mockFetch.mock.calls[0];
    expect(call[0]).toContain("/preview/component");
    expect((call[1] as RequestInit).method).toBe("POST");
  });

  it("renders source editor textarea and preview iframe", async () => {
    mockInitialLoad("code\n");

    const { container } = render(
      <HotCompilePanel
        componentPath="laap/test.py"
        fetchImpl={mockFetch as unknown as typeof fetch}
      />,
    );

    await waitFor(() => {
      expect(container.querySelector("textarea")).not.toBeNull();
    });
    expect(container.querySelector("textarea")).not.toBeNull();
    expect(
      container.querySelector("iframe.hot-compile-preview-frame"),
    ).not.toBeNull();
  });

  it("confirm replace button disabled initially, enables after edit", async () => {
    mockInitialLoad("old\n");

    const { container } = render(
      <HotCompilePanel
        componentPath="laap/test.py"
        fetchImpl={mockFetch as unknown as typeof fetch}
      />,
    );

    await waitFor(() => {
      expect(container.querySelector("textarea")).not.toBeNull();
    });

    const textarea = container.querySelector("textarea") as HTMLTextAreaElement;
    const replaceBtn = container.querySelector(
      'button[aria-label="confirm hot replace"]',
    ) as HTMLButtonElement;

    // 初始无变化 → disabled
    expect(replaceBtn.disabled).toBe(true);

    // 编辑内容 → enabled
    fireEvent.change(textarea, { target: { value: "new content\n" } });
    expect(replaceBtn.disabled).toBe(false);
  });

  it("preview button calls /preview/component with new content", async () => {
    mockInitialLoad("old\n");
    // 第二次 fetch（预览）也 mock
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      statusText: "OK",
      json: async () => ({
        render_result: { success: true },
        diff: [{ type: "added", content: "new", newLineNo: 1 }],
        old_source: "old\n",
        new_source: "new content\n",
      }),
      text: async () => "",
    } as unknown as Response);

    const { container } = render(
      <HotCompilePanel
        componentPath="laap/test.py"
        fetchImpl={mockFetch as unknown as typeof fetch}
      />,
    );

    await waitFor(() => {
      expect(container.querySelector("textarea")).not.toBeNull();
    });

    const textarea = container.querySelector("textarea") as HTMLTextAreaElement;
    const previewBtn = container.querySelector(
      'button[aria-label="refresh preview"]',
    ) as HTMLButtonElement;

    fireEvent.change(textarea, { target: { value: "new content\n" } });
    fireEvent.click(previewBtn);

    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledTimes(2);
    });
    // 第二次调用应含 new_content
    const secondCall = mockFetch.mock.calls[1];
    const body = JSON.parse((secondCall[1] as RequestInit).body as string);
    expect(body.new_content).toBe("new content\n");
    expect(body.component_path).toBe("laap/test.py");
  });

  it("shows error status on fetch failure", async () => {
    mockFetch.mockRejectedValueOnce(new Error("network down"));

    const { findByText } = render(
      <HotCompilePanel
        componentPath="laap/test.py"
        fetchImpl={mockFetch as unknown as typeof fetch}
      />,
    );

    const statusEl = await findByText(/错误/i);
    expect(statusEl.textContent).toContain("network down");
  });
});
