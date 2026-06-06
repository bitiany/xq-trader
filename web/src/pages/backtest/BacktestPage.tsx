import { useCallback, useEffect, useMemo, useState } from 'react'
import { useParams, useNavigate, useSearchParams } from 'react-router-dom'
import { Alert, Button, Card, Space, Spin, Table, Tabs, Tag, Tooltip, message } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { ArrowLeft, Play, TrendingUp, ListOrdered, Briefcase, BarChart3, ChevronLeft, ChevronRight } from 'lucide-react'
import dayjs from 'dayjs'
import {
  type BacktestStrategyInfo, type BacktestSizerInfo, type BacktestResultData,
  type BacktestEquityItem, type BacktestOrderItem, type BacktestPositionItem, type BacktestPerformance,
  runBacktest, fetchBacktestStrategies, fetchBacktestSizers,
  fetchBacktestEquity, fetchBacktestOrders, fetchBacktestPositions, fetchBacktestPerformance,
} from '@/api/backtest'
import type { KlineBarItem } from '@/api/stock'
import {
  KLineChart,
  EquityCurveChart,
  PerformanceGrid,
  BasicConfigPanel,
  StrategyModeSwitcher,
  BuiltinStrategyPicker,
  AlphaSignalSelector,
  RuleCombinationEditor,
  ExpressionStrategyEditor,
} from './components'
import type { BacktestConfig } from './types'
import { loadKlineData } from './utils'
import '@/styles/backtest.css'

export function BacktestPage() {
  const { symbol = '' } = useParams()
  const decodedSymbol = decodeURIComponent(symbol)
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()

  const initialStrategyId = useMemo(() => searchParams.get('strategy_id') ?? '', [searchParams])
  const initialSizerId = useMemo(() => searchParams.get('sizer_id') ?? '', [searchParams])

  const [strategies, setStrategies] = useState<BacktestStrategyInfo[]>([])
  const [sizers, setSizers] = useState<BacktestSizerInfo[]>([])

  const [config, setConfig] = useState<BacktestConfig>({
    initialCapital: 1000000,
    commissionRate: 0.0003,
    stampDuty: 0.001,
    startDate: dayjs().subtract(1, 'year'),
    endDate: dayjs(),
    benchmark: '000300',
    strategyMode: 'builtin',
    strategyId: initialStrategyId,
    sizerId: initialSizerId,
    sizerParams: {},
    alphaId: null,
    alphaBuyThreshold: 0.7,
    alphaSellThreshold: 0.3,
    ruleCombineConfig: {
      rules: [],
      buy_combinator: 'AND',
      sell_combinator: 'OR',
    },
  })

  const [running, setRunning] = useState(false)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const [result, setResult] = useState<BacktestResultData | null>(null)
  const [equity, setEquity] = useState<BacktestEquityItem[]>([])
  const [orders, setOrders] = useState<BacktestOrderItem[]>([])
  const [positions, setPositions] = useState<BacktestPositionItem[]>([])
  const [performance, setPerformance] = useState<BacktestPerformance | null>(null)
  const [klineBars, setKlineBars] = useState<KlineBarItem[]>([])
  const [chanlunData, setChanlunData] = useState<import('@/api/stock').ChanlunResponse | undefined>(undefined)
  const [errorMsg, setErrorMsg] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    Promise.all([fetchBacktestStrategies(), fetchBacktestSizers()])
      .then(([strats, szrs]) => {
        if (cancelled) return
        setStrategies(strats)
        setSizers(szrs)
      })
      .catch((err) => {
        console.error('[BacktestPage] Failed to load strategies/sizers:', err)
        message.error('加载策略或仓位管理列表失败')
      })
    return () => { cancelled = true }
  }, [])

  const handleConfigChange = useCallback(<K extends keyof BacktestConfig>(key: K, value: BacktestConfig[K]) => {
    setConfig((prev) => ({ ...prev, [key]: value }))
  }, [])

  const handleRun = useCallback(async () => {
    if (!decodedSymbol) {
      message.warning('缺少标的代码')
      return
    }
    if (config.strategyMode === 'builtin' && !config.strategyId) {
      message.warning('请选择回测策略')
      return
    }
    if (config.strategyMode === 'alpha' && !config.alphaId) {
      message.warning('请选择Alpha组合')
      return
    }
    if (config.strategyMode === 'rule_combine' && config.ruleCombineConfig.rules.length === 0) {
      message.warning('请至少添加一条因子规则')
      return
    }

    setRunning(true)
    setErrorMsg(null)
    setResult(null)
    setEquity([])
    setOrders([])
    setPositions([])
    setPerformance(null)
    setKlineBars([])

    try {
      const strategyParams: Record<string, unknown> = {}
      if (config.strategyMode === 'rule_combine') {
        strategyParams.rules = config.ruleCombineConfig.rules
        strategyParams.buy_combinator = config.ruleCombineConfig.buy_combinator
        strategyParams.sell_combinator = config.ruleCombineConfig.sell_combinator
      } else if (config.strategyMode === 'alpha') {
        strategyParams.alpha_id = config.alphaId
        strategyParams.buy_threshold = config.alphaBuyThreshold
        strategyParams.sell_threshold = config.alphaSellThreshold
      }
      const resp = await runBacktest({
        workspace_id: 'backtest_page',
        symbols: [decodedSymbol],
        strategy_id: config.strategyId,
        strategy_mode: config.strategyMode === 'alpha' ? 'alpha_combo' : config.strategyMode,
        strategy_params: strategyParams,
        sizer_id: config.sizerId || 'equal_weight',
        sizer_params: config.sizerParams,
        start_date: config.startDate.format('YYYY-MM-DD'),
        end_date: config.endDate.format('YYYY-MM-DD'),
        benchmark: config.benchmark,
        initial_capital: config.initialCapital,
        commission_rate: config.commissionRate,
        stamp_tax_rate: config.stampDuty,
      })
      setResult(resp)

      if (resp.execute_id) {
        const [eq, ord, pos, perf, klineData] = await Promise.all([
          fetchBacktestEquity(resp.execute_id, 1, 5000).catch(() => ({ total: 0, page: 1, page_size: 5000, items: [] })),
          fetchBacktestOrders(resp.execute_id, 1, 5000).catch(() => ({ total: 0, page: 1, page_size: 5000, items: [] })),
          fetchBacktestPositions(resp.execute_id, undefined, 1, 5000).catch(() => ({ total: 0, page: 1, page_size: 5000, items: [] })),
          fetchBacktestPerformance(resp.execute_id).catch(() => null),
          loadKlineData(decodedSymbol),
        ])
        setEquity(eq.items)
        setOrders(ord.items)
        setPositions(pos.items)
        setPerformance(perf)
        setKlineBars(klineData.klineBars)
        setChanlunData(klineData.chanlunData)
      }

      message.success('回测完成')
    } catch (err) {
      const m = err instanceof Error ? err.message : '回测执行失败'
      setErrorMsg(m)
      message.error(m)
    } finally {
      setRunning(false)
    }
  }, [decodedSymbol, config])

  const buySellPoints = useMemo(() => {
    const buyPoints: { date: string; price: number; low: number }[] = []
    const sellPoints: { date: string; price: number; high: number }[] = []
    const barMap = new Map<string, KlineBarItem>()
    for (const bar of klineBars) {
      barMap.set(bar.trade_date, bar)
    }
    for (const ord of orders) {
      const dt = ord.signal_date
      if (!dt) continue
      const bar = barMap.get(dt)
      if (ord.direction === 'BUY') {
        buyPoints.push({ date: dt, price: ord.price, low: bar?.low ?? ord.price })
      } else if (ord.direction === 'SELL') {
        sellPoints.push({ date: dt, price: ord.price, high: bar?.high ?? ord.price })
      }
    }
    return { buyPoints, sellPoints }
  }, [orders, klineBars])

  const orderColumns: ColumnsType<BacktestOrderItem> = useMemo(() => [
    {
      title: '日期',
      dataIndex: 'signal_date',
      width: 100,
      render: (v: string | null) => v ?? '—',
    },
    {
      title: '标的',
      dataIndex: 'symbol',
      width: 100,
    },
    {
      title: '方向',
      dataIndex: 'direction',
      width: 70,
      render: (v: string) => (
        <Tag color={v === 'BUY' ? '#e03e3e' : '#2eaa67'} style={{ margin: 0 }}>
          {v === 'BUY' ? '买入' : '卖出'}
        </Tag>
      ),
    },
    {
      title: '价格',
      dataIndex: 'price',
      width: 90,
      render: (v: number) => v.toFixed(2),
    },
    {
      title: '数量',
      dataIndex: 'amount',
      width: 80,
    },
    {
      title: '佣金',
      dataIndex: 'commission',
      width: 90,
      render: (v: number | null) => v?.toFixed(2) ?? '—',
    },
    {
      title: '信号依据',
      dataIndex: 'reason',
      width: 260,
      ellipsis: true,
      render: (v: string | null) => v ? (
        <Tooltip title={v}>
          <span style={{ fontSize: 12, color: 'var(--color-text-secondary)' }}>{v}</span>
        </Tooltip>
      ) : '—',
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 90,
      render: (v: string) => {
        const statusMap: Record<string, { label: string; color: string }> = {
          FILLED: { label: '已成交', color: 'success' },
          CANCELLED: { label: '已撤单', color: 'warning' },
          REJECTED: { label: '已拒绝', color: 'error' },
          PENDING: { label: '待成交', color: 'processing' },
        }
        const info = statusMap[v] ?? { label: v, color: 'default' }
        return <Tag color={info.color} style={{ margin: 0 }}>{info.label}</Tag>
      },
    },
  ], [])

  const positionColumns: ColumnsType<BacktestPositionItem> = useMemo(() => [
    { title: '日期', dataIndex: 'trade_date', width: 100 },
    { title: '标的', dataIndex: 'symbol', width: 100 },
    { title: '持仓量', dataIndex: 'amount', width: 80 },
    {
      title: '成本价',
      dataIndex: 'avg_cost',
      width: 90,
      render: (v: number) => v.toFixed(2),
    },
    {
      title: '市值',
      dataIndex: 'market_value',
      width: 110,
      render: (v: number | null) => v?.toFixed(2) ?? '—',
    },
    {
      title: '浮动盈亏',
      dataIndex: 'pnl',
      width: 110,
      render: (v: number | null) => {
        if (v == null) return '—'
        const color = v > 0 ? 'var(--color-rise)' : v < 0 ? 'var(--color-fall)' : undefined
        return <span style={{ color }}>{v.toFixed(2)}</span>
      },
    },
    {
      title: '盈亏%',
      dataIndex: 'pnl_pct',
      width: 90,
      render: (v: number | null) => {
        if (v == null) return '—'
        const pct = v * 100
        const color = pct > 0 ? 'var(--color-rise)' : pct < 0 ? 'var(--color-fall)' : undefined
        return <span style={{ color }}>{pct.toFixed(2)}%</span>
      },
    },
    {
      title: '权重',
      dataIndex: 'weight',
      width: 80,
      render: (v: number | null) => v != null ? `${(v * 100).toFixed(1)}%` : '—',
    },
  ], [])

  const strategyPanel = useMemo(() => {
    switch (config.strategyMode) {
      case 'builtin':
        return (
          <BuiltinStrategyPicker
            strategies={strategies}
            strategyId={config.strategyId}
            onStrategyChange={(id) => handleConfigChange('strategyId', id)}
          />
        )
      case 'rule_combine':
        return (
          <RuleCombinationEditor
            value={config.ruleCombineConfig}
            onChange={(rc) => handleConfigChange('ruleCombineConfig', rc)}
          />
        )
      case 'expression':
        return <ExpressionStrategyEditor />
      case 'alpha':
        return (
          <AlphaSignalSelector
            alphaId={config.alphaId}
            buyThreshold={config.alphaBuyThreshold}
            sellThreshold={config.alphaSellThreshold}
            onAlphaChange={(id) => handleConfigChange('alphaId', id)}
            onBuyThresholdChange={(v) => handleConfigChange('alphaBuyThreshold', v)}
            onSellThresholdChange={(v) => handleConfigChange('alphaSellThreshold', v)}
          />
        )
    }
  }, [config.strategyMode, config.strategyId, config.alphaId, config.alphaBuyThreshold, config.alphaSellThreshold, config.ruleCombineConfig, strategies, handleConfigChange])

  const canRun = config.strategyMode === 'builtin'
    ? !!config.strategyId && !!decodedSymbol
    : config.strategyMode === 'alpha'
      ? !!config.alphaId && !!decodedSymbol
      : config.strategyMode === 'rule_combine'
        ? config.ruleCombineConfig.rules.length > 0 && !!decodedSymbol
        : !!decodedSymbol

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
        <span className="backtest-page__title">{decodedSymbol} 回测</span>
      </div>

      <div className="backtest-page__content">
        {!sidebarCollapsed && (
          <div className="backtest-page__sidebar">
            <BasicConfigPanel
              symbol={decodedSymbol}
              config={config}
              sizers={sizers}
              onConfigChange={handleConfigChange}
            />

            <StrategyModeSwitcher
              value={config.strategyMode}
              onChange={(mode) => handleConfigChange('strategyMode', mode)}
            />

            {strategyPanel}

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
          {errorMsg && <Alert type="error" showIcon message={errorMsg} closable onClose={() => setErrorMsg(null)} />}

          {running && (
            <Card style={{ background: 'var(--bg-card)', textAlign: 'center', padding: 40 }}>
              <Spin size="large" />
              <p style={{ color: 'var(--text-muted)', marginTop: 16 }}>回测引擎运行中，请稍候...</p>
            </Card>
          )}

          {!running && !result && (
            <Card style={{ background: 'var(--bg-card)', textAlign: 'center', padding: 40 }}>
              <BarChart3 size={48} style={{ color: 'var(--text-muted)', marginBottom: 16 }} />
              <p style={{ color: 'var(--text-muted)' }}>配置参数后，点击"开始回测"</p>
            </Card>
          )}

          {!running && result && (
            <>
              <PerformanceGrid performance={performance} />

              <div className="backtest-page__chart card">
                <KLineChart
                  bars={klineBars}
                  buyPoints={buySellPoints.buyPoints}
                  sellPoints={buySellPoints.sellPoints}
                  startDate={config.startDate.format('YYYY-MM-DD')}
                  endDate={config.endDate.format('YYYY-MM-DD')}
                  chanlun={chanlunData}
                />
              </div>

              <Tabs
                className="backtest-page__tabs"
                items={[
                  {
                    key: 'equity',
                    label: <Space><TrendingUp size={14} />净值曲线</Space>,
                    children: (
                      <Card size="small" style={{ background: 'var(--bg-card)' }}>
                        <div style={{ height: 320 }}>
                          <EquityCurveChart data={equity} />
                        </div>
                      </Card>
                    ),
                  },
                  {
                    key: 'orders',
                    label: <Space><ListOrdered size={14} />委托记录 ({orders.length})</Space>,
                    children: (
                      <Card size="small" style={{ background: 'var(--bg-card)' }}>
                        <Table<BacktestOrderItem>
                          dataSource={orders}
                          columns={orderColumns}
                          rowKey="order_id"
                          size="small"
                          pagination={{ pageSize: 15, showTotal: (total) => `共 ${total} 条` }}
                          scroll={{ x: 640 }}
                        />
                      </Card>
                    ),
                  },
                  {
                    key: 'positions',
                    label: <Space><Briefcase size={14} />持仓快照 ({positions.length})</Space>,
                    children: (
                      <Card size="small" style={{ background: 'var(--bg-card)' }}>
                        <Table<BacktestPositionItem>
                          dataSource={positions}
                          columns={positionColumns}
                          rowKey={(r) => `${r.trade_date}-${r.symbol}`}
                          size="small"
                          pagination={{ pageSize: 15, showTotal: (total) => `共 ${total} 条` }}
                          scroll={{ x: 760 }}
                        />
                      </Card>
                    ),
                  },
                ]}
              />
            </>
          )}
        </div>
      </div>
    </div>
  )
}
