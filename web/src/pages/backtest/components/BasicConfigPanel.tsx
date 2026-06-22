import { Card, DatePicker, InputNumber, Space } from 'antd'
import { Wallet, Settings2 } from 'lucide-react'
import type { BacktestConfig } from '../types'

export interface BasicConfigPanelProps {
  symbol: string
  config: BacktestConfig
  onConfigChange: <K extends keyof BacktestConfig>(key: K, value: BacktestConfig[K]) => void
}

export function BasicConfigPanel({ symbol, config, onConfigChange }: BasicConfigPanelProps) {
  return (
    <div className="backtest-page__basic-config">
      <Card size="small" style={{ background: 'var(--bg-card)' }}>
        <div className="backtest-page__symbol-bar">
          <Wallet size={18} />
          <span className="backtest-page__symbol">{symbol}</span>
        </div>
      </Card>

      <Card size="small" title={<Space><Wallet size={14} />资金账户</Space>} style={{ background: 'var(--bg-card)' }}>
        <div className="backtest-page__config-row">
          <div className="backtest-page__config-item">
            <label>初始资金</label>
            <InputNumber
              style={{ width: '100%' }}
              min={10000}
              step={100000}
              value={config.initialCapital}
              onChange={(v) => onConfigChange('initialCapital', v ?? 1000000)}
            />
          </div>
          <div className="backtest-page__config-item">
            <label>佣金费率</label>
            <InputNumber
              style={{ width: '100%' }}
              min={0}
              max={0.01}
              step={0.0001}
              precision={4}
              value={config.commissionRate}
              onChange={(v) => onConfigChange('commissionRate', v ?? 0.0003)}
            />
          </div>
          <div className="backtest-page__config-item">
            <label>滑点</label>
            <InputNumber
              style={{ width: '100%' }}
              min={0}
              max={0.01}
              step={0.0001}
              precision={4}
              value={config.slippage}
              onChange={(v) => onConfigChange('slippage', v ?? 0)}
            />
          </div>
        </div>
      </Card>

      <Card size="small" title={<Space><Settings2 size={14} />回测参数</Space>} style={{ background: 'var(--bg-card)' }}>
        <div className="backtest-page__config-row">
          <div className="backtest-page__config-item">
            <label>起始日期</label>
            <DatePicker
              style={{ width: '100%' }}
              value={config.startDate}
              onChange={(d) => d && onConfigChange('startDate', d)}
            />
          </div>
          <div className="backtest-page__config-item">
            <label>结束日期</label>
            <DatePicker
              style={{ width: '100%' }}
              value={config.endDate}
              onChange={(d) => d && onConfigChange('endDate', d)}
            />
          </div>
        </div>
      </Card>
    </div>
  )
}
