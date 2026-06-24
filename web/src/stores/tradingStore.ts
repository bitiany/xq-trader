import { create } from 'zustand'

import type { TradingPnlData } from '@/ws/protocol'
import type { KpiData } from '@/pages/trading/types'

// ── State ──

interface TradingState {
  /** 当前资产所属账户 */
  accountId: number | null
  /** KPI 数据（由 REST 初始加载填充，匹配账户的 WS 推送可更新） */
  kpi: KpiData
  /** WS 推送的原始资产数据 */
  pnlData: TradingPnlData | null
  /** 初始加载是否完成 */
  loaded: boolean

  /** 从 REST API 初始化基础资产数据 */
  initFromAsset: (accountId: number, asset: {
    cash: number
    frozen_cash: number
    market_value: number
    total_asset: number
    today_pnl?: number
    today_pnl_pct?: number
    cumulative_pnl?: number
    cumulative_pnl_pct?: number
  }) => void

  /** 从 WS 推送更新 KPI */
  updateFromPnl: (accountId: number, data: TradingPnlData) => void

  /** 重置指定账户资产 */
  reset: (accountId?: number | null) => void
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
  accountId: null,
  kpi: { ...INITIAL_KPI },
  pnlData: null,
  loaded: false,

  initFromAsset: (accountId, asset) =>
    set({
      accountId,
      loaded: true,
      pnlData: {
        account_id: accountId,
        cash: asset.cash,
        frozen_cash: asset.frozen_cash,
        market_value: asset.market_value,
        total_asset: asset.total_asset,
        today_pnl: asset.today_pnl ?? 0,
        today_pnl_pct: asset.today_pnl_pct ?? 0,
        timestamp: Date.now() / 1000,
      },
      kpi: {
        totalAsset: asset.total_asset,
        availableCash: asset.cash,
        marketValue: asset.market_value,
        todayPnl: asset.today_pnl ?? 0,
        todayPnlPct: asset.today_pnl_pct ?? 0,
        cumulativePnl: asset.cumulative_pnl ?? 0,
        cumulativePnlPct: asset.cumulative_pnl_pct ?? 0,
        maxDrawdownPct: 0,
      },
    }),

  updateFromPnl: (accountId, data) =>
    set((state) => {
      if (state.accountId !== accountId) {
        return state
      }
      return {
        pnlData: { ...data, account_id: accountId },
        kpi: {
          ...state.kpi,
          totalAsset: data.total_asset,
          availableCash: data.cash,
          marketValue: data.market_value,
          todayPnl: data.today_pnl ?? state.kpi.todayPnl,
          todayPnlPct: data.today_pnl_pct ?? state.kpi.todayPnlPct,
        },
      }
    }),

  reset: (accountId) =>
    set((state) => {
      if (accountId !== undefined && state.accountId !== accountId) {
        return state
      }
      return {
        accountId: null,
        kpi: { ...INITIAL_KPI },
        pnlData: null,
        loaded: false,
      }
    }),
}))
