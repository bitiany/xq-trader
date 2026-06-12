import { create } from 'zustand'

import type { TradingPnlData } from '@/ws/protocol'
import type { KpiData } from '@/pages/trading/types'

// ── State ──

interface TradingState {
  /** KPI 数据（由 WS 推送 + REST 初始加载填充） */
  kpi: KpiData
  /** WS 推送的原始资产数据 */
  pnlData: TradingPnlData | null
  /** 初始加载是否完成 */
  loaded: boolean

  /** 从 REST API 初始化基础资产数据 */
  initFromAsset: (asset: {
    cash: number
    frozen_cash: number
    market_value: number
    total_asset: number
  }) => void

  /** 从 WS 推送更新 KPI */
  updateFromPnl: (data: TradingPnlData) => void

  /** 重置（WS 断开时） */
  reset: () => void
}

const INITIAL_KPI: KpiData = {
  totalAsset: 0,
  availableCash: 0,
  marketValue: 0,
  todayPnl: 0,
  todayPnlPct: 0,
  cumulativePnl: 0,
  cumulativePnlPct: 0,
  maxDrawdownPct: 0,
}

export const useTradingStore = create<TradingState>((set) => ({
  kpi: { ...INITIAL_KPI },
  pnlData: null,
  loaded: false,

  initFromAsset: (asset) =>
    set((state) => ({
      loaded: true,
      pnlData: {
        cash: asset.cash,
        frozen_cash: asset.frozen_cash,
        market_value: asset.market_value,
        total_asset: asset.total_asset,
        timestamp: Date.now() / 1000,
      },
      kpi: {
        ...state.kpi,
        totalAsset: asset.total_asset,
        availableCash: asset.cash,
        marketValue: asset.market_value,
      },
    })),

  updateFromPnl: (data) =>
    set((state) => ({
      pnlData: data,
      kpi: {
        ...state.kpi,
        totalAsset: data.total_asset,
        availableCash: data.cash,
        marketValue: data.market_value,
        todayPnl: data.today_pnl ?? state.kpi.todayPnl,
        todayPnlPct: data.today_pnl_pct ?? state.kpi.todayPnlPct,
      },
    })),

  reset: () =>
    set({
      kpi: { ...INITIAL_KPI },
      pnlData: null,
      loaded: false,
    }),
}))
