import { useWebSocketStore } from '@/stores/webSocketStore'
import {
  getWebSocketUrl,
  type WsClientMessage,
  type WsServerMessage,
} from '@/ws/protocol'
import type { PageWebSocketStatus } from '@/ws/usePageWebSocket'

export interface TopicHandler {
  onSnapshot?: (data: unknown) => void
  onUpdate?: (data: unknown) => void
  onError?: (code?: string, message?: string) => void
}

class WebSocketManager {
  private ws: WebSocket | null = null
  private requestId = 1
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null
  private readonly topicHandlers = new Map<string, Set<TopicHandler>>()
  private readonly topicRefCount = new Map<string, number>()

  acquireTopic(topic: string, handler: TopicHandler): void {
    const handlers = this.topicHandlers.get(topic) ?? new Set<TopicHandler>()
    handlers.add(handler)
    this.topicHandlers.set(topic, handlers)

    const prev = this.topicRefCount.get(topic) ?? 0
    this.topicRefCount.set(topic, prev + 1)

    if (prev === 0) {
      this.sendSubscribe([topic])
    }

    this.ensureConnected()
  }

  releaseTopic(topic: string, handler: TopicHandler): void {
    const handlers = this.topicHandlers.get(topic)
    handlers?.delete(handler)
    if (handlers && handlers.size === 0) {
      this.topicHandlers.delete(topic)
    }

    const prev = this.topicRefCount.get(topic) ?? 0
    if (prev <= 0) {
      return
    }

    const next = prev - 1
    if (next === 0) {
      this.topicRefCount.delete(topic)
      this.sendUnsubscribe([topic])
    } else {
      this.topicRefCount.set(topic, next)
    }

    if (this.getActiveTopics().length === 0) {
      this.scheduleDisconnect()
    }
  }

  getStatus(): PageWebSocketStatus {
    return useWebSocketStore.getState().status
  }

  private setStatus(status: PageWebSocketStatus): void {
    useWebSocketStore.getState().setStatus(status)
  }

  private getActiveTopics(): string[] {
    return Array.from(this.topicRefCount.keys())
  }

  private ensureConnected(): void {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }

    if (this.ws?.readyState === WebSocket.OPEN || this.ws?.readyState === WebSocket.CONNECTING) {
      return
    }

    this.connect()
  }

  private scheduleDisconnect(): void {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer)
    }
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null
      if (this.getActiveTopics().length === 0) {
        this.disconnect()
      }
    }, 300)
  }

  private connect(): void {
    this.disconnect(false)
    this.setStatus('connecting')

    const ws = new WebSocket(getWebSocketUrl())
    this.ws = ws

    ws.onopen = () => {
      this.setStatus('open')
      const topics = this.getActiveTopics()
      if (topics.length > 0) {
        this.sendSubscribe(topics)
      }
    }

    ws.onmessage = (event) => {
      let payload: WsServerMessage
      try {
        payload = JSON.parse(String(event.data)) as WsServerMessage
      } catch {
        return
      }

      const channel = payload.channel
      if (!channel) {
        return
      }

      const handlers = this.topicHandlers.get(channel)
      if (!handlers || handlers.size === 0) {
        return
      }

      if (payload.type === 'SNAPSHOT') {
        for (const handler of handlers) {
          handler.onSnapshot?.(payload.data)
        }
        return
      }

      if (payload.type === 'UPDATE') {
        for (const handler of handlers) {
          handler.onUpdate?.(payload.data)
        }
        return
      }

      if (payload.type === 'ERROR') {
        for (const handler of handlers) {
          handler.onError?.(payload.code, payload.message)
        }
      }
    }

    ws.onerror = () => {
      this.setStatus('error')
    }

    ws.onclose = () => {
      if (this.ws === ws) {
        this.ws = null
      }

      if (this.getActiveTopics().length > 0) {
        this.setStatus('connecting')
        this.reconnectTimer = setTimeout(() => {
          this.reconnectTimer = null
          this.ensureConnected()
        }, 1500)
        return
      }

      this.setStatus('closed')
    }
  }

  private disconnect(updateStatus = true): void {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }

    if (this.ws) {
      this.ws.onopen = null
      this.ws.onmessage = null
      this.ws.onerror = null
      this.ws.onclose = null
      this.ws.close()
      this.ws = null
    }

    if (updateStatus && this.getActiveTopics().length === 0) {
      this.setStatus('idle')
    }
  }

  private sendSubscribe(topics: string[]): void {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN || topics.length === 0) {
      return
    }

    const message: WsClientMessage = {
      method: 'SUBSCRIBE',
      params: topics,
      id: this.requestId++,
    }
    this.ws.send(JSON.stringify(message))
  }

  private sendUnsubscribe(topics: string[]): void {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN || topics.length === 0) {
      return
    }

    const message: WsClientMessage = {
      method: 'UNSUBSCRIBE',
      params: topics,
      id: this.requestId++,
    }
    this.ws.send(JSON.stringify(message))
  }
}

export const webSocketManager = new WebSocketManager()
