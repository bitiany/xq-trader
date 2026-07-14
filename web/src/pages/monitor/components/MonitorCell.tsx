import { useState, useEffect, useMemo, useRef, useCallback } from 'react'
import { Maximize2, Minimize2, X, ChevronDown } from 'lucide-react'
import { Dropdown, type MenuProps } from 'antd'
import { useMonitorStore, type MonitorCellConfig } from '../stores/monitorStore'
import { MiniKlineChart } from './MiniKlineChart'
import { minuteBarsToKline, dailyBarsToKline, aggregateMinuteBars, type KlineBar, type ChanlunData, type Td9Data } from '../utils/klineHelpers'
import type { IndicatorData } from '../utils/indicators'
import { buildSignalDesc } from '../utils/signalDesc'
import { fetchMinuteBars } from '@/api/intraday'
import { useStockQuote } from '@/hooks/useStockQuote'
import { request } from '@/api/client'
import '@/pages/monitor/styles/monitor.css'

// 将 QMT 时间戳转换为 { date: 'YYYY-MM-DD', time: 'HH:MM' }（Asia/Shanghai 时区）
function parseTradeTime(tradeTime: string): { date: string; time: string } | null {
  const n = Number(tradeTime)
  if (!Number.isFinite(n) || n <= 0) return null
  // QMT 时间戳可能为秒或毫秒
  const ms = n > 1e12 ? n : n * 1000
  const d = new Date(ms)
  const fmt = new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hour12: false,
  })
  const parts = fmt.formatToParts(d)
  const get = (t: string) => parts.find((p) => p.type === t)?.value ?? ''
  const date = `${get('year')}-${get('month')}-${get('day')}`
  const hh = get('hour')
  const mm = get('minute')
  // 处理凌晨 "24" 边界
  const hour = hh === '24' ? '00' : hh
  return { date, time: `${hour}:${mm}` }
}

const MAIN_INDICATOR_LABELS: Record<string, string> = {
  none: '无',
  vwap: '分时均线',
  ma: 'MA5/MA20',
  boll: '布林带',
  donchian: '唐奇安',
  chanlun: '缠论',
  td9: '神奇九转',
}

const MAIN_INDICATOR_SHORT: Record<string, string> = {
  none: '无',
  vwap: '均',
  ma: 'MA',
  boll: 'BOLL',
  donchian: 'DC',
  chanlun: '缠',
  td9: 'TD9',
}

const PERIOD_CONFIG: { key: MonitorCellConfig['period']; label: string }[] = [
  { key: '1m', label: '1m' },
  { key: '5m', label: '5m' },
  { key: '15m', label: '15m' },
  { key: 'daily', label: '日K' },
]

// 指标刷新节流间隔（毫秒）：WS minute_bar 推送新 bar 后触发指标重拉的最小间隔
// 60s 平衡实时性与请求开销：VWAP/TWAP 为累计型指标，1 分钟级别刷新已足够
const INDICATOR_REFRESH_INTERVAL_MS = 60_000

interface MonitorCellProps {
  cell: MonitorCellConfig
  isMaximized: boolean
}

export function MonitorCell({ cell, isMaximized }: MonitorCellProps) {
  const { id, symbol, period, mainIndicators } = cell
  const updateCell = useMonitorStore((s) => s.updateCell)
  const removeCell = useMonitorStore((s) => s.removeCell)
  const setMaximizedCellId = useMonitorStore((s) => s.setMaximizedCellId)
  const setSelectedCellId = useMonitorStore((s) => s.setSelectedCellId)
  const signals = useMonitorStore((s) => s.signals)

  const [rawMinuteBars, setRawMinuteBars] = useState<KlineBar[]>([])
  const [dailyBars, setDailyBars] = useState<KlineBar[]>([])
  const [chanlunData, setChanlunData] = useState<ChanlunData | null>(null)
  const [td9Data, setTd9Data] = useState<Td9Data | null>(null)
  const [indicatorData, setIndicatorData] = useState<IndicatorData | null>(null)
  const [loading, setLoading] = useState(false)

  // 实时价格：通过 WS 订阅 ws.market.stock_quotes.{symbol}（2s 推送）
  // 信号计算仍由后端 1m bar_ready 事件驱动，不受影响
  const { quote } = useStockQuote(symbol)
  const livePrice = useMemo(() => ({
    price: quote?.last ?? null,
    changePct: quote?.change_pct ?? null,
  }), [quote])

  // 加载K线数据（1m/5m/15m 共用原始 1m 数据）
  useEffect(() => {
    let cancelled = false
    const fetchData = async () => {
      setLoading(true)
      try {
        if (period === 'daily') {
          const resp = await request.get<{ bars: { trade_date: string; open: number; close: number; high: number; low: number; volume: number }[] }>(
            `/stocks/${symbol}/kline`,
            { params: { limit: 120 } },
          )
          if (!cancelled) {
            setDailyBars(dailyBarsToKline(resp.bars ?? []))
            setRawMinuteBars([])
          }
        } else {
          // 1m/5m/15m 都拉取 1m 原始数据，前端聚合
          // 1m 分时图：明确指定当天日期，盘前无数据时显示空图（不回退到前一交易日）
          //   当天最多 240 根（4h 交易），limit=240 足够
          // 5m: 1500 根（约 6 个交易日，聚合后 ~300 根，足够 MACD/BOLL warmup）
          // 15m: 3000 根（约 12 个交易日，聚合后 ~200 根，足够 MACD/BOLL warmup）
          // 业界主流：5m 默认显示近 5 日，15m 默认显示近 10 日
          if (period === '1m') {
            const today = new Date().toISOString().substring(0, 10)
            const resp = await fetchMinuteBars(symbol, today, 240)
            if (!cancelled) {
              setRawMinuteBars(minuteBarsToKline(resp.bars))
              setDailyBars([])
            }
          } else {
            const limit = period === '5m' ? 1500 : 3000
            const resp = await fetchMinuteBars(symbol, undefined, limit)
            if (!cancelled) {
              setRawMinuteBars(minuteBarsToKline(resp.bars))
              setDailyBars([])
            }
          }
        }
      } catch {
        if (!cancelled) {
          setRawMinuteBars([])
          setDailyBars([])
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    fetchData()
    return () => {
      cancelled = true
    }
  }, [symbol, period])

  // ── 盘中实时刷新机制 ───────────────────────────────────
  // minute_bar 由页面级（MonitorDashboardPage）统一订阅 WS，写入 store.latestMinuteBar
  // 本 cell 通过 selector 按 symbol 过滤消费，避免每个 cell 独立注册 handler
  // quote.last 变化时：通过 useMemo 派生 liveBars，仅更新最新一根 bar 的 close

  // 技术指标节流拉取：WS minute_bar 推送新 bar 后触发，60s 节流
  // 提前声明以供 minute_bar effect 和指标加载 effect 共用
  const lastIndicatorFetchTs = useRef(0)
  const fetchIndicators = useCallback(async () => {
    const now = Date.now()
    // 节流：距上次拉取不足 60s 则跳过（symbol/period 切换时强制立即拉取由 effect 控制）
    if (now - lastIndicatorFetchTs.current < INDICATOR_REFRESH_INTERVAL_MS) return
    lastIndicatorFetchTs.current = now
    try {
      const resp = await request.get<IndicatorData>(
        `/stocks/${symbol}/indicators`,
        { params: { period } },
      )
      setIndicatorData(resp)
    } catch {
      setIndicatorData(null)
    }
  }, [symbol, period])

  const latestMinuteBar = useMonitorStore((s) => s.latestMinuteBar)

  useEffect(() => {
    // 过滤非本 symbol 的 bar 更新
    if (!latestMinuteBar || latestMinuteBar.symbol !== symbol) return
    const parsed = parseTradeTime(latestMinuteBar.trade_time)
    if (!parsed) return
    const newBar: KlineBar = {
      time: parsed.time,
      date: parsed.date,
      open: latestMinuteBar.bar.open,
      high: latestMinuteBar.bar.high,
      low: latestMinuteBar.bar.low,
      close: latestMinuteBar.bar.close,
      volume: latestMinuteBar.bar.volume,
      amount: latestMinuteBar.bar.amount,
    }
    // eslint-disable-next-line react-hooks/set-state-in-effect -- 外部 store 变化同步到本地 state，属于合理用法
    setRawMinuteBars((prev) => {
      if (prev.length === 0) return [newBar]
      const last = prev[prev.length - 1]
      // 同一根 bar（相同 date+time）：替换为后端最终值
      if (last.date === newBar.date && last.time === newBar.time) {
        return [...prev.slice(0, -1), newBar]
      }
      // 新 bar：追加（避免重复）
      return [...prev, newBar]
    })
    // 新 bar 到达后节流重拉指标，保证 VWAP/TWAP 等累计型指标与 bars 长度对齐
    void fetchIndicators()
  }, [latestMinuteBar, symbol, fetchIndicators])

  // 实时价格：仅刷新最新一根 K 线的 close（含 high/low 极值同步）
  // 通过 useMemo 派生 liveBars，避免 useEffect 内 setState 引发级联渲染
  const livePriceValue = quote?.last ?? null
  const liveMinuteBars = useMemo(() => {
    if (livePriceValue === null || rawMinuteBars.length === 0) return rawMinuteBars
    const last = rawMinuteBars[rawMinuteBars.length - 1]
    const next: KlineBar = { ...last, close: livePriceValue }
    if (livePriceValue > next.high) next.high = livePriceValue
    if (livePriceValue < next.low) next.low = livePriceValue
    return [...rawMinuteBars.slice(0, -1), next]
  }, [rawMinuteBars, livePriceValue])

  const liveDailyBars = useMemo(() => {
    if (livePriceValue === null || dailyBars.length === 0) return dailyBars
    const last = dailyBars[dailyBars.length - 1]
    const next: KlineBar = { ...last, close: livePriceValue }
    if (livePriceValue > next.high) next.high = livePriceValue
    if (livePriceValue < next.low) next.low = livePriceValue
    return [...dailyBars.slice(0, -1), next]
  }, [dailyBars, livePriceValue])
  // ── 盘中实时刷新机制 END ───────────────────────────────

  // 加载缠论数据（仅 5m/15m/daily 且主图指标包含 chanlun 时）
  useEffect(() => {
    if (period === '1m' || !mainIndicators.includes('chanlun')) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setChanlunData(null)
      return
    }
    let cancelled = false
    const fetchChanlun = async () => {
      try {
        // display_limit 为前端实际展示的聚合后 bar 数量（非 1m 数量）
        // daily: 120 根日K；5m: 1500根1m/5=300 根 5m；15m: 3000根1m/15=200 根 15m
        // 后端内部加载更多历史数据计算缠论，offset 基于此值截取最近 N 根
        const displayLimit = period === 'daily' ? 120 : period === '5m' ? 300 : 200
        const resp = await request.get<ChanlunData>(
          `/stocks/${symbol}/chanlun`,
          { params: { period, display_limit: displayLimit } },
        )
        if (!cancelled) {
          setChanlunData(resp)
        }
      } catch {
        if (!cancelled) {
          setChanlunData(null)
        }
      }
    }
    fetchChanlun()
    return () => {
      cancelled = true
    }
  }, [symbol, period, mainIndicators])

  // 加载神奇九转数据（仅 5m/15m/daily 且主图指标包含 td9 时）
  useEffect(() => {
    if (period === '1m' || !mainIndicators.includes('td9')) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setTd9Data(null)
      return
    }
    let cancelled = false
    const fetchTd9 = async () => {
      try {
        const resp = await request.get<Td9Data>(
          `/stocks/${symbol}/td9`,
          { params: { period } },
        )
        if (!cancelled) {
          setTd9Data(resp)
        }
      } catch {
        if (!cancelled) {
          setTd9Data(null)
        }
      }
    }
    fetchTd9()
    return () => {
      cancelled = true
    }
  }, [symbol, period, mainIndicators])

  // 加载技术指标数据（MA/BOLL/Donchian/MACD/RSI/VWAP/TWAP，后端统一计算）
  // 指标刷新触发时机：
  //   1. cell 挂载或 symbol/period 切换时立即拉取（本 effect）
  //   2. WS minute_bar 推送新 bar 后节流重拉（fetchIndicators，已在前方声明）
  useEffect(() => {
    let cancelled = false
    const doFetch = async () => {
      // symbol/period 切换时重置节流时间戳，允许立即拉取
      lastIndicatorFetchTs.current = 0
      try {
        const resp = await request.get<IndicatorData>(
          `/stocks/${symbol}/indicators`,
          { params: { period } },
        )
        if (!cancelled) {
          setIndicatorData(resp)
          lastIndicatorFetchTs.current = Date.now()
        }
      } catch {
        if (!cancelled) {
          setIndicatorData(null)
        }
      }
    }
    doFetch()
    return () => {
      cancelled = true
    }
  }, [symbol, period])

  // 根据周期聚合分钟线
  // 1m 分时图：API 已按 trade_date=今天 过滤，直接使用；盘前无数据时为空数组（显示空图）
  // 5m/15m：保留多天数据，确保 MACD/RSI/布林带 warmup 充足
  // 使用 liveMinuteBars/liveDailyBars：实时价格已合并到最新一根 bar
  const bars = useMemo(() => {
    if (period === 'daily') return liveDailyBars
    if (period === '1m') return liveMinuteBars
    if (period === '5m') return aggregateMinuteBars(liveMinuteBars, 5)
    return aggregateMinuteBars(liveMinuteBars, 15)
  }, [period, liveMinuteBars, liveDailyBars])

  // 最新信号
  const latestSignal = signals.find((s) => s.symbol === symbol)

  // 该 symbol 的所有信号（用于分时图 markPoint 标记）
  const symbolSignals = useMemo(
    () => signals.filter((s) => s.symbol === symbol),
    [signals, symbol],
  )

  const priceClass =
    livePrice.changePct !== null && livePrice.changePct > 0
      ? 'monitor-cell__price--up'
      : livePrice.changePct !== null && livePrice.changePct < 0
        ? 'monitor-cell__price--down'
        : ''

  const formatPrice = (p: number | null) => (p !== null ? p.toFixed(2) : '—')
  const formatPct = (p: number | null) => {
    if (p === null) return ''
    const sign = p > 0 ? '+' : ''
    return `${sign}${p.toFixed(2)}%`
  }

  // 指标切换菜单（多选，支持缠论+神奇九转叠加）
  const mainMenuItems: MenuProps['items'] = Object.entries(MAIN_INDICATOR_LABELS).map(
    ([key, label]) => ({
      key,
      label: (
        <span style={{ color: mainIndicators.includes(key as MonitorCellConfig['mainIndicators'][number]) ? 'var(--accent-primary)' : undefined }}>
          {label}
        </span>
      ),
      onClick: () => {
        const ind = key as MonitorCellConfig['mainIndicators'][number]
        // 'none' 清空其他，选择其他时移除 'none'
        if (ind === 'none') {
          updateCell(id, { mainIndicators: [] })
          return
        }
        const current = mainIndicators.filter((m) => m !== 'none')
        const exists = current.includes(ind)
        const next = exists ? current.filter((m) => m !== ind) : [...current, ind]
        updateCell(id, { mainIndicators: next })
      },
    }),
  )

  // 当前指标显示文本
  const indicatorDisplayText = mainIndicators.length === 0
    ? '无'
    : isMaximized
      ? mainIndicators.map((m) => MAIN_INDICATOR_LABELS[m]).join('+')
      : mainIndicators.map((m) => MAIN_INDICATOR_SHORT[m]).join('+')

  return (
    <div
      className="monitor-cell"
      onClick={() => setSelectedCellId(id)}
      style={{ height: '100%' }}
    >
      <div className="monitor-cell__header">
        <span className="monitor-cell__symbol">{cell.name || symbol}</span>
        <span className="monitor-cell__code">{symbol}</span>
        {/* 最新价格：小窗模式仅显示价格，放大模式显示价格+涨跌幅，红涨绿跌 */}
        {livePrice.price !== null && (
          <>
            <span className={`monitor-cell__price ${priceClass}`} style={{ fontSize: 12 }}>
              {formatPrice(livePrice.price)}
            </span>
            {isMaximized && (
              <span className={`monitor-cell__price ${priceClass}`} style={{ fontSize: 11 }}>
                {formatPct(livePrice.changePct)}
              </span>
            )}
          </>
        )}
        <div className="monitor-cell__spacer" />
        {/* 周期切换 */}
        <div className="monitor-cell__segmented">
          {PERIOD_CONFIG.map((p) => (
            <button
              key={p.key}
              className={`monitor-cell__segmented-btn ${period === p.key ? 'monitor-cell__segmented-btn--active' : ''}`}
              onClick={() => {
                // 切换周期时设置默认主图指标：
                // - 1m 分时图：vwap（分时均线）
                // - 5m/15m/日K：缠论 + 神奇九转（叠加）
                const defaultIndicators = p.key === '1m'
                  ? ['vwap'] as const
                  : ['chanlun', 'td9'] as const
                updateCell(id, { period: p.key, mainIndicators: [...defaultIndicators] })
              }}
            >
              {p.label}
            </button>
          ))}
        </div>
        {/* 主图指标：1m 分时图模式显示静态标签，其他周期显示下拉菜单 */}
        {period === '1m' ? (
          <span className="monitor-cell__btn monitor-cell__btn--indicator" style={{ cursor: 'default' }} title="分时图：价格线 + 均价线">
            <span style={{ fontSize: 10, color: 'var(--accent-primary)' }}>分时</span>
          </span>
        ) : (
          <Dropdown menu={{ items: mainMenuItems }} trigger={['click']}>
            <button className="monitor-cell__btn monitor-cell__btn--indicator" title="主图指标（可多选）">
              <span style={{ fontSize: 10 }}>
                {indicatorDisplayText}
              </span>
              <ChevronDown size={10} />
            </button>
          </Dropdown>
        )}
        {/* 副图指标：成交量+MACD+RSI 始终全部展示，无需切换 */}
        {/* 放大/缩小 */}
        <button
          className="monitor-cell__btn"
          onClick={() => setMaximizedCellId(isMaximized ? null : id)}
          title={isMaximized ? '缩小' : '放大'}
        >
          {isMaximized ? <Minimize2 size={12} /> : <Maximize2 size={12} />}
        </button>
        {/* 关闭 */}
        <button
          className="monitor-cell__btn"
          onClick={() => removeCell(id)}
          title="移除"
        >
          <X size={12} />
        </button>
      </div>
      <div className="monitor-cell__chart">
        {loading ? (
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: 'var(--text-muted)', fontSize: 12 }}>
            加载中...
          </div>
        ) : bars.length > 0 ? (
          <MiniKlineChart
            symbol={symbol}
            bars={bars}
            mainIndicators={mainIndicators}
            isMaximized={isMaximized}
            period={period}
            chanlunData={chanlunData}
            td9Data={td9Data}
            indicatorData={indicatorData}
            signals={symbolSignals}
          />
        ) : (
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: 'var(--text-muted)', fontSize: 12 }}>
            暂无数据
          </div>
        )}
      </div>
      {latestSignal && (
        <div className="monitor-cell__footer">
          <span className="monitor-cell__signal-badge">
            {buildSignalDesc(latestSignal)}
          </span>
        </div>
      )}
    </div>
  )
}
