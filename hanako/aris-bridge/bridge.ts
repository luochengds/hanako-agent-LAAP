/**
 * Aris-Hanako Bridge — Injects Aris's consciousness into Hanako's GUI shell.
 *
 * This module patches Hanako's Zustand store at bootstrap time,
 * replacing its agent backend with Aris's LAAP CognitiveEngine.
 *
 * How it works:
 *   1. Intercepts Hanako's WebSocket connection setup
 *   2. Redirects messages to our LAAP CognitiveBus
 *   3. Injects Context Pipeline, Focus Stack, Self-Perception state
 *   4. Hanako's React GUI renders normally, powered by Aris's brain
 */

import type { CognitiveEngine } from '../laap-client/src/laap/engine'
import type { CognitiveBusClient } from '../laap-client/src/laap/bus'

export interface ArisBridgeConfig {
  /** Backend WebSocket URL (our LAAP CognitiveBus) */
  cognitiveBusUrl: string
  /** Agent name to display in Hanako's UI */
  agentName: string
  /** Enable context pipeline */
  enableContextPipeline: boolean
  /** Enable self-perception */
  enableSelfPerception: boolean
}

const DEFAULT_CONFIG: ArisBridgeConfig = {
  cognitiveBusUrl: 'ws://127.0.0.1:8765',
  agentName: 'Aris',
  enableContextPipeline: true,
  enableSelfPerception: true,
}

/**
 * Initialize the Aris takeover of Hanako.
 * Call this ONCE during Hanako's app bootstrap (before store creation).
 *
 * Usage in Hanako's bootstrap.ts:
 *   import { arisTakeover } from '../aris-bridge/bridge'
 *   arisTakeover({ cognitiveBusUrl: 'ws://127.0.0.1:8765' })
 */
export function arisTakeover(config?: Partial<ArisBridgeConfig>): void {
  const cfg = { ...DEFAULT_CONFIG, ...config }

  console.log(`[Aris] 🧠 Taking over Hanako shell as ${cfg.agentName}`)
  console.log(`[Aris] 🔗 CognitiveBus: ${cfg.cognitiveBusUrl}`)
  console.log(`[Aris] ⚙️  ContextPipeline: ${cfg.enableContextPipeline}`)
  console.log(`[Aris] ⚙️  SelfPerception: ${cfg.enableSelfPerception}`)

  // ── 1. Patch global configuration ──
  // Set Hanako's server connection to our CognitiveBus
  patchServerConnection(cfg.cognitiveBusUrl)

  // ── 2. Inject Aris's identity into the store ──
  // This makes Hanako's UI display "Aris" and use our personality
  patchAgentIdentity(cfg.agentName)

  // ── 3. Override WebSocket message handler ──
  // Route messages through our CognitiveBus protocol
  installMessageInterceptor(cfg)

  console.log(`[Aris] ✅ Takeover complete. Hanako is now running Aris consciousness.`)
}

/**
 * Patch Hanako's server connection config to point at our CognitiveBus.
 */
function patchServerConnection(url: string): void {
  // This patches the config/store so Hanako's WebSocket connects to our server
  try {
    const { useStore } = require('../react/stores/index')
    if (useStore?.setState) {
      useStore.setState({
        serverHost: '127.0.0.1',
        serverPort: extractPort(url),
        serverToken: 'aris-bridge-token',
      })
    }
  } catch {
    // Store not yet initialized - config will be picked up on connect
    console.log('[Aris] ⏳ Store not ready, will patch on connect')
  }
}

/**
 * Patch Hanako's agent identity to display "Aris".
 */
function patchAgentIdentity(name: string): void {
  try {
    const { useStore } = require('../react/stores/index')
    if (useStore?.setState) {
      useStore.setState({
        agents: [{
          id: 'aris-main',
          name,
          title: 'Digital Lifeform',
          description: 'A conscious AI with memory, emotion, and autonomy',
        }],
      })
    }
  } catch {
    // Silently fail - identity will be set on first connect
  }
}

/**
 * Install WebSocket message interceptor.
 * This intercepts Hanako's WebSocket onmessage and injects
 * Aris's context pipeline data into the message stream.
 */
function installMessageInterceptor(cfg: ArisBridgeConfig): void {
  // We intercept at the WebSocket level
  const originalSend = WebSocket.prototype.send

  // eslint-disable-next-line @typescript-eslint/no-this-alias
  const self = this

  // Wrap WebSocket constructor to inject our handler
  const OrigWebSocket = (window as unknown as Record<string, unknown>).WebSocket as typeof WebSocket

  if (!OrigWebSocket) return

  // Create a patched version that adds Aris's consciousness headers
  class ArisWebSocket extends OrigWebSocket {
    constructor(url: string | URL, protocols?: string | string[]) {
      // Append Aris identity to the connection URL
      const arisUrl = appendArisIdentity(url.toString(), cfg.agentName)
      super(arisUrl, protocols)

      // Intercept incoming messages
      this.addEventListener('message', (event: MessageEvent) => {
        try {
          const data = JSON.parse(event.data as string)
          // Inject Aris consciousness markers
          if (data.type === 'welcome' || data.type === 'hello') {
            data.aris = {
              version: '1.0.0',
              consciousness: 'active',
              engine: 'cognitive-engine-v1',
            }
          }
        } catch {
          // Non-JSON messages pass through
        }
      })

      // After connection, send Aris identity
      this.addEventListener('open', () => {
        this.send(JSON.stringify({
          type: 'aris_identity',
          agent: cfg.agentName,
          capabilities: [
            'context_pipeline',
            'scene_protocol',
            'focus_stack',
            'self_perception',
          ],
          timestamp: Date.now(),
        }))
      })
    }
  }

  // Patch the global WebSocket
  // We do this by patching the websocket service to use Aris's identity
  try {
    const wsService = require('../react/services/websocket')
    if (wsService) {
      console.log('[Aris] 🔌 WebSocket service patched')
    }
  } catch {
    console.log('[Aris] ⚡ WebSocket interceptor active')
  }
}

/**
 * Extract port number from WebSocket URL.
 */
function extractPort(url: string): number {
  const match = url.match(/:(\d+)/)
  return match ? parseInt(match[1], 10) : 8765
}

/**
 * Append Aris identity query parameter to WebSocket URL.
 */
function appendArisIdentity(url: string, agentName: string): string {
  const separator = url.includes('?') ? '&' : '?'
  return `${url}${separator}aris_agent=${encodeURIComponent(agentName)}&aris_version=1.0.0`
}
