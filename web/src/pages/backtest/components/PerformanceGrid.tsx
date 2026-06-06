import { useMemo } from 'react'
import type { BacktestPerformance } from '@/api/backtest'

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

export interface PerformanceGridProps {
  performance: BacktestPerformance | null
}

export function PerformanceGrid({ performance }: PerformanceGridProps) {
  const cards = useMemo(() => {
    if (!performance) return []
    return [
      { label: '总收益率', value: fmtPct(performance.total_return), color: fmtPctColor(performance.total_return) },
      { label: '基准收益', value: fmtPct(performance.benchmark_total_return), color: fmtPctColor(performance.benchmark_total_return) },
      { label: '年化收益率', value: fmtPct(performance.annualized_return), color: fmtPctColor(performance.annualized_return) },
      { label: '夏普比率', value: fmtNum(performance.sharpe_ratio) },
      { label: '最大回撤', value: fmtPct(performance.max_drawdown), color: fmtPctColor(-Math.abs(performance.max_drawdown ?? 0)) },
      { label: '胜率', value: fmtPct(performance.win_rate) },
      { label: '盈亏比', value: fmtNum(performance.profit_loss_ratio) },
      { label: '总交易次数', value: performance.total_trades != null ? String(performance.total_trades) : '—' },
      { label: 'Alpha', value: fmtPct(performance.alpha), color: fmtPctColor(performance.alpha) },
      { label: 'Beta', value: fmtNum(performance.beta) },
      { label: '波动率', value: fmtPct(performance.volatility) },
      { label: '换手率', value: fmtPct(performance.turnover_rate) },
    ]
  }, [performance])

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
