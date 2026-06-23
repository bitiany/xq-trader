import { useMemo } from 'react'
import type { BacktestSymbolMetrics } from '@/api/backtest'

function fmtValue(v: number | string | null | undefined, digits = 4) {
  if (v == null) return '\u2014'
  if (typeof v === 'string') return v
  return v.toFixed(digits)
}

function fmtMoney(v: number | null | undefined) {
  if (v == null) return '\u2014'
  return v.toLocaleString(undefined, { maximumFractionDigits: 2 })
}

function fmtColor(v: number | string | null | undefined) {
  if (v == null) return undefined
  const n = typeof v === 'string' ? Number(v.replace('%', '')) : v
  if (Number.isNaN(n)) return undefined
  return n > 0 ? 'var(--color-rise)' : n < 0 ? 'var(--color-fall)' : undefined
}

export interface PerformanceGridProps {
  metrics: BacktestSymbolMetrics | null
}

export function PerformanceGrid({ metrics }: PerformanceGridProps) {
  const cards = useMemo(() => {
    if (!metrics) return []
    return [
      { label: '\u521d\u59cb\u8d44\u91d1', value: fmtMoney(metrics.initial_cash) },
      { label: '\u6700\u7ec8\u8d44\u4ea7', value: fmtMoney(metrics.final_value) },
      { label: '\u603b\u6536\u76ca\u7387', value: fmtValue(metrics.total_return), color: fmtColor(metrics.total_return) },
      { label: '\u65e5\u5747\u6536\u76ca\u7387', value: fmtValue(metrics.avg_daily_return), color: fmtColor(metrics.avg_daily_return) },
      { label: '\u6700\u5927\u56de\u64a4', value: fmtValue(metrics.max_drawdown), color: fmtColor(metrics.max_drawdown) },
      { label: '\u590f\u666e\u6bd4\u7387', value: fmtValue(metrics.sharpe_ratio) },
      { label: '\u603b\u4ea4\u6613\u6b21\u6570', value: fmtValue(metrics.num_trades ?? metrics.total_trades, 0) },
      { label: '\u80dc\u7387', value: fmtValue(metrics.win_rate), color: fmtColor(metrics.win_rate) },
      { label: '\u76c8\u4e8f\u6bd4', value: fmtValue(metrics.profit_loss_ratio as number | string | undefined) },
      { label: 'SQN', value: fmtValue(metrics.sqn as number | string | undefined) },
    ]
  }, [metrics])

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
