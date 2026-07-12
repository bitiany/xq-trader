import { useEffect, useState, useCallback } from 'react'
import { useMonitorStore } from './stores/monitorStore'
import { useMonitorLayout } from './hooks/useMonitorLayout'
import { ScreenHeader } from './components/ScreenHeader'
import { StockPoolSidebar } from './components/StockPoolSidebar'
import { MonitorGrid } from './components/MonitorGrid'
import { SignalStreamPanel } from './components/SignalStreamPanel'
import { fetchIntradayStatus, fetchIntradaySignals, fetchDynamicPool } from '@/api/intraday'
import { fetchWatchlist, type WatchlistItem } from '@/api/trading'
import { request } from '@/api/client'
import '@/pages/monitor/styles/monitor.css'

export function MonitorDashboardPage() {
  useMonitorLayout()

  const setSignals = useMonitorStore((s) => s.setSignals)
  const [monitoring, setMonitoring] = useState(false)
  const [poolCount, setPoolCount] = useState(0)
  const [watchlistItems, setWatchlistItems] = useState<WatchlistItem[]>([])
  const [positionSymbols, setPositionSymbols] = useState<{ symbol: string; name?: string }[]>([])

  // 加载监控状态
  const loadStatus = useCallback(async () => {
    try {
      const resp = await fetchIntradayStatus()
      setMonitoring(resp.monitoring)
    } catch {
      setMonitoring(false)
    }
  }, [])

  // 加载股票池
  const loadPool = useCallback(async () => {
    try {
      const resp = await fetchDynamicPool()
      setPoolCount(resp.count)
    } catch {
      setPoolCount(0)
    }
  }, [])

  // 加载自选池（取第一个账户的自选池）
  const loadWatchlist = useCallback(async () => {
    try {
      // 获取账户列表
      const accountsResp = await request.get<{ items: { id: number; account_type: string }[] }>('/trading/accounts')
      const accounts = accountsResp.items ?? []
      if (accounts.length === 0) return

      // 取第一个账户的自选池
      const accountId = accounts[0].id
      const resp = await fetchWatchlist(accountId)
      setWatchlistItems(resp.items ?? [])
    } catch {
      // 静默
    }
  }, [])

  // 加载持仓
  const loadPositions = useCallback(async () => {
    try {
      const accountsResp = await request.get<{ items: { id: number }[] }>('/trading/accounts')
      const accounts = accountsResp.items ?? []
      if (accounts.length === 0) return

      const accountId = accounts[0].id
      const resp = await request.get<{ items: { symbol: string; name?: string }[] }>(
        '/trading/positions',
        { params: { account_id: accountId } },
      )
      const positions = (resp.items ?? []).map((p) => ({
        symbol: p.symbol,
        name: p.name,
      }))
      // 去重
      const seen = new Set<string>()
      const unique = positions.filter((p) => {
        if (seen.has(p.symbol)) return false
        seen.add(p.symbol)
        return true
      })
      setPositionSymbols(unique)
    } catch {
      // 静默
    }
  }, [])

  // 加载信号
  const loadSignals = useCallback(async () => {
    try {
      const now = new Date()
      const today = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
      const resp = await fetchIntradaySignals({ trade_date: today, page_size: 100 })
      setSignals(
        resp.items.map((s) => ({
          id: s.id,
          symbol: s.symbol,
          name: s.name,
          direction: s.direction,
          strength: s.strength,
          signal_type: s.signal_type,
          signal_source: s.signal_source,
          created_at: s.created_at,
        })),
      )
    } catch {
      // 静默
    }
  }, [setSignals])

  useEffect(() => {
    // 包装为本地函数避免 linter 追踪 useCallback 的 setState 调用
    const refresh = () => {
      void loadStatus()
      void loadPool()
      void loadWatchlist()
      void loadPositions()
      void loadSignals()
    }
    refresh()
    // 30s 刷新信号和状态
    const timer = setInterval(refresh, 30000)
    return () => clearInterval(timer)
  }, [loadStatus, loadPool, loadWatchlist, loadPositions, loadSignals])

  return (
    <div className="monitor-dashboard">
      <ScreenHeader monitoring={monitoring} poolCount={poolCount} />
      <div className="monitor-body">
        <StockPoolSidebar watchlistItems={watchlistItems} positionSymbols={positionSymbols} />
        <MonitorGrid />
      </div>
      <SignalStreamPanel />
    </div>
  )
}
