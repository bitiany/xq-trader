import { useState, useEffect, useMemo } from 'react'
import { Maximize2, Minimize2, X, ChevronDown } from 'lucide-react'
import { Dropdown, type MenuProps } from 'antd'
import { useMonitorStore, type MonitorCellConfig } from '../stores/monitorStore'
import { MiniKlineChart } from './MiniKlineChart'
import { minuteBarsToKline, dailyBarsToKline, aggregateMinuteBars, type KlineBar, type ChanlunData } from '../utils/klineHelpers'
import { fetchMinuteBars } from '@/api/intraday'
import { request } from '@/api/client'
import '@/pages/monitor/styles/monitor.css'

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

const SUB_INDICATOR_LABELS: Record<string, string> = {
  volume: '成交量',
  macd: 'MACD',
  rsi: 'RSI',
}

const SUB_INDICATOR_SHORT: Record<string, string> = {
  volume: '量',
  macd: 'MACD',
  rsi: 'RSI',
}

const PERIOD_CONFIG: { key: MonitorCellConfig['period']; label: string }[] = [
  { key: '1m', label: '1m' },
  { key: '5m', label: '5m' },
  { key: '15m', label: '15m' },
  { key: 'daily', label: '日K' },
]

interface MonitorCellProps {
  cell: MonitorCellConfig
  isMaximized: boolean
}

export function MonitorCell({ cell, isMaximized }: MonitorCellProps) {
  const { id, symbol, period, mainIndicator, subIndicator } = cell
  const updateCell = useMonitorStore((s) => s.updateCell)
  const removeCell = useMonitorStore((s) => s.removeCell)
  const setMaximizedCellId = useMonitorStore((s) => s.setMaximizedCellId)
  const setSelectedCellId = useMonitorStore((s) => s.setSelectedCellId)
  const signals = useMonitorStore((s) => s.signals)

  const [rawMinuteBars, setRawMinuteBars] = useState<KlineBar[]>([])
  const [dailyBars, setDailyBars] = useState<KlineBar[]>([])
  const [chanlunData, setChanlunData] = useState<ChanlunData | null>(null)
  const [livePrice, setLivePrice] = useState<{ price: number | null; changePct: number | null }>({
    price: null,
    changePct: null,
  })
  const [loading, setLoading] = useState(false)

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
          // 1m 扩到 400 根解决 MACD EMA warm-up（需 ~33 根）
          // 5m/15m 需要更多历史数据
          const limit = period === '1m' ? 400 : 2000
          const resp = await fetchMinuteBars(symbol, undefined, limit)
          if (!cancelled) {
            setRawMinuteBars(minuteBarsToKline(resp.bars))
            setDailyBars([])
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

  // 加载缠论数据（仅 5m/15m/daily 且主图指标为 chanlun 时）
  useEffect(() => {
    if (mainIndicator !== 'chanlun' || period === '1m') {
      setChanlunData(null)
      return
    }
    let cancelled = false
    const fetchChanlun = async () => {
      try {
        const resp = await request.get<ChanlunData>(
          `/stocks/${symbol}/chanlun`,
          { params: { period } },
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
  }, [symbol, period, mainIndicator])

  // 根据周期聚合分钟线
  const bars = useMemo(() => {
    if (period === 'daily') return dailyBars
    if (period === '5m') return aggregateMinuteBars(rawMinuteBars, 5)
    if (period === '15m') return aggregateMinuteBars(rawMinuteBars, 15)
    return rawMinuteBars
  }, [period, rawMinuteBars, dailyBars])

  // 实时行情（通过 REST 轮询，WS 将在 P1 替代）
  useEffect(() => {
    let cancelled = false
    const fetchQuote = async () => {
      try {
        const resp = await request.get<{ last: number | null; change_pct: number | null }>(
          `/stocks/${symbol}`,
        )
        if (!cancelled) {
          setLivePrice({ price: resp.last ?? null, changePct: resp.change_pct ?? null })
        }
      } catch {
        // 静默
      }
    }
    fetchQuote()
    const timer = setInterval(fetchQuote, 5000)
    return () => {
      cancelled = true
      clearInterval(timer)
    }
  }, [symbol])

  // 最新信号
  const latestSignal = signals.find((s) => s.symbol === symbol)

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
    return `${sign}${(p * 100).toFixed(2)}%`
  }

  // 指标切换菜单
  const mainMenuItems: MenuProps['items'] = Object.entries(MAIN_INDICATOR_LABELS).map(
    ([key, label]) => ({
      key,
      label: label,
      onClick: () => updateCell(id, { mainIndicator: key as MonitorCellConfig['mainIndicator'] }),
    }),
  )

  const subMenuItems: MenuProps['items'] = Object.entries(SUB_INDICATOR_LABELS).map(
    ([key, label]) => ({
      key,
      label: label,
      onClick: () => updateCell(id, { subIndicator: key as MonitorCellConfig['subIndicator'] }),
    }),
  )

  return (
    <div
      className="monitor-cell"
      onClick={() => setSelectedCellId(id)}
      style={{ height: '100%' }}
    >
      <div className="monitor-cell__header">
        <span className="monitor-cell__symbol">{symbol}</span>
        {/* 小窗模式隐藏价格，放大模式显示 */}
        {isMaximized && (
          <>
            <span className={`monitor-cell__price ${priceClass}`}>
              {formatPrice(livePrice.price)}
            </span>
            <span className={`monitor-cell__price ${priceClass}`} style={{ fontSize: 11 }}>
              {formatPct(livePrice.changePct)}
            </span>
          </>
        )}
        <div className="monitor-cell__spacer" />
        {/* 周期切换 */}
        <div className="monitor-cell__segmented">
          {PERIOD_CONFIG.map((p) => (
            <button
              key={p.key}
              className={`monitor-cell__segmented-btn ${period === p.key ? 'monitor-cell__segmented-btn--active' : ''}`}
              onClick={() => updateCell(id, { period: p.key })}
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
            <button className="monitor-cell__btn monitor-cell__btn--indicator" title="主图指标">
              <span style={{ fontSize: 10 }}>
                {isMaximized ? MAIN_INDICATOR_LABELS[mainIndicator] : MAIN_INDICATOR_SHORT[mainIndicator]}
              </span>
              <ChevronDown size={10} />
            </button>
          </Dropdown>
        )}
        {/* 副图指标：1m 分时图模式不显示 */}
        {period !== '1m' && (
          <Dropdown menu={{ items: subMenuItems }} trigger={['click']}>
            <button className="monitor-cell__btn monitor-cell__btn--indicator" title="副图指标">
              <span style={{ fontSize: 10 }}>
                {isMaximized ? SUB_INDICATOR_LABELS[subIndicator] : SUB_INDICATOR_SHORT[subIndicator]}
              </span>
              <ChevronDown size={10} />
            </button>
          </Dropdown>
        )}
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
            mainIndicator={mainIndicator}
            subIndicator={subIndicator}
            isMaximized={isMaximized}
            period={period}
            chanlunData={chanlunData}
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
            {latestSignal.signal_type ?? '信号'} {latestSignal.direction}
          </span>
        </div>
      )}
    </div>
  )
}
