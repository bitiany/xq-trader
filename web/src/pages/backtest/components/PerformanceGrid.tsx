import { useMemo } from 'react'
import type { SimpleBacktestResponse } from '@/api/backtest'

function fmtPct(v: number | null | undefined, digits = 2) {
  if (v == null) return '—'
  const pct = v * 100
  return `${pct > 0 ? '+' : ''}${pct.toFixed(digits)}%`
}

function fmtPctColor(v: number | null | undefined) {
  if (v == null) return undefined
  const pct = v * 100
  return pct > 0 ? 'var(--color-rise)' : pct < 0 ? 'var(--color-fall)' : undefined
}

function fmtNum(v: number | null | undefined, digits = 4) {
  if (v == null) return '—'
  return v.toFixed(digits)
}

function metricVal(metrics: Record<string, unknown>, key: string): number | null {
  const v = metrics[key]
  return typeof v === 'number' ? v : null
}

export interface PerformanceGridProps {
  result: SimpleBacktestResponse | null
}

export function PerformanceGrid({ result }: PerformanceGridProps) {
  const cards = useMemo(() => {
    if (!result) return []
    const m = result.metrics
    return [
      { label: '总收益率', value: fmtPct(result.total_return), color: fmtPctColor(result.total_return) },
      { label: '年化收益率', value: fmtPct(result.annual_return), color: fmtPctColor(result.annual_return) },
      { label: '夏普比率', value: fmtNum(result.sharpe_ratio) },
      { label: '最大回撤', value: fmtPct(result.max_drawdown), color: fmtPctColor(-Math.abs(result.max_drawdown)) },
      { label: '总交易次数', value: String(result.total_trades) },
      { label: '胜率', value: fmtPct(metricVal(m, 'win_rate')), color: fmtPctColor(metricVal(m, 'win_rate')) },
      { label: '盈亏比', value: fmtNum(metricVal(m, 'profit_loss_ratio')) },
      { label: 'Sortino比率', value: fmtNum(metricVal(m, 'sortino_ratio')) },
      { label: '波动率', value: fmtPct(metricVal(m, 'volatility')) },
      { label: '换手率', value: fmtPct(metricVal(m, 'turnover_rate')) },
      { label: '最终资产', value: result.final_value.toLocaleString() },
      { label: '耗时', value: `${result.elapsed_ms}ms` },
    ]
  }, [result])

  if (cards.length === 0) return null

  return (
    <div className="backtest-page__metrics">
      {cards.map((card) => (
        <div key={card.label} className="backtest-metric">
          <div className="backtest-metric__label">{card.label}</div>
          <div className="backtest-metric__value" style={card.color ? { color: card.color } : undefined}>
            {card.value}
          </div>
        </div>
      ))}
    </div>
  )
}
