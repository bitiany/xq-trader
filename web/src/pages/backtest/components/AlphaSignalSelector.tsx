import { useCallback, useMemo } from 'react'
import { Card, InputNumber, Select, Space, Empty } from 'antd'
import { Zap } from 'lucide-react'

export interface AlphaSignalSelectorProps {
  alphaId: string | null
  buyThreshold: number
  sellThreshold: number
  onAlphaChange: (alphaId: string | null) => void
  onBuyThresholdChange: (v: number) => void
  onSellThresholdChange: (v: number) => void
}

export function AlphaSignalSelector({
  alphaId,
  buyThreshold,
  sellThreshold,
  onAlphaChange,
  onBuyThresholdChange,
  onSellThresholdChange,
}: AlphaSignalSelectorProps) {
  const items = useMemo(() => [
    { alpha_id: 'sample1', name: 'Sample Alpha 1', synthesize_method: 'Linear', sample_pool: 'A', rebalance_freq: 'D', factors: [{ factor_id: 'MOM' }, { factor_id: 'VOL' }] },
    { alpha_id: 'sample2', name: 'Sample Alpha 2', synthesize_method: 'Rank', sample_pool: 'B', rebalance_freq: 'W', factors: [{ factor_id: 'REV' }, { factor_id: 'LIQ' }] }
  ], [])

  const selected = useMemo(
    () => items.find((it) => it.alpha_id === alphaId) ?? null,
    [items, alphaId],
  )

  const handleSelect = useCallback(
    (value: string | undefined) => {
      onAlphaChange(value ?? null)
    },
    [onAlphaChange],
  )

  return (
    <Card
      size="small"
      title={<Space><Zap size={14} />Alpha信号</Space>}
      style={{ background: 'var(--bg-card)' }}
    >
      <div className="backtest-page__config-item" style={{ marginBottom: 12 }}>
        <label>选择Alpha组合</label>
        <Select
          style={{ width: '100%' }}
          placeholder="选择Alpha组合"
          value={alphaId ?? undefined}
          onChange={handleSelect}
          options={items.map((it) => ({
            value: it.alpha_id,
            label: `${it.name} (${it.synthesize_method})`,
          }))}
          showSearch
          optionFilterProp="label"
        />
      </div>

      {selected && (
        <div className="backtest-page__config-row" style={{ marginTop: 12 }}>
          <div className="backtest-page__config-item">
            <label>买入阈值</label>
            <InputNumber
              style={{ width: '100%' }}
              min={0}
              max={1}
              step={0.05}
              precision={2}
              value={buyThreshold}
              onChange={(v) => onBuyThresholdChange(v ?? 0.7)}
            />
          </div>
          <div className="backtest-page__config-item">
            <label>卖出阈值</label>
            <InputNumber
              style={{ width: '100%' }}
              min={0}
              max={1}
              step={0.05}
              precision={2}
              value={sellThreshold}
              onChange={(v) => onSellThresholdChange(v ?? 0.3)}
            />
          </div>
        </div>
      )}
    </Card>
  )
}
