import { Card, Select, Space } from 'antd'
import { TrendingUp } from 'lucide-react'
import type { BacktestStrategyInfo } from '@/api/backtest'

export interface BuiltinStrategyPickerProps {
  strategies: BacktestStrategyInfo[]
  strategyId: string
  onStrategyChange: (id: string) => void
}

export function BuiltinStrategyPicker({
  strategies,
  strategyId,
  onStrategyChange,
}: BuiltinStrategyPickerProps) {
  return (
    <Card
      size="small"
      title={<Space><TrendingUp size={14} />策略选择</Space>}
      style={{ background: 'var(--bg-card)' }}
    >
      <div className="backtest-page__config-item">
        <label>回测策略</label>
        <Select
          style={{ width: '100%' }}
          placeholder="选择策略"
          value={strategyId || undefined}
          onChange={onStrategyChange}
          options={strategies.map((s) => ({ value: s.strategy_id, label: s.name }))}
        />
      </div>
    </Card>
  )
}
