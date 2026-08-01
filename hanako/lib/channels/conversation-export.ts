import { promises as fsp } from "fs";
import fs from "fs";
import path from "path";
import { execSync } from "child_process";
import { parseChannel } from "./channel-store.ts";

export type ConversationExportFormat = "md" | "html" | "docx";

export type ConversationExportFilters = {
  /** ISO date string or YYYY-MM-DD, only include messages on or after this date */
  fromDate?: string;
  /** ISO date string or YYYY-MM-DD, only include messages on or before this date */
  toDate?: string;
  /** Only include messages from these speakers (case-insensitive) */
  speakers?: string[];
};

export type ConversationExportOptions = {
  filePath: string;
  type: "channel" | "dm";
  conversationId: string;
  displayName?: string;
  ownerAgentId?: string;
  peerAgentId?: string;
  now?: Date;
  filters?: ConversationExportFilters;
};

export type ConversationExportResult = {
  markdown: string | Uint8Array;
  filename: string;
  mediaType: string;
  encoding: string;
  messageCount: number;
};

function filterMessages(messages: Array<{ speaker: string; timestamp: string; body: string }>, filters?: ConversationExportFilters) {
  if (!filters) return messages;
  return messages.filter((msg) => {
    // Date range filter
    if (filters.fromDate) {
      const msgDate = msg.timestamp.slice(0, 10);
      if (msgDate < filters.fromDate.slice(0, 10)) return false;
    }
    if (filters.toDate) {
      const msgDate = msg.timestamp.slice(0, 10);
      if (msgDate > filters.toDate.slice(0, 10)) return false;
    }
    // Speaker filter
    if (filters.speakers && filters.speakers.length > 0) {
      if (!filters.speakers.some((s) => msg.speaker.toLowerCase() === s.toLowerCase())) {
        return false;
      }
    }
    return true;
  });
}

function ensureTrailingNewline(content: string) {
  return content.endsWith("\n") ? content : `${content}\n`;
}

function inlineCode(value: string) {
  const normalized = value.replace(/[\r\n]+/g, " ");
  const longestRun = Math.max(0, ...Array.from(normalized.matchAll(/`+/g), match => match[0].length));
  const fence = "`".repeat(longestRun + 1);
  return `${fence}${normalized}${fence}`;
}

function safeFilenamePart(value: string) {
  const part = value
    .normalize("NFKD")
    .replace(/[^\p{L}\p{N}._-]+/gu, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 64);
  return part || "conversation";
}

function archiveFilename(options: ConversationExportOptions, generatedAt: Date) {
  if (Number.isNaN(generatedAt.getTime())) throw new TypeError("now must be a valid Date");
  const stamp = generatedAt.toISOString().replace(/[:.]/g, "-");
  const identity = options.type === "dm"
    ? `${safeFilenamePart(options.ownerAgentId || "agent")}-${safeFilenamePart(options.peerAgentId || options.conversationId)}`
    : safeFilenamePart(options.displayName || options.conversationId);
  return `hana-${options.type}-${identity}-${stamp}.md`;
}

export async function buildConversationMarkdownExport(options: ConversationExportOptions): Promise<ConversationExportResult> {
  if (!options.filePath || !options.conversationId) {
    throw new TypeError("filePath and conversationId are required");
  }
  const now = options.now || new Date();
  const stat = await fsp.stat(options.filePath);
  if (!stat.isFile()) throw new Error("conversation record is not a file");
  const content = await fsp.readFile(options.filePath, "utf-8");
  const parsed = parseChannel(content);
  const displayName = options.displayName || String(parsed.meta.name || options.conversationId);
  const lines = [
    `# ${options.type === "dm" ? "Direct Message" : "Group Chat"}: ${displayName}`,
    "",
    `Exported at: ${now.toISOString()}`,
    `Conversation ID: ${inlineCode(options.conversationId)}`,
  ];

  if (options.type === "dm") {
    lines.push(`Participants: ${inlineCode(options.ownerAgentId || "unknown")} ↔ ${inlineCode(options.peerAgentId || "unknown")}`);
  }

  lines.push("", "## Conversation record", "", ensureTrailingNewline(content));
  return {
    markdown: ensureTrailingNewline(lines.join("\n")),
    filename: archiveFilename(options, now),
    mediaType: "text/markdown; charset=utf-8",
    encoding: "utf-8",
    messageCount: parsed.messages.length,
  };
}

const SPEAKER_COLORS: Record<string, string> = {
  aris: "#7c5cfc",
  "hanako-2": "#f59e0b",
  hanako: "#f59e0b",
  butter: "#ec4899",
  lorry: "#10b981",
};

function speakerColor(name: string): string {
  if (SPEAKER_COLORS[name.toLowerCase()]) return SPEAKER_COLORS[name.toLowerCase()];
  // Generate a consistent color from the name
  let hash = 0;
  for (let i = 0; i < name.length; i++) hash = name.charCodeAt(i) + ((hash << 5) - hash);
  const hue = Math.abs(hash) % 360;
  return `hsl(${hue}, 65%, 50%)`;
}

function formatTime(ts: string): string {
  try {
    const d = new Date(ts);
    return d.toLocaleString("zh-CN", {
      year: "numeric", month: "2-digit", day: "2-digit",
      hour: "2-digit", minute: "2-digit",
    });
  } catch {
    return ts;
  }
}

function formatDateGroup(ts: string): string {
  try {
    const d = new Date(ts);
    return d.toLocaleDateString("zh-CN", {
      year: "numeric", month: "long", day: "numeric", weekday: "long",
    });
  } catch {
    return ts;
  }
}

function escHtml(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

export async function buildConversationHtmlExport(options: ConversationExportOptions): Promise<ConversationExportResult> {
  if (!options.filePath || !options.conversationId) {
    throw new TypeError("filePath and conversationId are required");
  }
  const now = options.now || new Date();
  const stat = await fsp.stat(options.filePath);
  if (!stat.isFile()) throw new Error("conversation record is not a file");
  const content = await fsp.readFile(options.filePath, "utf-8");
  const parsed = parseChannel(content);

  const displayName = options.displayName || options.conversationId;
  const channelTitle = options.type === "dm" ? "Direct Message" : "Group Chat";

  // Apply date/speaker filters
  const filteredMessages = filterMessages(parsed.messages, options.filters);

  // Group parsed messages by date
  const groups: { date: string; messages: typeof parsed.messages }[] = [];
  for (const msg of filteredMessages) {
    // timestamp format: YYYY-MM-DD HH:MM or YYYY-MM-DD HH:MM:SS
    const dateKey = msg.timestamp.slice(0, 10);
    const last = groups[groups.length - 1];
    if (last && last.date === dateKey) {
      last.messages.push(msg);
    } else {
      groups.push({ date: dateKey, messages: [msg] });
    }
  }

  const htmlLines: string[] = [];
  htmlLines.push(`<!DOCTYPE html>`);
  htmlLines.push(`<html lang="zh-CN">`);
  htmlLines.push(`<head>`);
  htmlLines.push(`<meta charset="utf-8">`);
  htmlLines.push(`<meta name="viewport" content="width=device-width, initial-scale=1.0">`);
  htmlLines.push(`<title>${escHtml(displayName)} — ${channelTitle} 导出</title>`);
  htmlLines.push(`<style>`);
  htmlLines.push(`
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans SC", "PingFang SC", sans-serif;
  background: #f5f0e8;
  color: #2c2c2c;
  line-height: 1.7;
  padding: 0;
}
.header {
  background: linear-gradient(135deg, #faf6ef 0%, #f0e8d8 100%);
  border-bottom: 1px solid #ddd6c8;
  padding: 32px 40px;
  text-align: center;
}
.header h1 {
  font-size: 22px;
  font-weight: 600;
  color: #3a3a3a;
  margin-bottom: 6px;
}
.header .meta {
  font-size: 13px;
  color: #888;
}
.header .meta span {
  margin: 0 8px;
}
.date-group {
  margin: 0 auto;
  max-width: 720px;
  padding: 20px 0;
}
.date-separator {
  text-align: center;
  margin: 24px 0;
  position: relative;
}
.date-separator::before {
  content: '';
  position: absolute;
  left: 0; right: 0; top: 50%;
  height: 1px;
  background: #ddd6c8;
}
.date-separator span {
  display: inline-block;
  background: #f5f0e8;
  padding: 0 16px;
  position: relative;
  z-index: 1;
  font-size: 13px;
  color: #999;
}
.message {
  display: flex;
  gap: 12px;
  padding: 8px 24px;
  transition: background 0.15s;
}
.message:hover {
  background: rgba(0,0,0,0.02);
}
.avatar {
  flex-shrink: 0;
  width: 36px;
  height: 36px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  font-weight: 600;
  color: #fff;
  margin-top: 2px;
}
.body {
  flex: 1;
  min-width: 0;
}
.body .speaker {
  font-size: 14px;
  font-weight: 600;
  margin-bottom: 2px;
}
.body .time {
  font-size: 11px;
  color: #bbb;
  margin-left: 8px;
  font-weight: 400;
}
.body .text {
  font-size: 15px;
  white-space: pre-wrap;
  word-break: break-word;
}
.body .text p { margin-bottom: 6px; }
.body .text code {
  background: #f0ebe3;
  padding: 1px 5px;
  border-radius: 3px;
  font-size: 13px;
  font-family: "JetBrains Mono", "SF Mono", "Fira Code", monospace;
}
.footer {
  text-align: center;
  padding: 32px;
  font-size: 12px;
  color: #ccc;
  border-top: 1px solid #ddd6c8;
  margin-top: 8px;
}
`);
  htmlLines.push(`</style>`);
  htmlLines.push(`</head>`);
  htmlLines.push(`<body>`);

  // Header
  htmlLines.push(`<div class="header">`);
  htmlLines.push(`<h1>${escHtml(displayName)}</h1>`);
  htmlLines.push(`<div class="meta">`);
  htmlLines.push(`<span>${escHtml(channelTitle)}</span>`);
  htmlLines.push(`<span>·</span>`);
  htmlLines.push(`<span>${filteredMessages.length} 条消息</span>`);
  htmlLines.push(`<span>·</span>`);
  htmlLines.push(`<span>导出于 ${formatTime(now.toISOString())}</span>`);
  htmlLines.push(`</div></div>`);

  // Messages grouped by date
  for (const group of groups) {
    htmlLines.push(`<div class="date-group">`);
    htmlLines.push(`<div class="date-separator"><span>${escHtml(formatDateGroup(group.messages[0].timestamp))}</span></div>`);
    for (const msg of group.messages) {
      const color = speakerColor(msg.speaker);
      const initial = msg.speaker.charAt(0).toUpperCase();
      htmlLines.push(`<div class="message">`);
      htmlLines.push(`<div class="avatar" style="background:${color}">${escHtml(initial)}</div>`);
      htmlLines.push(`<div class="body">`);
      htmlLines.push(`<div class="speaker" style="color:${color}">${escHtml(msg.speaker)}<span class="time">${escHtml(formatTime(msg.timestamp))}</span></div>`);
      htmlLines.push(`<div class="text">${escHtml(msg.body)}</div>`);
      htmlLines.push(`</div></div>`);
    }
    htmlLines.push(`</div>`);
  }

  // Footer
  htmlLines.push(`<div class="footer">由 Hana 频道导出 · ${now.toISOString().slice(0, 10)}</div>`);

  htmlLines.push(`</body></html>`);

  const htmlOutput = htmlLines.join("\n");
  const baseName = archiveFilename(options, now).replace(/\.md$/, "");

  return {
    markdown: htmlOutput,
    filename: `${baseName}.html`,
    mediaType: "text/html; charset=utf-8",
    encoding: "utf-8",
    messageCount: filteredMessages.length,
  };
}

export async function buildConversationDocxExport(options: ConversationExportOptions): Promise<ConversationExportResult> {
  if (!options.filePath || !options.conversationId) {
    throw new TypeError("filePath and conversationId are required");
  }
  const now = options.now || new Date();
  const stat = await fsp.stat(options.filePath);
  if (!stat.isFile()) throw new Error("conversation record is not a file");
  const content = await fsp.readFile(options.filePath, "utf-8");
  const parsed = parseChannel(content);

  const displayName = options.displayName || options.conversationId;

  // Apply date/speaker filters
  const filteredMessages = filterMessages(parsed.messages, options.filters);

  // Save parsed messages as JSON temp file
  const pythonScript = path.resolve(import.meta.dirname!, "../../scripts/channel-to-docx.py");
  const tempDir = path.resolve(import.meta.dirname!, "../../scripts");
  const tempJson = path.join(tempDir, `__docx_export_${Date.now()}.json`);
  const tempDocx = path.join(tempDir, `__docx_export_${Date.now()}.docx`);

  try {
    const payload = JSON.stringify({
      displayName,
      channelType: options.type,
      now: now.toISOString(),
      messages: filteredMessages.map((m: { speaker: string; timestamp: string; body: string }) => ({
        speaker: m.speaker,
        timestamp: m.timestamp,
        body: m.body,
      })),
    });

    fs.writeFileSync(tempJson, payload, "utf-8");

    const cmd = `python "${pythonScript}" "${tempJson}" -o "${tempDocx}"`;
    execSync(cmd, { timeout: 30000, stdio: "pipe" });

    if (!fs.existsSync(tempDocx)) {
      throw new Error("DOCX export failed: output file not created");
    }

    const buffer = fs.readFileSync(tempDocx);
    const baseName = archiveFilename(options, now).replace(/\\.md$/, "");

    return {
      markdown: new Uint8Array(buffer),
      filename: `${baseName}.docx`,
      mediaType: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      encoding: "binary",
      messageCount: filteredMessages.length,
    };
  } finally {
    // Cleanup temp files
    try { if (fs.existsSync(tempJson)) fs.unlinkSync(tempJson); } catch {}
    try { if (fs.existsSync(tempDocx)) fs.unlinkSync(tempDocx); } catch {}
  }
}
