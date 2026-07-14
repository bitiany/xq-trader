import { useEffect, useState, useCallback } from 'react'
import { useMonitorStore, type MinuteBarUpdate } from './stores/monitorStore'
import { useMonitorLayout } from './hooks/useMonitorLayout'
import { ScreenHeader } from './components/ScreenHeader'
import { StockPoolSidebar } from './components/StockPoolSidebar'
import { MonitorGrid } from './components/MonitorGrid'
import { SignalStreamPanel } from './components/SignalStreamPanel'
import { fetchIntradayStatus, fetchIntradaySignals, fetchDynamicPool } from '@/api/intraday'
import { request } from '@/api/client'
import { usePageWebSocket } from '@/ws/usePageWebSocket'
import { TOPIC_INTRADAY_SIGNAL, type IntradaySignalData } from '@/ws/protocol'
import { isAshareTradingSession } from '@/utils/tradingSession'
import '@/pages/monitor/styles/monitor.css'

interface AccountInfo {
  id: number
  account_type: string
}

export function MonitorDashboardPage() {
  useMonitorLayout()

  const setSignals = useMonitorStore((s) => s.setSignals)
  const addSignal = useMonitorStore((s) => s.addSignal)
  const [monitoring, setMonitoring] = useState(false)
  const [poolCount, setPoolCount] = useState(0)
  const [watchlistItems, setWatchlistItems] = useState<{ symbol: string; name?: string }[]>([])
  const [positionSymbols, setPositionSymbols] = useState<{ symbol: string; name?: string }[]>([])

  // 加载监控状态
  const loadStatus = useCallback(async () => {
    try {
      const resp = await fetchIntradayStatus()
      setMonitoring(resp.monitoring)
    } catch (e) {
      console.warn('加载盘内监控状态失败', e)
      setMonitoring(false)
    }
  }, [])

  // 加载股票池
  const loadPool = useCallback(async () => {
    try {
      const resp = await fetchDynamicPool()
      setPoolCount(resp.count)
    } catch (e) {
      console.warn('加载动态股票池失败', e)
      setPoolCount(0)
    }
  }, [])

  // 加载动态股票池（自选+持仓去重，由后端聚合，含标的名称）
  // 使用 /intraday/pool 接口，避免 watchlist API 跨 schema 查询问题
  const loadWatchlist = useCallback(async () => {
    try {
      const resp = await fetchDynamicPool()
      setWatchlistItems(resp.items.map((it) => ({ symbol: it.symbol, name: it.name })))
    } catch (e) {
      console.warn('加载自选股列表失败', e)
      setWatchlistItems([])
    }
  }, [])

  // 加载所有账户的持仓（合并去重）
  const loadPositions = useCallback(async () => {
    try {
      const accountsResp = await request.get<{ items: AccountInfo[] }>('/trading/accounts')
      const accounts = accountsResp.items ?? []
      if (accounts.length === 0) return

      // 并发加载所有账户的持仓
      const responses = await Promise.all(
        accounts.map((acc) =>
          request.get<{ items: { symbol: string; name?: string }[] }>(
            '/trading/positions',
            { params: { account_id: acc.id } },
          ).catch((e: unknown) => {
            console.warn(`加载账户 ${acc.id} 持仓失败`, e)
            return null
          }),
        ),
      )
      const seen = new Set<string>()
      const merged: { symbol: string; name?: string }[] = []
      for (const resp of responses) {
        if (!resp?.items) continue
        for (const p of resp.items) {
          if (!seen.has(p.symbol)) {
            seen.add(p.symbol)
            merged.push({ symbol: p.symbol, name: p.name })
          }
        }
      }
      setPositionSymbols(merged)
    } catch {
      // 加载持仓列表失败时不阻塞页面，静默处理
    }
  }, [])

  // 加载信号
  // trade_time 直接使用后端返回的 ISO 字符串（Shanghai 时区，由 signal_engine 注入 raw_values 并由 API 提取到顶层）
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
          raw_values: s.raw_values,
          // 后端返回的 trade_time 已是 Shanghai 时区 ISO 字符串
          trade_time: s.trade_time,
        })),
      )
    } catch {
      // 加载盘内信号列表失败时不阻塞页面，静默处理
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

  // 订阅盘内分时信号 WS topic，实时接收信号推送
  // data.trade_time 为后端 signal_engine 推送的 Shanghai 时区 ISO 字符串
  const handleSignalUpdate = useCallback(
    (_topic: string, data: IntradaySignalData) => {
      if (!data || typeof data.id !== 'number') return
      addSignal({
        id: data.id,
        symbol: data.symbol,
        name: data.name,
        direction: data.direction,
        strength: data.strength,
        signal_type: data.signal_type,
        signal_source: data.signal_source,
        created_at: data.created_at ?? new Date().toISOString(),
        trade_time: data.trade_time ?? null,
        raw_values: data.raw_values ?? null,
        resonance: data.resonance ?? null,
      })
    },
    [addSignal],
  )

  usePageWebSocket<IntradaySignalData>({
    topics: [TOPIC_INTRADAY_SIGNAL],
    onUpdate: handleSignalUpdate,
  })

  // 页面级统一订阅 ws.intraday.minute_bar（全局 topic，所有 symbol 的 bar 都推送至此）
  // 收到后写入 store，各 MonitorCell 通过 selector 按自己的 symbol 过滤消费
  // 避免每个 cell 独立注册 handler 导致的 N 次无效调用
  const setLatestMinuteBar = useMonitorStore((s) => s.setLatestMinuteBar)
  const minuteBarWsEnabled = isAshareTradingSession()
  const handleMinuteBarUpdate = useCallback((_topic: string, data: Omit<MinuteBarUpdate, 'ts'>) => {
    if (!data || !data.symbol) return
    setLatestMinuteBar({ ...data, ts: Date.now() })
  }, [setLatestMinuteBar])

  usePageWebSocket<Omit<MinuteBarUpdate, 'ts'>>({
    topics: minuteBarWsEnabled ? ['ws.intraday.minute_bar'] : [],
    enabled: minuteBarWsEnabled,
    onSnapshot: handleMinuteBarUpdate,
    onUpdate: handleMinuteBarUpdate,
  })

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
