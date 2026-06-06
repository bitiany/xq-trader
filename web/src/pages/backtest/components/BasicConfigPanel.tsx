import { useMemo } from 'react'
import { Card, DatePicker, InputNumber, Select, Space, Switch } from 'antd'
import { Wallet, Settings2, Briefcase } from 'lucide-react'
import type { BacktestConfig } from '../types'
import { BENCHMARK_OPTIONS } from '../types'
import type { BacktestSizerInfo } from '@/api/backtest'

export interface BasicConfigPanelProps {
  symbol: string
  config: BacktestConfig
  sizers: BacktestSizerInfo[]
  onConfigChange: <K extends keyof BacktestConfig>(key: K, value: BacktestConfig[K]) => void
}

interface ParamFieldProps {
  name: string
  schema: Record<string, unknown>
  value: unknown
  onChange: (v: unknown) => void
}

function ParamField({ name, schema, value, onChange }: ParamFieldProps) {
  const type = (schema.type as string) || 'string'
  const desc = (schema.description as string) || name
  const defaultValue = schema.default

  if (type === 'float' || type === 'int') {
    const isFloat = type === 'float'
    const min = schema.min != null ? Number(schema.min) : 0
    const max = schema.max != null ? Number(schema.max) : isFloat ? 1 : 1000
    const step = isFloat ? 0.01 : 1
    const precision = isFloat ? 2 : 0
    const displayValue = value != null ? Number(value) : defaultValue != null ? Number(defaultValue) : isFloat ? 0.1 : 10

    return (
      <div className="backtest-page__config-item">
        <label>{desc}</label>
        <InputNumber
          style={{ width: '100%' }}
          min={min}
          max={max}
          step={step}
          precision={precision}
          value={displayValue}
          onChange={(v) => onChange(v)}
        />
      </div>
    )
  }

  if (type === 'bool') {
    const checked = value != null ? Boolean(value) : defaultValue != null ? Boolean(defaultValue) : false
    return (
      <div className="backtest-page__config-item" style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' }}>
        <label style={{ marginBottom: 0 }}>{desc}</label>
        <Switch size="small" checked={checked} onChange={(v) => onChange(v)} />
      </div>
    )
  }

  return (
    <div className="backtest-page__config-item">
      <label>{desc}</label>
      <Select
        style={{ width: '100%' }}
        value={value != null ? String(value) : defaultValue != null ? String(defaultValue) : undefined}
        onChange={(v) => onChange(v)}
        options={[]}
      />
    </div>
  )
}

export function BasicConfigPanel({ symbol, config, sizers, onConfigChange }: BasicConfigPanelProps) {
  const currentSizer = useMemo(
    () => sizers.find((s) => s.sizer_id === config.sizerId),
    [sizers, config.sizerId],
  )

  const paramsSchema = useMemo(() => {
    if (!currentSizer?.params_schema) return {} as Record<string, Record<string, unknown>>
    return currentSizer.params_schema as Record<string, Record<string, unknown>>
  }, [currentSizer])

  const handleSizerParamChange = (paramName: string, paramValue: unknown) => {
    onConfigChange('sizerParams', { ...config.sizerParams, [paramName]: paramValue })
  }

  const handleSizerChange = (sizerId: string) => {
    onConfigChange('sizerId', sizerId)
    const target = sizers.find((s) => s.sizer_id === sizerId)
    const defaults: Record<string, unknown> = {}
    if (target?.params_schema) {
      const schema = target.params_schema as Record<string, Record<string, unknown>>
      for (const [key, field] of Object.entries(schema)) {
        if (field.default != null) defaults[key] = field.default
      }
    }
    onConfigChange('sizerParams', defaults)
  }

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
            <label>印花税率</label>
            <InputNumber
              style={{ width: '100%' }}
              min={0}
              max={0.01}
              step={0.0001}
              precision={4}
              value={config.stampDuty}
              onChange={(v) => onConfigChange('stampDuty', v ?? 0.001)}
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
          <div className="backtest-page__config-item">
            <label>基准指数</label>
            <Select
              style={{ width: '100%' }}
              value={config.benchmark}
              onChange={(v) => onConfigChange('benchmark', v)}
              options={BENCHMARK_OPTIONS}
            />
          </div>
        </div>
      </Card>

      <Card size="small" title={<Space><Briefcase size={14} />仓位管理</Space>} style={{ background: 'var(--bg-card)' }}>
        <div className="backtest-page__config-item" style={{ marginBottom: Object.keys(paramsSchema).length > 0 ? 12 : 0 }}>
          <label>仓位策略</label>
          <Select
            style={{ width: '100%' }}
            placeholder="选择仓位策略"
            value={config.sizerId || undefined}
            onChange={handleSizerChange}
            options={sizers.map((s) => ({ value: s.sizer_id, label: s.name }))}
          />
        </div>
        {Object.keys(paramsSchema).length > 0 && (
          <div className="backtest-page__config-row" style={{ flexWrap: 'wrap' }}>
            {Object.entries(paramsSchema).map(([paramName, fieldSchema]) => (
              <ParamField
                key={paramName}
                name={paramName}
                schema={fieldSchema}
                value={config.sizerParams[paramName]}
                onChange={(v) => handleSizerParamChange(paramName, v)}
              />
            ))}
          </div>
        )}
      </Card>
    </div>
  )
}
