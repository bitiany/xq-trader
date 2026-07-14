import { useCallback, useEffect, useMemo, useState } from 'react'
import { useParams, useNavigate, useSearchParams } from 'react-router-dom'
import { Alert, App, Button, Card, Input, Space, Spin, Tabs } from 'antd'
import { ArrowLeft, Play, TrendingUp, ListOrdered, Briefcase, ChevronLeft, ChevronRight } from 'lucide-react'
import dayjs from 'dayjs'
import {
  type BacktestStrategyInfo,
  type BacktestSymbolMetrics,
  type SimpleBacktestResponse,
  fetchBacktestStrategies,
  runSimpleBacktest,
} from '@/api/backtest'
import type { MainIndicator, SubIndicator } from '@/api/stock'
import { StockKlineChart, type StockKlineTradeMarker } from '@/components/stock/StockKlineChart'
import { useStockKline } from '@/hooks/useStockKline'
import {
  EquityCurveChart,
  PerformanceGrid,
  BasicConfigPanel,
  BuiltinStrategyPicker,
  TradeListTable,
  PositionListTable,
} from './components'
import type { BacktestConfig } from './types'
import '@/styles/backtest.css'

let strategiesRequest: Promise<BacktestStrategyInfo[]> | null = null

function loadBacktestStrategiesOnce() {
  strategiesRequest ??= fetchBacktestStrategies()
  return strategiesRequest
}

function toNumber(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) return value
  if (typeof value !== 'string') return null
  const normalized = value.trim()
  if (!normalized || normalized === 'N/A') return null
  const parsed = Number(normalized.replace('%', ''))
  if (!Number.isFinite(parsed)) return null
  return normalized.includes('%') ? parsed / 100 : parsed
}

function fmtAttributionValue(value: unknown, format: 'pct' | 'num' | 'int' | 'money') {
  const n = toNumber(value)
  if (n == null) return '—'
  if (format === 'pct') return `${(n * 100).toFixed(2)}%`
  if (format === 'int') return `${Math.round(n)}`
  if (format === 'money') return n.toLocaleString(undefined, { maximumFractionDigits: 2 })
  return n.toFixed(4)
}

function calcEquityStats(metrics: BacktestSymbolMetrics) {
  const curve = metrics.equity_curve ?? []
  if (curve.length < 2) return { bestDay: null as number | null, worstDay: null as number | null, positiveDays: 0, negativeDays: 0 }
  const returns: number[] = []
  for (let i = 1; i < curve.length; i++) {
    const prev = curve[i - 1].value
    const curr = curve[i].value
    if (prev > 0) returns.push((curr - prev) / prev)
  }
  return {
    bestDay: returns.length ? Math.max(...returns) : null,
    worstDay: returns.length ? Math.min(...returns) : null,
    positiveDays: returns.filter((v) => v > 0).length,
    negativeDays: returns.filter((v) => v < 0).length,
  }
}

function AttributionPanel({ metrics }: { metrics: BacktestSymbolMetrics }) {
  const trades = metrics.trades ?? []
  const positions = metrics.positions ?? []
  const buyTrades = trades.filter((t) => t.direction === 'buy')
  const sellTrades = trades.filter((t) => t.direction === 'sell')
  const equityStats = calcEquityStats(metrics)
  const latestPosition = positions[positions.length - 1]

  const sections = [
    {
      title: '收益分解',
      items: [
        { label: '初始资金', value: metrics.initial_cash, format: 'money' as const },
        { label: '最终资产', value: metrics.final_value, format: 'money' as const },
        { label: '总收益率', value: metrics.total_return, format: 'pct' as const },
        { label: '日均收益率', value: metrics.avg_daily_return, format: 'pct' as const },
        { label: '最佳单日', value: equityStats.bestDay, format: 'pct' as const },
        { label: '最差单日', value: equityStats.worstDay, format: 'pct' as const },
      ],
    },
    {
      title: '风险分析',
      items: [
        { label: '最大回撤', value: metrics.max_drawdown, format: 'pct' as const },
        { label: '最大回撤周期', value: metrics.max_dd_length, format: 'int' as const },
        { label: '夏普比率', value: metrics.sharpe_ratio, format: 'num' as const },
        { label: 'SQN', value: metrics.sqn, format: 'num' as const },
        { label: '上涨天数', value: equityStats.positiveDays, format: 'int' as const },
        { label: '下跌天数', value: equityStats.negativeDays, format: 'int' as const },
      ],
    },
    {
      title: '交易分析',
      items: [
        { label: '总交易次数', value: metrics.num_trades ?? metrics.total_trades, format: 'int' as const },
        { label: '买入次数', value: buyTrades.length, format: 'int' as const },
        { label: '卖出次数', value: sellTrades.length, format: 'int' as const },
        { label: '胜率', value: metrics.win_rate, format: 'pct' as const },
        { label: '盈亏比', value: metrics.profit_loss_ratio, format: 'num' as const },
        { label: '最新持仓权重', value: latestPosition?.weight, format: 'pct' as const },
      ],
    },
  ]

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {sections.map((section) => (
        <div key={section.title}>
          <div style={{ fontWeight: 600, marginBottom: 8, fontSize: 13, color: 'var(--text-secondary)' }}>
            {section.title}
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: 8 }}>
            {section.items.map((item) => (
              <div key={item.label} style={{ padding: '6px 10px', background: 'var(--bg-secondary)', borderRadius: 4 }}>
                <div style={{ color: 'var(--text-muted)', fontSize: 11 }}>{item.label}</div>
                <div style={{ fontSize: 14, fontWeight: 600, marginTop: 2 }}>
                  {fmtAttributionValue(item.value, item.format)}
                </div>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}

export function BacktestPage() {
  const { message } = App.useApp()
  const { symbol: urlSymbol = '' } = useParams()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()

  const initialStrategyId = useMemo(() => searchParams.get('strategy_id') ?? '', [searchParams])

  const [strategies, setStrategies] = useState<BacktestStrategyInfo[]>([])
  const [symbolInput, setSymbolInput] = useState(urlSymbol ? decodeURIComponent(urlSymbol) : '')

  const activeSymbol = urlSymbol ? decodeURIComponent(urlSymbol) : symbolInput.trim()

  const [config, setConfig] = useState<BacktestConfig>({
    initialCapital: 1000000,
    commissionRate: 0.0003,
    startDate: dayjs().subtract(1, 'year'),
    endDate: dayjs(),
    strategyId: initialStrategyId,
  })

  const [running, setRunning] = useState(false)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const [result, setResult] = useState<SimpleBacktestResponse | null>(null)
  const [errorMsg, setErrorMsg] = useState<string | null>(null)
  const [mainIndicator, setMainIndicator] = useState<MainIndicator>('ma')
  const [subIndicator, setSubIndicator] = useState<SubIndicator>('macd')

  const {
    bars: stockBars,
    maOverlays,
    allOverlays,
    chanlun,
    chanlunLoading,
    loading: klineLoading,
  } = useStockKline(activeSymbol, mainIndicator, subIndicator)

  useEffect(() => {
    let cancelled = false
    loadBacktestStrategiesOnce()
      .then((strats) => {
        if (cancelled) return
        setStrategies(strats)
        const defaultStrategy = strats[0]
        if (defaultStrategy) {
          setConfig((prev) => (prev.strategyId ? prev : { ...prev, strategyId: defaultStrategy.strategy_id }))
        }
      })
      .catch((err) => {
        strategiesRequest = null
        if (cancelled) return
        console.error('[BacktestPage] Failed to load strategies:', err)
        message.error('加载策略列表失败')
      })
    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- message 为 antd 稳定引用
  }, [])

  const handleConfigChange = useCallback(<K extends keyof BacktestConfig>(key: K, value: BacktestConfig[K]) => {
    setConfig((prev) => ({ ...prev, [key]: value }))
  }, [])

  const handleRun = useCallback(async () => {
    if (!activeSymbol) {
      message.warning('请输入标的代码')
      return
    }
    if (!config.strategyId) {
      message.warning('请选择回测策略')
      return
    }

    setRunning(true)
    setErrorMsg(null)
    setResult(null)

    try {
      const resp = await runSimpleBacktest({
        strategy_id: config.strategyId,
        symbols: [activeSymbol],
        start_date: config.startDate.format('YYYY-MM-DD'),
        end_date: config.endDate.format('YYYY-MM-DD'),
        initial_cash: config.initialCapital,
        commission: config.commissionRate,
      })
      setResult(resp)
      message.success('回测完成')
    } catch (err) {
      const m = err instanceof Error ? err.message : '回测执行失败'
      setErrorMsg(m)
      message.error(m)
    } finally {
      setRunning(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- message 为 antd 稳定引用
  }, [activeSymbol, config])

  const canRun = !!config.strategyId && !!activeSymbol

  const activeMetrics = useMemo(() => {
    if (!result) return null
    return result.metrics_per_symbol[activeSymbol] ?? Object.values(result.metrics_per_symbol)[0] ?? null
  }, [activeSymbol, result])

  const mainIndicatorOptions = useMemo(
    () => (['ma', 'boll', 'chanlun'] as MainIndicator[]).map((value) => ({ label: value.toUpperCase(), value })),
    [],
  )

  const subIndicatorOptions = useMemo(
    () => (['macd', 'kdj', 'rsi', 'bias', 'adx'] as SubIndicator[]).map((value) => ({ label: value.toUpperCase(), value })),
    [],
  )

  const tradeMarkers = useMemo<StockKlineTradeMarker[]>(() => (
    activeMetrics?.trades?.map((trade) => ({
      date: trade.date,
      direction: trade.direction,
      price: trade.price,
      quantity: trade.quantity,
    })) ?? []
  ), [activeMetrics])

  const pageTitle = activeSymbol ? `${activeSymbol} 回测` : '单标的回测'

  return (
    <div className="backtest-page">
      <div className="backtest-page__header">
        <button
          type="button"
          className="backtest-page__back"
          onClick={() => navigate(-1)}
          aria-label="返回"
        >
          <ArrowLeft size={18} />
        </button>
        <span className="backtest-page__title">{pageTitle}</span>
      </div>

      <div className="backtest-page__content">
        {!sidebarCollapsed && (
          <div className="backtest-page__sidebar">
            {!urlSymbol && (
              <Card size="small" style={{ background: 'var(--bg-card)' }}>
                <div className="backtest-page__config-item">
                  <label>标的代码</label>
                  <Input
                    placeholder="如 600519.SH"
                    value={symbolInput}
                    onChange={(e) => setSymbolInput(e.target.value)}
                    onPressEnter={() => canRun && handleRun()}
                  />
                </div>
              </Card>
            )}

            <BasicConfigPanel
              symbol={activeSymbol}
              config={config}
              onConfigChange={handleConfigChange}
            />

            <BuiltinStrategyPicker
              strategies={strategies}
              strategyId={config.strategyId}
              onStrategyChange={(id) => handleConfigChange('strategyId', id)}
              strategyType="timing"
            />

            <Button
              type="primary"
              size="large"
              icon={<Play size={16} />}
              loading={running}
              disabled={!canRun}
              onClick={handleRun}
              block
            >
              {running ? '回测运行中...' : '开始回测'}
            </Button>
          </div>
        )}

        <button
          type="button"
          className="backtest-page__sidebar-toggle"
          onClick={() => setSidebarCollapsed(!sidebarCollapsed)}
          aria-label={sidebarCollapsed ? '展开侧栏' : '收起侧栏'}
        >
          {sidebarCollapsed ? <ChevronRight size={14} /> : <ChevronLeft size={14} />}
        </button>

        <div className="backtest-page__main">
          {errorMsg && <Alert type="error" showIcon title={errorMsg} closable onClose={() => setErrorMsg(null)} />}

          {running && (
            <Card style={{ background: 'var(--bg-card)', textAlign: 'center', padding: 40 }}>
              <Spin size="large" />
              <p style={{ color: 'var(--text-muted)', marginTop: 16 }}>回测引擎运行中，请稍候...</p>
            </Card>
          )}

          {!running && !result && (
            <Card style={{ background: 'var(--bg-card)', textAlign: 'center', padding: 40 }}>
              <TrendingUp size={48} style={{ color: 'var(--text-muted)', marginBottom: 16 }} />
              <p style={{ color: 'var(--text-muted)' }}>配置参数后，点击"开始回测"</p>
            </Card>
          )}

          {!running && result && (
            <>
              <PerformanceGrid metrics={activeMetrics} />

              <div className="backtest-page__chart card" style={{ marginTop: 12 }}>
                <Card size="small" title={<Space><TrendingUp size={14} />K线与交易信号</Space>} style={{ background: 'var(--bg-card)' }}>
                  <StockKlineChart
                    bars={stockBars}
                    mainIndicator={mainIndicator}
                    subIndicator={subIndicator}
                    mainIndicatorOptions={mainIndicatorOptions}
                    subIndicatorOptions={subIndicatorOptions}
                    onMainIndicatorChange={setMainIndicator}
                    onSubIndicatorChange={setSubIndicator}
                    allOverlays={allOverlays}
                    maOverlays={maOverlays}
                    chanlun={chanlun ?? undefined}
                    tradeMarkers={tradeMarkers}
                    loading={klineLoading || chanlunLoading}
                  />
                </Card>
              </div>

              <div className="backtest-page__chart card" style={{ marginTop: 12 }}>
                <Card size="small" style={{ background: 'var(--bg-card)' }}>
                  <Tabs
                    defaultActiveKey="equity"
                    items={[
                      {
                        key: 'equity',
                        label: <Space><TrendingUp size={14} />净值曲线</Space>,
                        children: (
                          <div style={{ height: 320 }}>
                            <EquityCurveChart data={activeMetrics?.equity_curve ?? []} />
                          </div>
                        ),
                      },
                      {
                        key: 'trades',
                        label: <Space><ListOrdered size={14} />交易记录 ({activeMetrics?.trades?.length ?? 0})</Space>,
                        children: <TradeListTable trades={activeMetrics?.trades ?? []} />,
                      },
                      {
                        key: 'positions',
                        label: <Space><Briefcase size={14} />持仓快照 ({activeMetrics?.positions?.length ?? 0})</Space>,
                        children: <PositionListTable positions={activeMetrics?.positions ?? []} />,
                      },
                      {
                        key: 'attribution',
                        label: '归因分析',
                        children: activeMetrics ? <AttributionPanel metrics={activeMetrics} /> : null,
                      },
                    ]}
                  />
                </Card>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
