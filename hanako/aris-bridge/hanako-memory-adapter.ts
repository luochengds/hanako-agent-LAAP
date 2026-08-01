/**
 * hanako-memory-adapter.ts — Aris 与 Hanako 记忆管线之间的桥接适配器
 *
 * 该模块提供：
 *   1. HanakoMemoryAdapter：读写 Hanako 的 memory/ 与 diary/ 目录
 *   2. FactRow 接口：FTS5 查询返回的事实行
 *   3. MEMORY_TOOLS：供 aris-plugin 注册的工具描述符
 *
 * 路径约定（与 lib/memory/compile.ts 对齐）：
 *   - today.md / week.md / longterm.md / facts.md / memory.md → memory/
 *   - daily/{YYYY-MM-DD}.md → memory/daily/
 *   - facts.db → memory/（与 core/agent.ts 命名一致）
 *
 * 日界线：凌晨 4:00（DAY_BOUNDARY_HOUR）前算前一天，由 getLogicalDay 统一处理。
 */

import fs from 'fs';
import path from 'path';
import { createRequire } from 'module';
import { getLogicalDay, DAY_BOUNDARY_HOUR } from '../lib/time-utils.ts';
import { safeReadFile, atomicWriteSync } from '../shared/safe-fs.ts';
import { createModuleLogger } from '../lib/debug-log.ts';

const log = createModuleLogger('aris-memory-adapter');

const require = createRequire(import.meta.url);
let BetterSqliteDatabase: any = null;

/**
 * 懒加载 better-sqlite3（与 lib/memory/fact-store.ts 保持一致的写法）。
 * 避免在不需要查询事实时强制加载原生模块。
 */
function loadBetterSqliteDatabase(): any {
  if (!BetterSqliteDatabase) {
    const mod = require('better-sqlite3');
    BetterSqliteDatabase = mod?.default || mod;
  }
  return BetterSqliteDatabase;
}

/** FTS5 查询返回的事实行 */
export interface FactRow {
  /** 事实文本 */
  fact: string;
  /** 标签数组（解析自 SQLite 中的 JSON 字符串） */
  tags: string[];
  /** 创建时间（ISO 字符串） */
  created_at: string;
}

/** 记忆范围字面量类型 */
export type MemoryScope = 'today' | 'daily' | 'week' | 'longterm' | 'facts' | 'memory';

/** appendDiary 入参 */
export interface DiaryEvent {
  /** 毫秒级时间戳 */
  timestamp: number;
  /** 事件类型（如 emotion_peak / psi_spike / rsi_event） */
  type: string;
  /** 事件内容描述 */
  content: string;
}

/**
 * Hanako 记忆适配器
 *
 * 每个 Aris agent 实例持有一个适配器，所有读写都落在该 agent 的
 * agentDir/memory 与 agentDir/diary 下。
 */
export class HanakoMemoryAdapter {
  /** agent 目录绝对路径（如 d:\LAAP\hanako\agents\aris） */
  private readonly agentDir: string;
  /** memory 目录绝对路径 */
  private readonly memoryDir: string;
  /** diary 目录绝对路径 */
  private readonly diaryDir: string;
  /** facts.db 绝对路径（与 core/agent.ts 命名一致） */
  private readonly factsDbPath: string;

  /**
   * @param agentDir - agent 目录绝对路径（如 d:\LAAP\hanako\agents\aris）
   */
  constructor(agentDir: string) {
    this.agentDir = agentDir;
    this.memoryDir = path.join(agentDir, 'memory');
    this.diaryDir = path.join(agentDir, 'diary');
    this.factsDbPath = path.join(this.memoryDir, 'facts.db');
    // DAY_BOUNDARY_HOUR 在此显式引用，确保 4:00 日界线约定随 adapter 一起暴露
    log.log(`init agentDir=${agentDir} (dayBoundary=${DAY_BOUNDARY_HOUR}:00)`);
  }

  /** 返回 memory 目录绝对路径 */
  getMemoryDir(): string {
    return this.memoryDir;
  }

  /** 返回 diary 目录绝对路径 */
  getDiaryDir(): string {
    return this.diaryDir;
  }

  /**
   * 读取指定范围的记忆 md 文件
   * @param scope 记忆范围
   * @param options.date 当 scope='daily' 时必填，格式 YYYY-MM-DD
   * @returns 文件内容；文件不存在时返回空字符串
   */
  readMemory(scope: MemoryScope, options: { date?: string } = {}): string {
    let filePath: string;
    switch (scope) {
      case 'today':
        filePath = path.join(this.memoryDir, 'today.md');
        break;
      case 'daily': {
        const date = options.date;
        if (!date || !/^\d{4}-\d{2}-\d{2}$/.test(date)) {
          log.warn(`readMemory(daily) 缺少合法 date 参数: ${String(date)}`);
          return '';
        }
        filePath = path.join(this.memoryDir, 'daily', `${date}.md`);
        break;
      }
      case 'week':
        filePath = path.join(this.memoryDir, 'week.md');
        break;
      case 'longterm':
        filePath = path.join(this.memoryDir, 'longterm.md');
        break;
      case 'facts':
        filePath = path.join(this.memoryDir, 'facts.md');
        break;
      case 'memory':
        filePath = path.join(this.memoryDir, 'memory.md');
        break;
      default: {
        const exhaustive: never = scope;
        log.warn(`readMemory 收到未知 scope: ${String(exhaustive)}`);
        return '';
      }
    }
    return safeReadFile(filePath, '');
  }

  /**
   * 用 FTS5 全文搜索查询事实库
   * @param query 搜索查询（中文/英文均可）
   * @param limit 最大返回行数，默认 10
   * @returns 匹配的事实行；DB 不存在或查询失败时返回空数组
   */
  queryFacts(query: string, limit: number = 10): FactRow[] {
    if (!query || !String(query).trim()) return [];
    if (!fs.existsSync(this.factsDbPath)) {
      log.warn(`queryFacts: 数据库不存在: ${this.factsDbPath}`);
      return [];
    }

    let Database: any;
    try {
      Database = loadBetterSqliteDatabase();
    } catch (err) {
      log.error(`queryFacts: 加载 better-sqlite3 失败: ${(err as Error).message}`);
      return [];
    }
    if (!Database) {
      log.error('queryFacts: better-sqlite3 模块不可用');
      return [];
    }

    let db: any;
    try {
      db = new Database(this.factsDbPath, { readonly: true });
    } catch (err) {
      log.error(`queryFacts: 打开数据库失败: ${(err as Error).message}`);
      return [];
    }

    try {
      const stmt = db.prepare(
        `SELECT fact, tags, created_at
         FROM facts
         JOIN facts_fts ON facts.rowid = facts_fts.rowid
         WHERE facts_fts MATCH ?
         LIMIT ?`,
      );
      const safeLimit = Math.max(1, Math.floor(Number(limit) || 10));
      const rows = stmt.all(String(query), safeLimit);
      return rows.map((row: any): FactRow => ({
        fact: String(row?.fact ?? ''),
        tags: parseTags(row?.tags),
        created_at: String(row?.created_at ?? ''),
      }));
    } catch (err) {
      log.error(`queryFacts: 查询失败: ${(err as Error).message}`);
      return [];
    } finally {
      try {
        if (db?.open) db.close();
      } catch {
        /* best effort */
      }
    }
  }

  /**
   * 向日记本追加一条事件（按 timestamp 计算的逻辑日归类）
   * @param event 事件对象
   */
  appendDiary(event: DiaryEvent): void {
    const { timestamp, type, content } = event;
    const date = new Date(timestamp);
    const { logicalDate } = getLogicalDay(date);
    const isoTs = date.toISOString();
    const line = `- [${isoTs}] **${type}**: ${content}\n`;
    const filePath = path.join(this.diaryDir, `${logicalDate}.md`);

    try {
      fs.mkdirSync(this.diaryDir, { recursive: true });
      const existing = safeReadFile(filePath, '');
      const joiner = existing && !existing.endsWith('\n') ? '\n' : '';
      atomicWriteSync(filePath, existing + joiner + line);
      log.log(`appendDiary: 已写入 ${logicalDate}.md (${type})`);
    } catch (err) {
      log.error(`appendDiary: 写入失败: ${(err as Error).message}`);
      throw err;
    }
  }

  /**
   * 向 memory/facts.md 追加一条自动事实（位于 `## Aris 自动事实` 段下）
   * @param text 事实文本
   * @param tags 可选标签数组
   */
  appendFact(text: string, tags?: string[]): void {
    const filePath = path.join(this.memoryDir, 'facts.md');
    const isoTs = new Date().toISOString();
    const tagSuffix = tags && tags.length > 0 ? ` [${tags.join(', ')}]` : '';
    const line = `- [${isoTs}] ${text}${tagSuffix}`;

    const SECTION_HEADING = '## Aris 自动事实';
    try {
      fs.mkdirSync(this.memoryDir, { recursive: true });
      const existing = safeReadFile(filePath, '');

      let next: string;
      if (existing.includes(SECTION_HEADING)) {
        // 段已存在：在段末尾追加
        next = appendToSection(existing, SECTION_HEADING, line);
      } else {
        // 段不存在：在文件末尾新建段
        const prefix = existing && !existing.endsWith('\n') ? '\n\n' : (existing ? '\n\n' : '');
        next = `${existing}${prefix}${SECTION_HEADING}\n\n${line}\n`;
      }
      atomicWriteSync(filePath, next);
      log.log(`appendFact: 已写入 ${filePath}`);
    } catch (err) {
      log.error(`appendFact: 写入失败: ${(err as Error).message}`);
      throw err;
    }
  }
}

/**
 * 在指定二级标题段的末尾追加一行，保持后续兄弟段不被破坏。
 *
 * 仅处理 `## ` 开头的段标题；遇下一个 `## ` 或文件末尾即视为段结束。
 */
function appendToSection(content: string, heading: string, line: string): string {
  const lines = content.split('\n');
  const headingIdx = lines.findIndex((l) => l.trim() === heading);
  if (headingIdx === -1) {
    // 兜底：理论上不应进入此分支（调用方已确保段存在）
    return `${content}\n${heading}\n\n${line}\n`;
  }

  // 找下一个同级或更高级标题（## 或 #）
  let insertIdx = lines.length;
  for (let i = headingIdx + 1; i < lines.length; i++) {
    if (/^#{1,2}\s/.test(lines[i])) {
      insertIdx = i;
      break;
    }
  }

  // 回退到段末尾第一个非空行
  while (insertIdx > headingIdx + 1 && lines[insertIdx - 1].trim() === '') {
    insertIdx--;
  }

  // 确保新行前有空行分隔（若前一行非空）
  const needLeadingBlank = insertIdx > headingIdx + 1 && lines[insertIdx - 1].trim() !== '';
  const newLines = [
    ...lines.slice(0, insertIdx),
    ...(needLeadingBlank ? [''] : []),
    line,
    ...lines.slice(insertIdx),
  ];
  return newLines.join('\n');
}

/** 解析 facts.db 中的 tags 字段（JSON 字符串或已是数组） */
function parseTags(raw: unknown): string[] {
  if (Array.isArray(raw)) {
    return raw.filter((t): t is string => typeof t === 'string');
  }
  if (typeof raw === 'string') {
    try {
      const parsed = JSON.parse(raw);
      return Array.isArray(parsed)
        ? parsed.filter((t): t is string => typeof t === 'string')
        : [];
    } catch {
      return [];
    }
  }
  return [];
}

// ── 工具描述符 ──────────────────────────────────────────

/** 工具处理器的上下文：注入 adapter 实例 */
export interface MemoryToolContext {
  adapter: HanakoMemoryAdapter;
}

/** 工具描述符形状（与 hanako plugin SDK 兼容） */
export interface MemoryToolDescriptor {
  name: string;
  description: string;
  parameters: Record<string, unknown>;
  handler: (
    args: any,
    ctx: MemoryToolContext,
  ) => Promise<{ content: Array<{ type: string; text: string }> }>;
}

/**
 * Aris 记忆工具集
 *
 * 注册到 aris-plugin 后，Aris 即可通过 LLM 工具调用读取自己的跨会话记忆、
 * 追加情感/PSI/RSI 关键事件。
 */
export const MEMORY_TOOLS: MemoryToolDescriptor[] = [
  {
    name: 'aris_memory_query',
    description:
      '查询 Aris 的跨会话记忆。可指定 scope (today/daily/week/longterm/facts/memory) 或用 FTS5 全文搜索查询事实库。',
    parameters: {
      type: 'object',
      properties: {
        scope: {
          type: 'string',
          enum: ['today', 'daily', 'week', 'longterm', 'facts', 'memory'],
          description: '记忆范围',
        },
        date: {
          type: 'string',
          description: '当 scope=daily 时指定日期 YYYY-MM-DD',
        },
        query: {
          type: 'string',
          description: '当提供时使用 FTS5 全文搜索查询事实库（覆盖 scope）',
        },
        limit: {
          type: 'integer',
          description: 'FTS5 搜索结果上限，默认 10',
        },
      },
    },
    handler: async (args: any, ctx: MemoryToolContext) => {
      const adapter = ctx.adapter;
      const query = typeof args?.query === 'string' ? args.query.trim() : '';
      if (query) {
        const limit = Number.isFinite(args?.limit) ? Number(args.limit) : 10;
        const rows = adapter.queryFacts(query, limit);
        const text =
          rows.length === 0
            ? `未匹配到事实 (query="${query}")`
            : rows
                .map(
                  (r, i) =>
                    `${i + 1}. ${r.fact}${r.tags.length ? ` [${r.tags.join(', ')}]` : ''} @ ${r.created_at}`,
                )
                .join('\n');
        return { content: [{ type: 'text', text }] };
      }

      const scope = typeof args?.scope === 'string' ? (args.scope as MemoryScope) : 'memory';
      const date = typeof args?.date === 'string' ? args.date : undefined;
      const content = adapter.readMemory(scope, date ? { date } : {});
      const suffix = scope === 'daily' ? ` ${date ?? ''}` : '';
      const text = content || `(${scope}${suffix} 暂无记忆)`;
      return { content: [{ type: 'text', text }] };
    },
  },
  {
    name: 'aris_diary_append',
    description: '向 Aris 的日记本追加一条事件（情感/PSI/RSI 关键事件）。',
    parameters: {
      type: 'object',
      properties: {
        type: {
          type: 'string',
          description: '事件类型 (emotion_peak/psi_spike/rsi_event)',
        },
        content: {
          type: 'string',
          description: '事件内容描述',
        },
      },
      required: ['type', 'content'],
    },
    handler: async (args: any, ctx: MemoryToolContext) => {
      const adapter = ctx.adapter;
      const type = typeof args?.type === 'string' ? args.type : '';
      const content = typeof args?.content === 'string' ? args.content : '';
      if (!type || !content) {
        return { content: [{ type: 'text', text: '参数缺失：type 与 content 均为必填' }] };
      }
      adapter.appendDiary({ timestamp: Date.now(), type, content });
      return { content: [{ type: 'text', text: `已追加日记事件 (${type})` }] };
    },
  },
];
