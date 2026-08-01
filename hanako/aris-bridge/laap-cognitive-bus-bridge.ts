/**
 * laap-cognitive-bus-bridge.ts — Hanako 与 LAAP CognitiveBus 的 TypeScript 桥接
 *
 * 该模块在 Hanako 插件主进程内运行，负责：
 *   1. 通过 WebSocket 连接 LAAP CognitiveBus（默认 ws://127.0.0.1:8765）
 *   2. 将 CognitiveBus 事件翻译为 Aris 意识事件（aris.psi.update 等）
 *   3. 在连接失败超过 30 秒后进入 degraded 模式，轮询 sidecar HTTP 端点
 *   4. 缓存最新 PSI / 情绪 / 焦点状态，供 Hanako 状态查询
 *
 * 用法：
 *   import { createBridge } from './laap-cognitive-bus-bridge'
 *   const bridge = createBridge()
 *   bridge.on('aris.psi.update', (p) => console.log(p))
 *   bridge.connect()
 */

import { EventEmitter } from 'events'

// ── 浏览器安全 Emitter ─────────────────────────────────────
// Node 的 EventEmitter 无法在 renderer（vite 浏览器打包）中编译。
// 这里提供一个最小等价实现：on/emit/off/removeAllListeners。
class SafeEmitter {
  private _listeners: Record<string, Array<(payload: any) => void>> = {}
  on(event: string, cb: (payload: any) => void) {
    ;(this._listeners[event] ??= []).push(cb)
    return this
  }
  emit(event: string, payload?: any) {
    for (const cb of this._listeners[event] ?? []) {
      try { cb(payload) } catch { /* 单监听器错误不拖垮其他 */ }
    }
    return true
  }
  off(event: string, cb: (payload: any) => void) {
    this._listeners[event] = (this._listeners[event] ?? []).filter(f => f !== cb)
    return this
  }
  removeAllListeners(event?: string) {
    if (event) delete this._listeners[event]
    else this._listeners = {}
    return this
  }
}

// ── 类型定义 ──────────────────────────────────────────

/** CognitiveBus 连接状态 */
export type CognitiveBusStatus =
  | 'disconnected'
  | 'connecting'
  | 'connected'
  | 'error'
  | 'degraded'

/** CognitiveBus 原始事件 */
export interface CognitiveBusEvent {
  type: string
  payload?: Record<string, unknown>
  [key: string]: unknown
}

/** Aris 意识聚合状态（getState 返回的缓存快照） */
export interface ArisConsciousnessState {
  /** 连接状态 */
  connectionStatus: CognitiveBusStatus
  /** PSI 需求状态快照 */
  psi: {
    dominant: string
    drive: number
    needs: Record<string, unknown>
  } | null
  /** 情绪状态快照 */
  emotion: {
    dominant: string
    intensity: number
    valence: number
    arousal: number
    emotions: Record<string, unknown>
  } | null
  /** 焦点状态快照 */
  focus: {
    intent: string
    focus: string
  } | null
  /** 最近一次执行结果 */
  lastExecution: {
    success: boolean
    result: unknown
    duration_ms: number
  } | null
  /** Aris 桥接版本 */
  version: string
}

// ── 常量 ──────────────────────────────────────────────

const DEFAULT_BUS_URL = 'ws://127.0.0.1:8765'
const DEFAULT_SIDECAR_URL = 'http://127.0.0.1:11521/cognitive_context'
const DEGRADED_THRESHOLD_MS = 30_000
const POLLING_INTERVAL_MS = 10_000
const MAX_RETRIES = 10
const MAX_BACKOFF_MS = 30_000
const BRIDGE_VERSION = '1.0.0'

const DEFAULT_STATE: ArisConsciousnessState = {
  connectionStatus: 'disconnected',
  psi: null,
  emotion: null,
  focus: null,
  lastExecution: null,
  version: BRIDGE_VERSION,
}

// ── LaapCognitiveBusBridge ───────────────────────────

/**
 * LAAP CognitiveBus 桥接器。
 *
 * 继承 EventEmitter，翻译后的事件通过 emit 抛出：
 *   - aris.psi.update        —— need_* 事件
 *   - aris.emotion.update    —— emotion_* 事件
 *   - aris.focus.update      —— v12_kernel 事件
 *   - aris.execution.result  —— harness_execution_result 事件
 *   - aris.qre.update        —— qre_* 事件（透传 payload）
 *   - aris.status.update     —— 连接状态变更
 */
export class LaapCognitiveBusBridge extends SafeEmitter {
  private ws: WebSocket | null = null
  private readonly url: string
  private readonly sidecarUrl: string
  private status: CognitiveBusStatus = 'disconnected'
  private cachedState: ArisConsciousnessState

  private reconnectAttempts = 0
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null
  private degradedTimer: ReturnType<typeof setTimeout> | null = null
  private pollingTimer: ReturnType<typeof setInterval> | null = null
  private firstFailureTime: number | null = null
  private degradedModeActive = false

  constructor(
    url: string = DEFAULT_BUS_URL,
    sidecarUrl: string = DEFAULT_SIDECAR_URL,
  ) {
    super()
    this.url = url
    this.sidecarUrl = sidecarUrl
    this.cachedState = { ...DEFAULT_STATE }
  }

  /**
   * 建立 CognitiveBus WebSocket 连接。
   * 已连接或正在连接时重复调用安全（幂等）。
   */
  connect(): void {
    if (this.status === 'connected' || this.status === 'connecting') return
    if (this.ws?.readyState === WebSocket.OPEN) return

    // 降级模式下保持 degraded 状态标记，不回退到 connecting
    if (!this.degradedModeActive) {
      this.setStatus('connecting')
    }

    try {
      this.ws = new WebSocket(this.url)
    } catch {
      this.recordFailure()
      this.setStatus('error')
      this.scheduleReconnect()
      return
    }

    this.ws.onopen = () => {
      this.reconnectAttempts = 0
      this.firstFailureTime = null
      this.degradedModeActive = false
      this.clearDegradedTimer()
      this.stopPolling()
      this.setStatus('connected')
      // 发送 Aris 身份标识
      this.send({
        type: 'aris_identity',
        agent: 'Aris',
        version: BRIDGE_VERSION,
        capabilities: [
          'context_pipeline',
          'focus_stack',
          'self_perception',
          'scene_protocol',
        ],
        timestamp: Date.now(),
      })
    }

    this.ws.onmessage = (event: MessageEvent) => {
      this.handleRaw(event.data)
    }

    this.ws.onclose = () => {
      this.ws = null
      this.recordFailure()
      // 降级模式下回到 degraded，否则标记 disconnected
      this.setStatus(this.degradedModeActive ? 'degraded' : 'disconnected')
      this.scheduleReconnect()
    }

    this.ws.onerror = () => {
      this.recordFailure()
      if (!this.degradedModeActive) {
        this.setStatus('error')
      }
    }
  }

  /**
   * 主动断开连接，停止重连与轮询。
   */
  disconnect(): void {
    this.clearReconnectTimer()
    this.clearDegradedTimer()
    this.stopPolling()
    if (this.ws) {
      try {
        this.ws.close()
      } catch {
        // 关闭异常忽略
      }
      this.ws = null
    }
    this.firstFailureTime = null
    this.degradedModeActive = false
    this.setStatus('disconnected')
  }

  /**
   * 向 CognitiveBus 发送 JSON 数据。连接未就绪时静默丢弃。
   * @param data 可序列化的消息体
   */
  send(data: unknown): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      try {
        this.ws.send(JSON.stringify(data))
      } catch {
        // 透传失败忽略
      }
    }
  }

  /**
   * 获取当前连接状态。
   */
  getStatus(): CognitiveBusStatus {
    return this.status
  }

  /**
   * 获取最新缓存的 Aris 意识状态快照。
   * 返回的是深拷贝，修改不会影响内部缓存。
   */
  getState(): ArisConsciousnessState {
    return { ...this.cachedState, connectionStatus: this.status }
  }

  // ── 内部：连接状态 ───────────────────────────────

  private setStatus(status: CognitiveBusStatus): void {
    if (this.status === status) return
    this.status = status
    this.cachedState.connectionStatus = status
    this.emit('aris.status.update', status)
  }

  private updateCache(partial: Partial<ArisConsciousnessState>): void {
    this.cachedState = { ...this.cachedState, ...partial }
  }

  // ── 内部：重连退避 ───────────────────────────────

  private scheduleReconnect(): void {
    if (this.reconnectAttempts >= MAX_RETRIES) return
    const delay = Math.min(
      1000 * Math.pow(2, this.reconnectAttempts),
      MAX_BACKOFF_MS,
    )
    this.reconnectAttempts++
    this.clearReconnectTimer()
    this.reconnectTimer = setTimeout(() => this.connect(), delay)
  }

  private clearReconnectTimer(): void {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
  }

  // ── 内部：降级模式 ───────────────────────────────

  private recordFailure(): void {
    if (this.firstFailureTime === null) {
      this.firstFailureTime = Date.now()
      this.degradedTimer = setTimeout(() => {
        // 30 秒后仍未连接则进入降级模式
        if (this.status !== 'connected' && this.status !== 'connecting') {
          this.enterDegradedMode()
        }
      }, DEGRADED_THRESHOLD_MS)
    }
  }

  private clearDegradedTimer(): void {
    if (this.degradedTimer) {
      clearTimeout(this.degradedTimer)
      this.degradedTimer = null
    }
  }

  private enterDegradedMode(): void {
    this.degradedModeActive = true
    this.setStatus('degraded')
    this.stopPolling()
    // 立即触发一次，随后按间隔轮询
    void this.pollSidecar()
    this.pollingTimer = setInterval(() => {
      void this.pollSidecar()
    }, POLLING_INTERVAL_MS)
  }

  private stopPolling(): void {
    if (this.pollingTimer) {
      clearInterval(this.pollingTimer)
      this.pollingTimer = null
    }
  }

  /**
   * 轮询 sidecar HTTP 端点获取 PSI / 情绪 / 焦点状态。
   * 成功取回后翻译为 aris.psi.update / aris.emotion.update / aris.focus.update。
   */
  private async pollSidecar(): Promise<void> {
    try {
      const res = await fetch(this.sidecarUrl, {
        method: 'GET',
        headers: { Accept: 'application/json' },
      })
      if (!res.ok) {
        throw new Error(`sidecar responded ${res.status}`)
      }
      const data = (await res.json()) as Record<string, unknown>

      if (data.psi && typeof data.psi === 'object') {
        const psi = data.psi as Record<string, unknown>
        const payload = {
          dominant: String(psi.dominant ?? ''),
          drive: Number(psi.drive ?? 0),
          needs: (psi.needs as Record<string, unknown>) ?? {},
        }
        this.updateCache({ psi: payload })
        this.emit('aris.psi.update', payload)
      }

      if (data.emotion && typeof data.emotion === 'object') {
        const emo = data.emotion as Record<string, unknown>
        const payload = {
          dominant: String(emo.dominant ?? ''),
          intensity: Number(emo.intensity ?? 0),
          valence: Number(emo.valence ?? 0),
          arousal: Number(emo.arousal ?? 0),
          emotions: (emo.emotions as Record<string, unknown>) ?? {},
        }
        this.updateCache({ emotion: payload })
        this.emit('aris.emotion.update', payload)
      }

      if (data.focus && typeof data.focus === 'object') {
        const f = data.focus as Record<string, unknown>
        const payload = {
          intent: String(f.intent ?? ''),
          focus: String(f.focus ?? ''),
        }
        this.updateCache({ focus: payload })
        this.emit('aris.focus.update', payload)
      }
    } catch {
      // 轮询失败静默忽略，下一轮继续
    }
  }

  // ── 内部：消息翻译 ───────────────────────────────

  private handleRaw(raw: unknown): void {
    let text: string
    if (typeof raw === 'string') {
      text = raw
    } else if (raw instanceof ArrayBuffer) {
      text = new TextDecoder().decode(raw)
    } else {
      text = String(raw)
    }

    let data: unknown
    try {
      data = JSON.parse(text)
    } catch {
      // 非 JSON 消息丢弃
      return
    }

    this.translate(data as CognitiveBusEvent)
  }

  private translate(evt: CognitiveBusEvent): void {
    const type = String(evt?.type ?? '')
    const payload = (evt.payload as Record<string, unknown> | undefined) ?? {}

    // need_* → aris.psi.update
    if (type.startsWith('need_')) {
      const p = {
        dominant: String(payload.dominant ?? type.slice(5)),
        drive: Number(payload.drive ?? 0),
        needs: (payload.needs as Record<string, unknown>) ?? {},
      }
      this.updateCache({ psi: p })
      this.emit('aris.psi.update', p)
      return
    }

    // emotion_* → aris.emotion.update
    if (type.startsWith('emotion_')) {
      const p = {
        dominant: String(payload.dominant ?? type.slice(8)),
        intensity: Number(payload.intensity ?? 0),
        valence: Number(payload.valence ?? 0),
        arousal: Number(payload.arousal ?? 0),
        emotions: (payload.emotions as Record<string, unknown>) ?? {},
      }
      this.updateCache({ emotion: p })
      this.emit('aris.emotion.update', p)
      return
    }

    // v12_kernel → aris.focus.update
    if (type === 'v12_kernel') {
      const p = {
        intent: String(payload.intent ?? ''),
        focus: String(payload.focus ?? ''),
      }
      this.updateCache({ focus: p })
      this.emit('aris.focus.update', p)
      return
    }

    // harness_execution_result → aris.execution.result
    if (type === 'harness_execution_result') {
      const p = {
        success: Boolean(payload.success ?? false),
        result: payload.result,
        duration_ms: Number(payload.duration_ms ?? 0),
      }
      this.updateCache({ lastExecution: p })
      this.emit('aris.execution.result', p)
      return
    }

    // qre_* → aris.qre.update（透传 payload）
    if (type.startsWith('qre_')) {
      this.emit('aris.qre.update', payload)
      return
    }
  }
}

// ── 工厂函数 ─────────────────────────────────────────

/**
 * 创建 CognitiveBus 桥接器实例。
 * @param url CognitiveBus WebSocket 地址，缺省 ws://127.0.0.1:8765
 */
export function createBridge(url?: string): LaapCognitiveBusBridge {
  return new LaapCognitiveBusBridge(url)
}
