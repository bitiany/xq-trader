import { Segmented } from 'antd'
import type { StrategyMode } from '../types'
import { STRATEGY_MODE_OPTIONS } from '../types'

export interface StrategyModeSwitcherProps {
  value: StrategyMode
  onChange: (mode: StrategyMode) => void
}

export function StrategyModeSwitcher({ value, onChange }: StrategyModeSwitcherProps) {
  return (
    <div className="backtest-page__mode-switcher">
      <Segmented
        value={value}
        onChange={(v) => onChange(v as StrategyMode)}
        options={STRATEGY_MODE_OPTIONS.map((opt) => ({
          value: opt.value,
          label: opt.label,
        }))}
        block
      />
    </div>
  )
}
