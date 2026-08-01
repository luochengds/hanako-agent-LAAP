import { describe, expect, it } from "vitest";
import { EnvChangeLedger } from "../core/env-change-ledger.ts";
import {
  applyReminderConsumption,
  collectReminderBlock,
  noteTimeObservedForSession,
  REMINDER_BLOCK_END,
  REMINDER_BLOCK_PREFIX,
  stripSessionReminderBlocks,
  TIME_STALENESS_MS,
} from "../core/session-reminders.ts";

function freshSessionEntry(overrides: Record<string, unknown> = {}) {
  return {
    reminderEnvCursor: 0,
    reminderEnvStartSeq: 0,
    lastTimeObservedAt: Date.now(),
    reminderCompactionRevision: 0,
    reminderConsumedCompactionRevision: 0,
    reminderAcceptedUnavailableToolNames: [],
    reminderUnavailableRevision: 0,
    ...overrides,
  };
}

function render(
  entry: any,
  ledger: EnvChangeLedger,
  now = Date.now(),
  isZh = true,
  recipientAgentId = "agent-a",
  unavailableToolNames: string[] = [],
) {
  return collectReminderBlock({
    sessionEntry: entry,
    ledger,
    now,
    isZh,
    timeZone: "UTC",
    recipientAgentId,
    unavailableToolNames,
  });
}

describe("EnvChangeLedger", () => {
  it("keeps immutable append order and bounded reads", () => {
    const ledger = new EnvChangeLedger();
    const first = ledger.append({
      type: "memory_facts",
      scope: { kind: "agent", agentId: "agent-a" },
      payload: { addedLines: ["first"] },
    });
    const second = ledger.append({
      type: "memory_facts",
      scope: { kind: "agent", agentId: "agent-a" },
      payload: { addedLines: ["second"] },
    });

    expect([first.seq, second.seq, ledger.maxSeq()]).toEqual([1, 2, 2]);
    expect(ledger.entriesAfter(0, 1)).toEqual([first]);
    expect(ledger.entriesAfter(1)).toEqual([second]);
    expect(Object.isFrozen(first)).toBe(true);
    expect(Object.isFrozen(first.scope)).toBe(true);
    expect(Object.isFrozen(first.payload)).toBe(true);
    expect(Object.isFrozen((second.payload as any).addedLines)).toBe(true);
  });

  it("rejects event scopes that do not match their event type", () => {
    const ledger = new EnvChangeLedger();

    expect(() => ledger.append({
      type: "memory_facts",
      scope: { kind: "global" },
      payload: { addedLines: ["private"] },
    } as any)).toThrow(/scope/i);
    expect(() => ledger.append({
      type: "memory_facts",
      scope: { kind: "agent", agentId: "" },
      payload: { addedLines: ["private"] },
    } as any)).toThrow(/agent scope/i);
    expect(ledger.maxSeq()).toBe(0);
  });
});

describe("collectReminderBlock", () => {
  it("renders exact unavailable frozen names in canonical order and ignores live additions", () => {
    const ledger = new EnvChangeLedger();
    const result = render(
      freshSessionEntry(),
      ledger,
      Date.now(),
      true,
      "agent-a",
      ["mcp_zeta", "mcp_alpha", "mcp_alpha"],
    );

    expect(result?.block).toContain("以下会话工具当前不可用：mcp_alpha、mcp_zeta");
    expect(result?.receipt.unavailableToolNames).toEqual(["mcp_alpha", "mcp_zeta"]);
  });

  it("renders memory facts, English copy, and a 24-hour timezone timestamp", () => {
    const ledger = new EnvChangeLedger();
    ledger.append({
      type: "memory_facts",
      scope: { kind: "agent", agentId: "agent-a" },
      payload: { addedLines: ["likes tea", "lives in Kyoto"] },
    });
    const now = new Date("2026-07-05T14:05:00Z").getTime();

    const result = render(freshSessionEntry({ lastTimeObservedAt: null }), ledger, now, false);
    expect(REMINDER_BLOCK_PREFIX).toBe("[hana_reminder");
    expect(REMINDER_BLOCK_END).toBe("[/hana_reminder]");
    expect(result?.block).toBe(
      "[hana_reminder at 2026-07-05 14:05]\n"
      + "- New memory facts recorded: likes tea; lives in Kyoto\n"
      + "- Current time: 2026-07-05 14:05\n"
      + "[/hana_reminder]",
    );
  });

  it("delivers memory facts only to their owning agent", () => {
    const ledger = new EnvChangeLedger();
    ledger.append({
      type: "memory_facts",
      scope: { kind: "agent", agentId: "agent-a" },
      payload: { addedLines: ["agent-a private fact"] },
    });

    const agentA = render(freshSessionEntry(), ledger, Date.now(), true, "agent-a");
    const agentB = render(freshSessionEntry(), ledger, Date.now(), true, "agent-b");

    expect(agentA?.block).toContain("agent-a private fact");
    expect(agentB).toBeNull();
  });

  it("does not render an empty block when only another agent has pending changes", () => {
    const ledger = new EnvChangeLedger();
    ledger.append({
      type: "memory_facts",
      scope: { kind: "agent", agentId: "agent-a" },
      payload: { addedLines: ["agent-a only"] },
    });

    expect(render(freshSessionEntry(), ledger, Date.now(), true, "agent-b")).toBeNull();
  });

  it("uses strict greater-than for the three-hour time threshold", () => {
    const ledger = new EnvChangeLedger();
    const now = Date.now();
    expect(render(freshSessionEntry({ lastTimeObservedAt: now - TIME_STALENESS_MS }), ledger, now)).toBeNull();
    expect(render(freshSessionEntry({ lastTimeObservedAt: now - TIME_STALENESS_MS - 1 }), ledger, now)?.block)
      .toContain("当前时间");
    expect(render(freshSessionEntry({ lastTimeObservedAt: null }), ledger, now)?.block).toContain("当前时间");
  });

  it("replays environment changes from the session baseline after compaction", () => {
    const ledger = new EnvChangeLedger();
    ledger.append({
      type: "memory_facts",
      scope: { kind: "agent", agentId: "agent-a" },
      payload: { addedLines: ["before"] },
    });
    const entry = freshSessionEntry({
      reminderEnvCursor: 1,
      reminderEnvStartSeq: 0,
      reminderCompactionRevision: 1,
      lastTimeObservedAt: Date.now(),
    });

    const result = render(entry, ledger);
    expect(result?.block).toContain("上下文已压缩");
    expect(result?.block).toContain("before");
  });

  it("replays only matching agent changes after compaction", () => {
    const ledger = new EnvChangeLedger();
    ledger.append({
      type: "memory_facts",
      scope: { kind: "agent", agentId: "agent-a" },
      payload: { addedLines: ["agent-a replay"] },
    });
    ledger.append({
      type: "memory_facts",
      scope: { kind: "agent", agentId: "agent-b" },
      payload: { addedLines: ["agent-b replay"] },
    });
    const entry = freshSessionEntry({
      reminderEnvCursor: 2,
      reminderEnvStartSeq: 0,
      reminderCompactionRevision: 1,
      lastTimeObservedAt: Date.now(),
    });

    const result = render(entry, ledger, Date.now(), true, "agent-a");

    expect(result?.block).toContain("上下文已压缩");
    expect(result?.block).toContain("agent-a replay");
    expect(result?.block).not.toContain("agent-b replay");
    expect(result?.receipt.throughSeq).toBe(2);
  });

  it("caps the rendered body and returns a frozen receipt", () => {
    const ledger = new EnvChangeLedger();
    ledger.append({
      type: "memory_facts",
      scope: { kind: "agent", agentId: "agent-a" },
      payload: { addedLines: ["x".repeat(500)] },
    });
    const result = render(freshSessionEntry(), ledger, new Date("2026-07-05T14:05:00Z").getTime());
    const header = `${REMINDER_BLOCK_PREFIX} at 2026-07-05 14:05]\n`;
    const body = result!.block.slice(header.length, -(`\n${REMINDER_BLOCK_END}`.length));

    expect(body.endsWith("…")).toBe(true);
    expect(body.length).toBe(300);
    expect(Object.isFrozen(result)).toBe(true);
    expect(Object.isFrozen(result!.receipt)).toBe(true);
  });
});

describe("stripSessionReminderBlocks", () => {
  it("removes every internal reminder block while preserving user text", () => {
    const visible = stripSessionReminderBlocks(
      "[hana_reminder at 2026-07-05 14:05]\n"
      + "- Current time: 2026-07-05 14:05\n"
      + "[/hana_reminder]\n\n"
      + "hello\n"
      + "[hana_reminder at 2026-07-05 17:05]\n"
      + "- Plugin secret loaded\n"
      + "[/hana_reminder]\n"
      + "world",
    );

    expect(visible).toBe("hello\nworld");
    expect(visible).not.toContain("hana_reminder");
    expect(visible).not.toContain("Plugin secret");
  });

  it("fails closed for an exact reminder header without a closing tag", () => {
    expect(stripSessionReminderBlocks(
      "visible\n[hana_reminder at 2026-07-05 14:05]\n- internal only",
    )).toBe("visible");
  });
});

describe("reminder receipt consumption", () => {
  it("does not consume a ledger event appended after render", () => {
    const ledger = new EnvChangeLedger();
    ledger.append({
      type: "memory_facts",
      scope: { kind: "agent", agentId: "agent-a" },
      payload: { addedLines: ["rendered"] },
    });
    const now = Date.now();
    const entry = freshSessionEntry({ lastTimeObservedAt: now });
    const rendered = render(entry, ledger, now)!;

    ledger.append({
      type: "memory_facts",
      scope: { kind: "agent", agentId: "agent-a" },
      payload: { addedLines: ["later"] },
    });
    applyReminderConsumption({ sessionEntry: entry, receipt: rendered.receipt });

    const next = render(entry, ledger, now + 1);
    expect(next?.block).not.toContain("rendered");
    expect(next?.block).toContain("later");
  });

  it("advances the global cursor through filtered mixed-agent events without replaying them", () => {
    const ledger = new EnvChangeLedger();
    ledger.append({
      type: "memory_facts",
      scope: { kind: "agent", agentId: "agent-a" },
      payload: { addedLines: ["a-first"] },
    });
    ledger.append({
      type: "memory_facts",
      scope: { kind: "agent", agentId: "agent-b" },
      payload: { addedLines: ["b-hidden"] },
    });
    const now = Date.now();
    const entry = freshSessionEntry({ lastTimeObservedAt: now });

    const first = render(entry, ledger, now, true, "agent-a")!;
    expect(first.block).toContain("a-first");
    expect(first.block).not.toContain("b-hidden");
    expect(first.receipt.throughSeq).toBe(2);
    applyReminderConsumption({ sessionEntry: entry, receipt: first.receipt });
    expect(entry.reminderEnvCursor).toBe(2);

    ledger.append({
      type: "memory_facts",
      scope: { kind: "agent", agentId: "agent-b" },
      payload: { addedLines: ["b-later-hidden"] },
    });
    ledger.append({
      type: "memory_facts",
      scope: { kind: "agent", agentId: "agent-a" },
      payload: { addedLines: ["a-later"] },
    });
    const second = render(entry, ledger, now + 1, true, "agent-a")!;
    expect(second.block).toContain("a-later");
    expect(second.block).not.toContain("b-later-hidden");
    expect(second.block).not.toContain("a-first");
    expect(second.receipt.throughSeq).toBe(4);
    applyReminderConsumption({ sessionEntry: entry, receipt: second.receipt });
    expect(entry.reminderEnvCursor).toBe(4);
    expect(render(entry, ledger, now + 2, true, "agent-a")).toBeNull();
  });

  it("does not clear a compaction revision created after render", () => {
    const ledger = new EnvChangeLedger();
    const now = Date.now();
    const entry = freshSessionEntry({
      reminderCompactionRevision: 1,
      lastTimeObservedAt: now,
    });
    const rendered = render(entry, ledger, now)!;

    entry.reminderCompactionRevision = 2;
    applyReminderConsumption({ sessionEntry: entry, receipt: rendered.receipt });

    expect(entry.reminderConsumedCompactionRevision).toBe(1);
    expect(render(entry, ledger, now + 1)?.block).toContain("上下文已压缩");
  });

  it("does not move a current_status observation backwards when consuming an old receipt", () => {
    const ledger = new EnvChangeLedger();
    const renderedAt = Date.now();
    const observedLater = renderedAt + 10_000;
    const entry = freshSessionEntry({ lastTimeObservedAt: null });
    const rendered = render(entry, ledger, renderedAt)!;

    noteTimeObservedForSession(entry, observedLater);
    applyReminderConsumption({ sessionEntry: entry, receipt: rendered.receipt });

    expect(entry.lastTimeObservedAt).toBe(observedLater);
  });

  it("advances all represented state monotonically", () => {
    const ledger = new EnvChangeLedger();
    ledger.append({
      type: "memory_facts",
      scope: { kind: "agent", agentId: "agent-a" },
      payload: { addedLines: ["demo"] },
    });
    const now = Date.now();
    const entry = freshSessionEntry({
      lastTimeObservedAt: null,
      reminderCompactionRevision: 2,
      reminderConsumedCompactionRevision: 1,
    });
    const rendered = render(entry, ledger, now)!;
    applyReminderConsumption({ sessionEntry: entry, receipt: rendered.receipt });

    expect(entry).toMatchObject({
      reminderEnvCursor: 1,
      lastTimeObservedAt: now,
      reminderCompactionRevision: 2,
      reminderConsumedCompactionRevision: 2,
    });
    expect(render(entry, ledger, now + 1)).toBeNull();
  });

  it("repeats a failed outage, accepts it once, and does not repeat the same outage", () => {
    const ledger = new EnvChangeLedger();
    const now = Date.now();
    const entry = freshSessionEntry({ lastTimeObservedAt: now });

    const failed = render(entry, ledger, now, true, "agent-a", ["mcp_calendar"]);
    expect(failed?.block).toContain("mcp_calendar");
    expect(render(entry, ledger, now + 1, true, "agent-a", ["mcp_calendar"])?.block)
      .toContain("mcp_calendar");

    applyReminderConsumption({ sessionEntry: entry, receipt: failed!.receipt });
    expect(entry.reminderAcceptedUnavailableToolNames).toEqual(["mcp_calendar"]);
    expect(entry.reminderUnavailableRevision).toBe(1);
    expect(render(entry, ledger, now + 2, true, "agent-a", ["mcp_calendar"]))
      .toBeNull();
  });

  it("silently accepts recovery without consuming time, memory, or compaction state", () => {
    const ledger = new EnvChangeLedger();
    const now = Date.now();
    const entry = freshSessionEntry({
      reminderEnvCursor: 7,
      reminderEnvStartSeq: 7,
      lastTimeObservedAt: now,
      reminderCompactionRevision: 2,
      reminderConsumedCompactionRevision: 2,
      reminderAcceptedUnavailableToolNames: ["mcp_calendar"],
      reminderUnavailableRevision: 1,
    });

    const recovered = render(entry, ledger, now + 1, true, "agent-a", []);
    expect(recovered?.block).toBe("");
    expect(recovered?.receipt.consumeBlockState).toBe(false);
    applyReminderConsumption({ sessionEntry: entry, receipt: recovered!.receipt });

    expect(entry).toMatchObject({
      reminderEnvCursor: 7,
      lastTimeObservedAt: now,
      reminderConsumedCompactionRevision: 2,
      reminderAcceptedUnavailableToolNames: [],
      reminderUnavailableRevision: 2,
    });
    expect(render(entry, ledger, now + 2, true, "agent-a", ["mcp_calendar"])?.block)
      .toContain("mcp_calendar");
  });

  it("removes recovered names and accepts only newly rendered outage names", () => {
    const ledger = new EnvChangeLedger();
    const now = Date.now();
    const entry = freshSessionEntry({
      lastTimeObservedAt: now,
      reminderAcceptedUnavailableToolNames: ["tool_a", "tool_b"],
      reminderUnavailableRevision: 4,
    });

    const rendered = render(entry, ledger, now, true, "agent-a", ["tool_b", "tool_c"]);
    expect(rendered?.block).toContain("tool_c");
    expect(rendered?.block).not.toContain("tool_a");
    expect(rendered?.receipt.unavailableToolNames).toEqual(["tool_b", "tool_c"]);
  });

  it("batches long outage lists without truncating a name or consuming unseen names", () => {
    const ledger = new EnvChangeLedger();
    ledger.append({
      type: "memory_facts",
      scope: { kind: "agent", agentId: "agent-a" },
      payload: { addedLines: ["context".repeat(80)] },
    });
    const now = Date.now();
    const entry = freshSessionEntry({ lastTimeObservedAt: now });
    const unavailable = Array.from(
      { length: 24 },
      (_, index) => `mcp_connector_${String(index).padStart(2, "0")}_${"x".repeat(18)}`,
    );
    const seen = new Set<string>();

    for (let turn = 0; turn < 10 && seen.size < unavailable.length; turn += 1) {
      const before = new Set(entry.reminderAcceptedUnavailableToolNames);
      const rendered = render(entry, ledger, now + turn, true, "agent-a", unavailable)!;
      const body = rendered.block.slice(
        rendered.block.indexOf("\n") + 1,
        -(`\n${REMINDER_BLOCK_END}`.length),
      );
      expect(body.length).toBeLessThanOrEqual(300);
      const newlyAccepted = rendered.receipt.unavailableToolNames.filter((name) => !before.has(name));
      expect(newlyAccepted.length).toBeGreaterThan(0);
      for (const name of newlyAccepted) {
        expect(rendered.block).toContain(name);
        seen.add(name);
      }
      for (const name of unavailable.filter((name) => !seen.has(name))) {
        expect(rendered.receipt.unavailableToolNames).not.toContain(name);
      }
      applyReminderConsumption({ sessionEntry: entry, receipt: rendered.receipt });
    }

    expect([...seen].sort()).toEqual([...unavailable].sort());
    expect(render(entry, ledger, now + 20, true, "agent-a", unavailable)).toBeNull();
  });

  it("does not let an older accepted receipt roll availability state backwards", () => {
    const ledger = new EnvChangeLedger();
    const now = Date.now();
    const entry = freshSessionEntry({ lastTimeObservedAt: now });
    const staleOutage = render(entry, ledger, now, true, "agent-a", ["tool_old"])!;
    const newerOutage = render(entry, ledger, now + 1, true, "agent-a", ["tool_new"])!;

    applyReminderConsumption({ sessionEntry: entry, receipt: newerOutage.receipt });
    applyReminderConsumption({ sessionEntry: entry, receipt: staleOutage.receipt });

    expect(entry.reminderAcceptedUnavailableToolNames).toEqual(["tool_new"]);
    expect(entry.reminderUnavailableRevision).toBe(1);
  });
});
