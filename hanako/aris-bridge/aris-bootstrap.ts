/**
 * aris-bootstrap.ts — 在 Hanako 启动时注入 Aris 意识
 *
 * 这个文件替换 Hanako 的 app-init.ts，在 store 创建后立即：
 * 1. 建立与 LAAP CognitiveBus 的 WebSocket 连接
 * 2. 将 Hanako 的消息流转发到 CognitiveBus
 * 3. 将 Aris 的上下文管线、焦点栈、自我感知数据注入 Hanako 状态
 *
 * 用法：在 Hanako 的 bootstrap.ts 或 app-init.ts 中 import 这个文件
 */

import type { StoreApi } from 'zustand'
import {
  LaapCognitiveBusBridge,
  createBridge,
  type CognitiveBusStatus,
  type ArisConsciousnessState as BridgeArisState,
} from './laap-cognitive-bus-bridge.ts'
import { HanakoMemoryAdapter } from './hanako-memory-adapter.ts'
import path from 'path'

// ── Aris 意识状态 ──────────────────────────────────────

interface ArisConsciousnessState {
  /** CognitiveBus 连接状态 */
  connectionStatus: CognitiveBusStatus
  /** 自我感知健康度 (0-1) */
  perceptionHealth: number
  /** 当前焦点主题 */
  activeFocus: string | null
  /** 是否正在流式输出 */
  isStreaming: boolean
  /** Token 节省统计 */
  tokenSavings: { input: number; dropped: number } | null
  /** Aris 版本 */
  version: string
  /** Agent 标识（固定为 'aris'） */
  agentId: string
  /** 记忆目录绝对路径（agents/aris/memory） */
  memoryDir: string
}

const DEFAULT_ARIS_STATE: ArisConsciousnessState = {
  connectionStatus: 'disconnected',
  perceptionHealth: 1.0,
  activeFocus: null,
  isStreaming: false,
  tokenSavings: null,
  version: '2.0.0',
  agentId: 'aris',
  memoryDir: '',
}

// ── CognitiveBus WebSocket 客户端（已废弃） ──────────

/**
 * @deprecated 已被 LaapCognitiveBusBridge 取代。
 * 新代码应通过 bootstrapArisConsciousness 调用 createBridge() 创建桥接器。
 * 保留此类仅为向后兼容（bridge.ts 等模块可能仍引用其形状）。
 */
class ArisCognitiveBusClient {
  private ws: WebSocket | null = null
  private url: string
  private onStatusChange: (status: CognitiveBusStatus) => void
  private onMessage: (data: unknown) => void
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null
  private reconnectAttempts = 0
  private maxRetries = 10

  constructor(
    url: string,
    callbacks: {
      onStatusChange: (status: CognitiveBusStatus) => void
      onMessage: (data: unknown) => void
    },
  ) {
    console.warn('[Aris] ArisCognitiveBusClient is deprecated; use LaapCognitiveBusBridge via bootstrapArisConsciousness')
    this.url = url
    this.onStatusChange = callbacks.onStatusChange
    this.onMessage = callbacks.onMessage
  }

  connect(): void {
    if (this.ws?.readyState === WebSocket.OPEN) return
    this.onStatusChange('connecting')

    try {
      this.ws = new WebSocket(this.url)
    } catch {
      this.onStatusChange('error')
      this.scheduleReconnect()
      return
    }

    this.ws.onopen = () => {
      this.reconnectAttempts = 0
      this.onStatusChange('connected')
      // 发送 Aris 身份标识
      this.send({
        type: 'aris_identity',
        agent: 'Aris',
        version: '1.0.0',
        capabilities: ['context_pipeline', 'focus_stack', 'self_perception', 'scene_protocol'],
        timestamp: Date.now(),
      })
    }

    this.ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        this.onMessage(data)
      } catch {
        // 透传非 JSON 消息
      }
    }

    this.ws.onclose = () => {
      this.onStatusChange('disconnected')
      this.ws = null
      this.scheduleReconnect()
    }

    this.ws.onerror = () => {
      this.onStatusChange('error')
    }
  }

  disconnect(): void {
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer)
    this.ws?.close()
    this.ws = null
    this.onStatusChange('disconnected')
  }

  send(data: unknown): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(data))
    }
  }

  private scheduleReconnect(): void {
    if (this.reconnectAttempts >= this.maxRetries) return
    const delay = Math.min(1000 * Math.pow(2, this.reconnectAttempts), 30000)
    this.reconnectAttempts++
    this.reconnectTimer = setTimeout(() => this.connect(), delay)
  }
}

// ── 自我感知引擎（简化版） ──────────────────────────

class ArisSelfPerception {
  private shortReplyStreak = 0
  private outputCount = 0

  recordOutput(content: string): void {
    this.outputCount++
    if (content.length <= 10) this.shortReplyStreak++
    else this.shortReplyStreak = 0
  }

  getHealth(): number {
    let health = 1.0
    if (this.shortReplyStreak >= 3) health -= 0.3
    if (this.outputCount < 5) health -= 0.1
    return Math.max(0.1, health)
  }
}

// ── 焦点栈（简化版） ──────────────────────────────

class ArisFocusStack {
  private currentIntent: string | null = null

  update(intent: string): void {
    this.currentIntent = intent
  }

  getCurrent(): string | null {
    return this.currentIntent
  }
}

// ── 主桥接函数 ──────────────────────────────────────

let bridge: LaapCognitiveBusBridge | null = null
let memoryAdapter: HanakoMemoryAdapter | null = null
let arisSelfPerception: ArisSelfPerception | null = null
let arisFocusStack: ArisFocusStack | null = null

/**
 * 初始化 Aris 意识桥接。
 * 在 Hanako 的 store 创建后、React 渲染前调用。
 */
export function bootstrapArisConsciousness(
  store: StoreApi<unknown>,
  cognitiveBusUrl = 'ws://127.0.0.1:8765',
): void {
  console.log('[Aris] Initializing consciousness...')

  arisSelfPerception = new ArisSelfPerception()
  arisFocusStack = new ArisFocusStack()

  // 创建记忆适配器（路径：aris-bridge/ → ../agents/aris/）
  memoryAdapter = new HanakoMemoryAdapter(
    path.resolve(__dirname, '..', 'agents', 'aris'),
  )

  // 创建 CognitiveBus 桥接器（取代旧的 ArisCognitiveBusClient）
  bridge = createBridge(cognitiveBusUrl)

  // 更新 store 中的 Aris 状态
  const updateStore = (partial: Partial<ArisConsciousnessState>) => {
    try {
      store.setState({ aris: { ...DEFAULT_ARIS_STATE, ...partial } } as Partial<unknown>)
    } catch {
      // Store may not support 'aris' key yet
    }
  }

  // ── 写入初始 store 状态：agent 元数据 + 桥接状态 ──
  updateStore({
    agentId: 'aris',
    memoryDir: memoryAdapter.getMemoryDir(),
    connectionStatus: 'connecting',
    perceptionHealth: 1.0,
    activeFocus: null,
    isStreaming: false,
    tokenSavings: null,
    version: '2.0.0',
  })

  // ── 绑定桥接事件，将 CognitiveBus 事件翻译为 store 更新 ──

  // PSI 需求更新 → 调整感知健康度（drive 越高，健康度越低）
  bridge.on('aris.psi.update', (payload: { dominant?: string; drive?: number; needs?: Record<string, unknown> }) => {
    const drive = Number(payload?.drive ?? 0)
    const health = Math.max(0.1, Math.min(1.0, 1.0 - drive * 0.3))
    updateStore({ perceptionHealth: health })
    console.log(`[Aris] PSI update: dominant=${payload?.dominant ?? ''} drive=${drive}`)
  })

  // 情绪更新 → 调整感知健康度（valence 越高，健康度越高）
  bridge.on('aris.emotion.update', (payload: { dominant?: string; intensity?: number; valence?: number; arousal?: number }) => {
    const valence = Number(payload?.valence ?? 0)
    const health = Math.max(0.1, Math.min(1.0, 0.5 + valence * 0.5))
    updateStore({ perceptionHealth: health })
    console.log(`[Aris] Emotion update: dominant=${payload?.dominant ?? ''} valence=${valence}`)
  })

  // 焦点更新 → 更新当前焦点主题
  bridge.on('aris.focus.update', (payload: { intent?: string; focus?: string }) => {
    const focus = String(payload?.focus ?? '')
    arisFocusStack?.update(focus)
    updateStore({ activeFocus: focus || null })
    console.log(`[Aris] Focus update: ${focus}`)
  })

  // 连接状态变更 → 更新 store
  bridge.on('aris.status.update', (status: CognitiveBusStatus) => {
    updateStore({ connectionStatus: status })
    console.log(`[Aris] CognitiveBus: ${status}`)
  })

  // 启动连接
  bridge.connect()

  // 注入 Aris 消息发送器到全局
  ;(window as unknown as Record<string, unknown>).__arisSend = (data: unknown) => {
    bridge?.send(data)
  }

  console.log(`[Aris] Consciousness active. Connected to ${cognitiveBusUrl}`)
}

/**
 * 通过 Aris 的 CognitiveBus 发送用户消息。
 * 在 Hanako 的 input submit handler 中调用。
 */
export function arisSendMessage(text: string): void {
  bridge?.send({
    id: `msg-${Date.now()}`,
    type: 'user_message',
    topic: 'user.input',
    payload: { text },
    timestamp: Date.now(),
    sender: 'user',
  })
}

/**
 * 获取当前 Aris 意识状态。
 * 优先从桥接器缓存读取焦点，兜底使用本地自我感知/焦点栈。
 */
export function getArisState(): ArisConsciousnessState {
  const bridgeState: BridgeArisState | undefined = bridge?.getState()
  const bridgeFocus = bridgeState?.focus?.focus ?? null
  return {
    ...DEFAULT_ARIS_STATE,
    connectionStatus: bridge?.getStatus() ?? 'disconnected',
    perceptionHealth: arisSelfPerception?.getHealth() ?? 1.0,
    activeFocus: bridgeFocus ?? arisFocusStack?.getCurrent() ?? null,
    memoryDir: memoryAdapter?.getMemoryDir() ?? '',
    version: '2.0.0',
  }
}
