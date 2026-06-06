import { useEffect, useMemo, useRef } from 'react'

import { webSocketManager } from '@/ws/webSocketManager'
import { useWebSocketStore } from '@/stores/webSocketStore'

export type PageWebSocketStatus = 'idle' | 'connecting' | 'open' | 'closed' | 'error'

export interface UsePageWebSocketOptions<T = unknown> {
  topics: string[]
  enabled?: boolean
  onSnapshot?: (channel: string, data: T) => void
  onUpdate?: (channel: string, data: T) => void
  onError?: (channel: string | undefined, code: string | undefined, message: string | undefined) => void
}

export function usePageWebSocket<T = unknown>({
  topics,
  enabled = true,
  onSnapshot,
  onUpdate,
  onError,
}: UsePageWebSocketOptions<T>) {
  const status = useWebSocketStore((state) => state.status)
  const callbacksRef = useRef({ onSnapshot, onUpdate, onError })
  const topicsKey = useMemo(() => topics.join('|'), [topics])

  useEffect(() => {
    callbacksRef.current = { onSnapshot, onUpdate, onError }
  }, [onSnapshot, onUpdate, onError])

  useEffect(() => {
    if (!enabled || topics.length === 0) {
      return
    }

    const cleanups = topics.map((topic) => {
      const handler = {
        onSnapshot: (data: unknown) => {
          callbacksRef.current.onSnapshot?.(topic, data as T)
        },
        onUpdate: (data: unknown) => {
          callbacksRef.current.onUpdate?.(topic, data as T)
        },
        onError: (code?: string, message?: string) => {
          callbacksRef.current.onError?.(topic, code, message)
        },
      }

      webSocketManager.acquireTopic(topic, handler)
      return () => webSocketManager.releaseTopic(topic, handler)
    })

    return () => {
      for (const cleanup of cleanups) {
        cleanup()
      }
    }
    // topicsKey 稳定标识 topics 内容，避免内联数组导致重复订阅
    // eslint-disable-next-line react-hooks/exhaustive-deps -- topics 已通过 topicsKey 追踪
  }, [enabled, topicsKey])

  return { status }
}
