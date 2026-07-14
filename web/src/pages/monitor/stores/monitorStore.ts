import { create } from 'zustand'

export type ChartPeriod = '1m' | '5m' | '15m' | 'daily'

export type MainIndicator = 'none' | 'vwap' | 'ma' | 'boll' | 'donchian' | 'chanlun' | 'td9'
export type SubIndicator = 'volume' | 'macd' | 'rsi'

export interface MonitorCellConfig {
  id: string
  symbol: string
  name: string
  period: ChartPeriod
  /** 主图指标（多选，支持缠论+神奇九转叠加） */
  mainIndicators: MainIndicator[]
  subIndicator: SubIndicator
  /** react-grid-layout item */
  layout: { x: number; y: number; w: number; h: number }
}

export interface SignalItem {
  id: number
  symbol: string
  name?: string
  direction: 'long' | 'short' | 'neutral'
  strength: number | null
  signal_type: string | null
  signal_source: string
  created_at: string
  /** 信号触发的 1m bar 时间（ISO 字符串，Shanghai 时区，如 "2026-07-13T10:32:00+08:00"），用于分时图 markPoint 定位 */
  trade_time?: string | null
  /** 原始因子值（RSI值、偏离度等），用于构建专业信号说明 */
  raw_values?: Record<string, unknown> | null
  /** 共振信号：同一根 bar 同时触发多个指标时的组合信号标记 */
  resonance?: string[] | null
}

/** WS minute_bar 推送的最新 bar（页面级统一订阅，分发给各 cell） */
export interface MinuteBarUpdate {
  symbol: string
  trade_time: string
  bar: {
    open: number
    high: number
    low: number
    close: number
    volume: number
    amount: number
  }
  /** 收到时间戳，用于 cell 判断是否已处理 */
  ts: number
}

interface MonitorState {
  /** 监控格子列表 */
  cells: MonitorCellConfig[]
  /** 信号列表 */
  signals: SignalItem[]
  /** 选中的 cell ID（用于高亮） */
  selectedCellId: string | null
  /** 放大全屏的 cell ID */
  maximizedCellId: string | null
  /** 信号区折叠 */
  signalPanelCollapsed: boolean
  /** 布局列数 */
  cols: number
  /** 行高(px) */
  rowHeight: number
  /** 最新 minute_bar 推送（页面级统一订阅，cell 通过 symbol 过滤消费） */
  latestMinuteBar: MinuteBarUpdate | null

  addCell: (symbol: string, name: string) => void
  removeCell: (id: string) => void
  updateCell: (id: string, patch: Partial<MonitorCellConfig>) => void
  updateCellLayout: (id: string, layout: { x: number; y: number; w: number; h: number }) => void
  setCells: (cells: MonitorCellConfig[]) => void
  setSelectedCellId: (id: string | null) => void
  setMaximizedCellId: (id: string | null) => void
  setSignals: (signals: SignalItem[]) => void
  addSignal: (signal: SignalItem) => void
  setSignalPanelCollapsed: (collapsed: boolean) => void
  setLatestMinuteBar: (update: MinuteBarUpdate) => void
}

let cellIdCounter = 0
function nextCellId(): string {
  cellIdCounter += 1
  return `cell-${Date.now()}-${cellIdCounter}`
}

export const useMonitorStore = create<MonitorState>((set) => ({
  cells: [],
  signals: [],
  selectedCellId: null,
  maximizedCellId: null,
  signalPanelCollapsed: false,
  cols: 6,
  rowHeight: 100,
  latestMinuteBar: null,

  addCell: (symbol, name) =>
    set((state) => {
      const existing = state.cells.find((c) => c.symbol === symbol)
      if (existing) return state

      const id = nextCellId()
      const cellCount = state.cells.length
      const w = 2
      const h = 3
      const cols = state.cols
      const x = (cellCount * w) % cols
      const y = Math.floor((cellCount * w) / cols) * h

      const newCell: MonitorCellConfig = {
        id,
        symbol,
        name,
        period: '1m',
        mainIndicators: ['vwap'],
        subIndicator: 'volume',
        layout: { x, y, w, h },
      }
      return { cells: [...state.cells, newCell] }
    }),

  removeCell: (id) =>
    set((state) => {
      const remaining = state.cells.filter((c) => c.id !== id)
      // 重置坐标，让 RGL compactType="vertical" 重新紧凑排列
      const w = 2
      const h = 3
      const cols = state.cols
      const reflowed = remaining.map((c, i) => ({
        ...c,
        layout: {
          x: (i * w) % cols,
          y: Math.floor((i * w) / cols) * h,
          w,
          h,
        },
      }))
      return {
        cells: reflowed,
        maximizedCellId: state.maximizedCellId === id ? null : state.maximizedCellId,
        selectedCellId: state.selectedCellId === id ? null : state.selectedCellId,
      }
    }),

  updateCell: (id, patch) =>
    set((state) => ({
      cells: state.cells.map((c) => (c.id === id ? { ...c, ...patch } : c)),
    })),

  updateCellLayout: (id, layout) =>
    set((state) => ({
      cells: state.cells.map((c) => (c.id === id ? { ...c, layout } : c)),
    })),

  setCells: (cells) => set({ cells }),

  setSelectedCellId: (id) => set({ selectedCellId: id }),

  setMaximizedCellId: (id) => set({ maximizedCellId: id }),

  setSignals: (signals) => set({ signals }),

  addSignal: (signal) =>
    set((state) => {
      // 基于 id 去重，避免 WS 实时推送与 30s 轮询重复
      if (state.signals.some((s) => s.id === signal.id)) {
        return state
      }
      return { signals: [signal, ...state.signals].slice(0, 200) }
    }),

  setSignalPanelCollapsed: (collapsed) => set({ signalPanelCollapsed: collapsed }),

  setLatestMinuteBar: (update) => set({ latestMinuteBar: update }),
}))
