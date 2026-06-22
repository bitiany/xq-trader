import { useCallback, useEffect, useMemo, useState } from 'react'
import { useParams, useNavigate, useSearchParams } from 'react-router-dom'
import { Alert, Button, Card, Input, Space, Spin, message } from 'antd'
import { ArrowLeft, Play, TrendingUp, BarChart3, ChevronLeft, ChevronRight, FileText } from 'lucide-react'
import dayjs from 'dayjs'
import {
  type BacktestStrategyInfo,
  type SimpleBacktestResponse,
  fetchBacktestStrategies,
  runSimpleBacktest,
} from '@/api/backtest'
import {
  EquityCurveChart,
  PerformanceGrid,
  BasicConfigPanel,
  BuiltinStrategyPicker,
  DailyReturnsChart,
} from './components'
import type { BacktestConfig } from './types'
import '@/styles/backtest.css'

export function BacktestPage() {
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
    slippage: 0,
    startDate: dayjs().subtract(1, 'year'),
    endDate: dayjs(),
    strategyId: initialStrategyId,
  })

  const [running, setRunning] = useState(false)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const [result, setResult] = useState<SimpleBacktestResponse | null>(null)
  const [errorMsg, setErrorMsg] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    fetchBacktestStrategies()
      .then((strats) => {
        if (cancelled) return
        setStrategies(strats)
      })
      .catch((err) => {
        console.error('[BacktestPage] Failed to load strategies:', err)
        message.error('加载策略列表失败')
      })
    return () => { cancelled = true }
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
        initial_capital: config.initialCapital,
        commission_rate: config.commissionRate,
        slippage: config.slippage,
        generate_report: true,
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
  }, [activeSymbol, config])

  const canRun = !!config.strategyId && !!activeSymbol

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
              <PerformanceGrid result={result} />

              <div className="backtest-page__chart card">
                <Card size="small" title={<Space><TrendingUp size={14} />净值曲线</Space>} style={{ background: 'var(--bg-card)' }}>
                  <div style={{ height: 320 }}>
                    <EquityCurveChart data={result.equity_curve} />
                  </div>
                </Card>
              </div>

              {result.daily_returns.length > 0 && (
                <div className="backtest-page__chart card" style={{ marginTop: 12 }}>
                  <Card size="small" title={<Space><BarChart3 size={14} />日收益率</Space>} style={{ background: 'var(--bg-card)' }}>
                    <div style={{ height: 240 }}>
                      <DailyReturnsChart data={result.daily_returns} />
                    </div>
                  </Card>
                </div>
              )}

              {result.html_report_path && (
                <Card size="small" style={{ background: 'var(--bg-card)', marginTop: 12 }}>
                  <Button
                    type="link"
                    icon={<FileText size={14} />}
                    href={result.html_report_path}
                    target="_blank"
                  >
                    查看详细报告
                  </Button>
                </Card>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  )
}
