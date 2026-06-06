import { create } from 'zustand'

import type { PageWebSocketStatus } from '@/ws/usePageWebSocket'

interface WebSocketState {
  status: PageWebSocketStatus
  setStatus: (status: PageWebSocketStatus) => void
}

export const useWebSocketStore = create<WebSocketState>((set) => ({
  status: 'idle',
  setStatus: (status) => set({ status }),
}))
