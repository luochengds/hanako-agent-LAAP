/**
 * Renders internal reminder blocks for changes hidden by a session's frozen
 * prompt/tool snapshot. The block remains in model JSONL; server-owned display
 * projections remove it, with the desktop parser retained as defense in depth.
 *
 * The renderer is pure with respect to session state. It returns an immutable
 * receipt, and callers apply that receipt only after the prompt/steer operation
 * has accepted the rendered message.
 */

import type {
  EnvChangeEntry,
  EnvChangeLedger,
  MemoryFactsPayload,
} from "./env-change-ledger.ts";

export const REMINDER_BLOCK_PREFIX = "[hana_reminder";
export const REMINDER_BLOCK_END = "[/hana_reminder]";
export const TIME_STALENESS_MS = 3 * 60 * 60 * 1000;

const REMINDER_HEADER_LINE_RE = /^\[hana_reminder at \d{4}-\d{2}-\d{2} \d{2}:\d{2}\]$/;

const BLOCK_BODY_CHAR_LIMIT = 300;

/**
 * Removes model-only reminder blocks from user-visible session text.
 *
 * Historical JSONL stores reminder input inside the user message because the
 * model must observe it. Display/export consumers must use this projection
 * rather than exposing that internal input. An exact header without a closing
 * line is removed through end-of-text so a truncated JSONL entry fails closed.
 */
export function stripSessionReminderBlocks(value: unknown): string {
  if (typeof value !== "string" || !value) return typeof value === "string" ? value : "";

  const visibleLines: string[] = [];
  let insideReminder = false;
  let dropSeparatorAfterReminder = false;

  for (const line of value.split(/\r?\n/)) {
    if (insideReminder) {
      if (line === REMINDER_BLOCK_END) {
        insideReminder = false;
        dropSeparatorAfterReminder = true;
      }
      continue;
    }
    if (REMINDER_HEADER_LINE_RE.test(line)) {
      insideReminder = true;
      continue;
    }
    if (dropSeparatorAfterReminder && line === "") continue;
    dropSeparatorAfterReminder = false;
    visibleLines.push(line);
  }

  while (visibleLines.at(-1) === "") visibleLines.pop();
  return visibleLines.join("\n");
}

/** Projects a persisted message for display without mutating the JSONL truth. */
export function projectSessionMessageForDisplay(message: any): any {
  if (!message || message.role !== "user") return message;
  if (typeof message.content === "string") {
    const content = stripSessionReminderBlocks(message.content);
    return content === message.content ? message : { ...message, content };
  }
  if (!Array.isArray(message.content)) return message;

  let changed = false;
  const content = message.content.map((block: any) => {
    if (block?.type !== "text" || typeof block.text !== "string") return block;
    const text = stripSessionReminderBlocks(block.text);
    if (text === block.text) return block;
    changed = true;
    return { ...block, text };
  });
  return changed ? { ...message, content } : message;
}

export interface ReminderSessionEntry {
  reminderEnvCursor: number;
  reminderEnvStartSeq: number;
  lastTimeObservedAt: number | null;
  reminderCompactionRevision: number;
  reminderConsumedCompactionRevision: number;
  reminderAcceptedUnavailableToolNames: string[];
  reminderUnavailableRevision: number;
}

export interface SessionReminderReceipt {
  readonly observedAt: number;
  readonly throughSeq: number;
  readonly compactionRevision: number;
  readonly unavailableToolNames: readonly string[];
  readonly baseUnavailableRevision: number;
  readonly consumeBlockState: boolean;
}

export interface RenderedSessionReminderBlock {
  readonly block: string;
  readonly receipt: SessionReminderReceipt;
}

function nonNegativeInteger(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) && value > 0
    ? Math.floor(value)
    : 0;
}

function memoryFactsEntries(entries: EnvChangeEntry[]): EnvChangeEntry[] {
  return entries.filter((entry) => entry.type === "memory_facts");
}

function entriesVisibleToAgent(entries: EnvChangeEntry[], recipientAgentId: string): EnvChangeEntry[] {
  return entries.filter((entry) => entry.scope.agentId === recipientAgentId);
}

function formatMemoryFactsLine(payload: Readonly<MemoryFactsPayload>, isZh: boolean): string {
  const lines = payload.addedLines.join(isZh ? "；" : "; ");
  return isZh ? `记忆新增事实：${lines}` : `New memory facts recorded: ${lines}`;
}

function formatCompactionLine(isZh: boolean): string {
  return isZh
    ? "上下文已压缩，早期对话已被总结"
    : "Context has been compacted; earlier turns were summarized";
}

function formatTimeLine(now: number, timeZone: string | undefined, isZh: boolean): string {
  const stamp = formatTimestamp(now, timeZone);
  return isZh ? `当前时间：${stamp}` : `Current time: ${stamp}`;
}

function normalizeUnavailableToolNames(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return [...new Set(value
    .filter((name): name is string => typeof name === "string")
    .map((name) => name.trim())
    .filter(Boolean))]
    .sort((left, right) => left.localeCompare(right));
}

function sameNames(left: readonly string[], right: readonly string[]): boolean {
  return left.length === right.length && left.every((name, index) => name === right[index]);
}

function formatUnavailableToolsLine(names: readonly string[], isZh: boolean): string {
  return isZh
    ? `以下会话工具当前不可用：${names.join("、")}`
    : `These session tools are currently unavailable: ${names.join(", ")}`;
}

function selectUnavailableToolBatch(names: readonly string[], isZh: boolean): string[] {
  const batch: string[] = [];
  for (const name of names) {
    const candidate = [...batch, name];
    const line = `- ${formatUnavailableToolsLine(candidate, isZh)}`;
    if (line.length > BLOCK_BODY_CHAR_LIMIT) break;
    batch.push(name);
  }
  return batch;
}

function formatTimestamp(now: number, timeZone: string | undefined): string {
  const parts = new Intl.DateTimeFormat("en-CA", {
    ...(timeZone ? { timeZone } : {}),
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(new Date(now));
  const values: Record<string, string> = {};
  for (const part of parts) values[part.type] = part.value;
  return `${values.year}-${values.month}-${values.day} ${values.hour}:${values.minute}`;
}

export function collectReminderBlock({
  sessionEntry,
  ledger,
  recipientAgentId,
  now,
  isZh,
  timeZone,
  unavailableToolNames = [],
}: {
  sessionEntry: ReminderSessionEntry;
  ledger: EnvChangeLedger;
  recipientAgentId: string;
  now: number;
  isZh: boolean;
  timeZone?: string;
  unavailableToolNames?: string[];
}): RenderedSessionReminderBlock | null {
  const normalizedRecipientAgentId = typeof recipientAgentId === "string" ? recipientAgentId.trim() : "";
  if (!normalizedRecipientAgentId) {
    throw new TypeError("collectReminderBlock requires a non-empty recipientAgentId");
  }
  const throughSeq = ledger.maxSeq();
  const compactionRevision = nonNegativeInteger(sessionEntry.reminderCompactionRevision);
  const consumedCompactionRevision = nonNegativeInteger(sessionEntry.reminderConsumedCompactionRevision);
  const hasPendingCompaction = compactionRevision > consumedCompactionRevision;
  const envCursor = hasPendingCompaction
    ? nonNegativeInteger(sessionEntry.reminderEnvStartSeq)
    : nonNegativeInteger(sessionEntry.reminderEnvCursor);
  const entries = entriesVisibleToAgent(
    ledger.entriesAfter(envCursor, throughSeq),
    normalizedRecipientAgentId,
  );
  const lines: string[] = [];
  const acceptedUnavailableToolNames = normalizeUnavailableToolNames(
    sessionEntry.reminderAcceptedUnavailableToolNames,
  );
  const unavailableRevision = nonNegativeInteger(sessionEntry.reminderUnavailableRevision);
  const currentUnavailableToolNames = normalizeUnavailableToolNames(unavailableToolNames);
  const acceptedUnavailableSet = new Set(acceptedUnavailableToolNames);
  const currentUnavailableSet = new Set(currentUnavailableToolNames);
  const newUnavailableToolNames = currentUnavailableToolNames.filter(
    (name) => !acceptedUnavailableSet.has(name),
  );
  const stillAcceptedUnavailableToolNames = acceptedUnavailableToolNames.filter(
    (name) => currentUnavailableSet.has(name),
  );
  const renderedUnavailableToolNames = selectUnavailableToolBatch(newUnavailableToolNames, isZh);
  const nextAcceptedUnavailableToolNames = normalizeUnavailableToolNames([
    ...stillAcceptedUnavailableToolNames,
    ...renderedUnavailableToolNames,
  ]);
  const hasNewOutage = renderedUnavailableToolNames.length > 0;
  const availabilityTransition = !sameNames(
    acceptedUnavailableToolNames,
    nextAcceptedUnavailableToolNames,
  );

  if (hasNewOutage) {
    lines.push(`- ${formatUnavailableToolsLine(renderedUnavailableToolNames, isZh)}`);
  }
  if (hasPendingCompaction) lines.push(`- ${formatCompactionLine(isZh)}`);
  for (const entry of memoryFactsEntries(entries)) {
    lines.push(`- ${formatMemoryFactsLine(entry.payload as Readonly<MemoryFactsPayload>, isZh)}`);
  }

  const lastTimeObservedAt = sessionEntry.lastTimeObservedAt;
  const isTimeStale = lastTimeObservedAt == null || (now - lastTimeObservedAt) > TIME_STALENESS_MS;
  if (isTimeStale) lines.push(`- ${formatTimeLine(now, timeZone, isZh)}`);
  if (lines.length === 0 && !availabilityTransition) return null;

  let body = lines.join("\n");
  if (body.length > BLOCK_BODY_CHAR_LIMIT) {
    if (hasNewOutage) {
      const outageLine = lines[0];
      const remainingBody = lines.slice(1).join("\n");
      const remainingLimit = BLOCK_BODY_CHAR_LIMIT - outageLine.length - 1;
      body = remainingLimit > 1 && remainingBody
        ? `${outageLine}\n${remainingBody.slice(0, remainingLimit - 1)}…`
        : outageLine;
    } else {
      body = `${body.slice(0, BLOCK_BODY_CHAR_LIMIT - 1)}…`;
    }
  }

  const receipt = Object.freeze({
    observedAt: now,
    throughSeq,
    compactionRevision,
    unavailableToolNames: Object.freeze([...nextAcceptedUnavailableToolNames]),
    baseUnavailableRevision: unavailableRevision,
    consumeBlockState: lines.length > 0,
  });
  return Object.freeze({
    block: lines.length > 0
      ? `${REMINDER_BLOCK_PREFIX} at ${formatTimestamp(now, timeZone)}]\n${body}\n${REMINDER_BLOCK_END}`
      : "",
    receipt,
  });
}

/** Applies only the state range represented by a previously rendered receipt. */
export function applyReminderConsumption({
  sessionEntry,
  receipt,
}: {
  sessionEntry: ReminderSessionEntry;
  receipt: SessionReminderReceipt;
}): void {
  if (
    !receipt
    || !Number.isFinite(receipt.observedAt)
    || !Number.isFinite(receipt.throughSeq)
    || !Number.isFinite(receipt.compactionRevision)
    || !Array.isArray(receipt.unavailableToolNames)
    || !Number.isFinite(receipt.baseUnavailableRevision)
    || typeof receipt.consumeBlockState !== "boolean"
  ) {
    throw new TypeError("applyReminderConsumption requires a valid reminder receipt");
  }

  if (receipt.consumeBlockState) {
    sessionEntry.reminderEnvCursor = Math.max(
      nonNegativeInteger(sessionEntry.reminderEnvCursor),
      nonNegativeInteger(receipt.throughSeq),
    );
    const currentRevision = nonNegativeInteger(sessionEntry.reminderCompactionRevision);
    sessionEntry.reminderConsumedCompactionRevision = Math.max(
      nonNegativeInteger(sessionEntry.reminderConsumedCompactionRevision),
      Math.min(nonNegativeInteger(receipt.compactionRevision), currentRevision),
    );
    noteTimeObservedForSession(sessionEntry, receipt.observedAt);
  }

  const currentUnavailableRevision = nonNegativeInteger(
    sessionEntry.reminderUnavailableRevision,
  );
  if (currentUnavailableRevision === nonNegativeInteger(receipt.baseUnavailableRevision)) {
    const accepted = normalizeUnavailableToolNames(
      sessionEntry.reminderAcceptedUnavailableToolNames,
    );
    const next = normalizeUnavailableToolNames(receipt.unavailableToolNames);
    if (!sameNames(accepted, next)) {
      sessionEntry.reminderAcceptedUnavailableToolNames = next;
      sessionEntry.reminderUnavailableRevision = currentUnavailableRevision + 1;
    }
  }
}

/** Pure session-state helper used by reminder consumption and current_status(time). */
export function noteTimeObservedForSession(sessionEntry: ReminderSessionEntry, observedAt: number): void {
  if (!Number.isFinite(observedAt)) {
    throw new TypeError("noteTimeObservedForSession requires a finite observedAt");
  }
  const current = sessionEntry.lastTimeObservedAt;
  sessionEntry.lastTimeObservedAt = current == null ? observedAt : Math.max(current, observedAt);
}
