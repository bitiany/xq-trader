import { create } from 'zustand'

interface SignalNotification {
  id: number
  symbol: string
  symbol_name: string | null
  side: string
  strategy_code: string | null
  price: number | null
  reason: string | null
  confidence: number | null
  created_at: string | null
}

interface SignalNotificationState {
  /** 未读信号列表（最新的在前） */
  notifications: SignalNotification[]
  /** 未读数量 */
  unreadCount: number
  /** 添加新信号通知 */
  addNotification: (signal: SignalNotification) => void
  /** 标记全部已读 */
  markAllRead: () => void
  /** 清空通知 */
  clearAll: () => void
}

const MAX_NOTIFICATIONS = 50

export const useSignalNotificationStore = create<SignalNotificationState>((set) => ({
  notifications: [],
  unreadCount: 0,

  addNotification: (signal) =>
    set((state) => {
      const notifications = [signal, ...state.notifications].slice(0, MAX_NOTIFICATIONS)
      return { notifications, unreadCount: notifications.length }
    }),

  markAllRead: () => set({ unreadCount: 0 }),

  clearAll: () => set({ notifications: [], unreadCount: 0 }),
}))
