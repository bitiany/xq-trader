import { Card, Select, Space, Tag } from 'antd'
import { TrendingUp } from 'lucide-react'
import type { BacktestStrategyInfo } from '@/api/backtest'

export interface BuiltinStrategyPickerProps {
  strategies: BacktestStrategyInfo[]
  strategyId: string
  onStrategyChange: (id: string) => void
  strategyType?: string
}

export function BuiltinStrategyPicker({
  strategies,
  strategyId,
  onStrategyChange,
  strategyType,
}: BuiltinStrategyPickerProps) {
  const filtered = strategyType
    ? strategies.filter((s) => s.strategy_type === strategyType)
    : strategies

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
          options={filtered.map((s) => ({
            value: s.strategy_id,
            label: (
              <Space>
                <span>{s.name}</span>
                <Tag color={s.strategy_type === 'timing' ? 'blue' : 'default'}>
                  {s.strategy_type === 'timing' ? '时序' : '截面'}
                </Tag>
              </Space>
            ),
          }))}
        />
      </div>
    </Card>
  )
}
