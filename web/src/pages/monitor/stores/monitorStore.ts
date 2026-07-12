import { create } from 'zustand'

export type ChartPeriod = '1m' | '5m' | '15m' | 'daily'

export type MainIndicator = 'none' | 'vwap' | 'ma' | 'boll' | 'donchian' | 'chanlun' | 'td9'
export type SubIndicator = 'volume' | 'macd' | 'rsi'

export interface MonitorCellConfig {
  id: string
  symbol: string
  name: string
  period: ChartPeriod
  mainIndicator: MainIndicator
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
        mainIndicator: 'vwap',
        subIndicator: 'volume',
        layout: { x, y, w, h },
      }
      return { cells: [...state.cells, newCell] }
    }),

  removeCell: (id) =>
    set((state) => ({
      cells: state.cells.filter((c) => c.id !== id),
      maximizedCellId: state.maximizedCellId === id ? null : state.maximizedCellId,
      selectedCellId: state.selectedCellId === id ? null : state.selectedCellId,
    })),

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
    set((state) => ({
      signals: [signal, ...state.signals].slice(0, 200),
    })),

  setSignalPanelCollapsed: (collapsed) => set({ signalPanelCollapsed: collapsed }),
}))
