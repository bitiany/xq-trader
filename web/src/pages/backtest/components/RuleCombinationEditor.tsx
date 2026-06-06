import { useCallback, useMemo } from 'react'
import {
  Button, Card, Empty, InputNumber, Select, Space, Table, Tag,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { Plus, Trash2, Zap } from 'lucide-react'
import type { RuleCombineConfig } from '../types'

type Combinator = 'AND' | 'OR' | 'VOTING'

interface Rule {
  rule_id: string
  name: string
  buy_expr?: string
  sell_expr?: string
}

export interface RuleCombinationEditorProps {
  value: RuleCombineConfig
  onChange: (config: RuleCombineConfig) => void
}

const COMBINATOR_OPTIONS: { value: Combinator; label: string }[] = [
  { value: 'AND', label: 'AND (全部满足)' },
  { value: 'OR', label: 'OR (任一满足)' },
  { value: 'VOTING', label: 'VOTING (投票)' },
]

export function RuleCombinationEditor({ value, onChange }: RuleCombinationEditorProps) {
  const allRules: Rule[] = useMemo(() => [
    { rule_id: 'rule1', name: '动量规则', buy_expr: 'MOM > 0', sell_expr: 'MOM < 0' },
    { rule_id: 'rule2', name: '成交量规则', buy_expr: 'VOL > 100', sell_expr: 'VOL < 50' },
    { rule_id: 'rule3', name: '价格规则', buy_expr: 'CLOSE > MA5', sell_expr: 'CLOSE < MA10' }
  ], [])

  const ruleLookup = useMemo(() => {
    const map = new Map<string, Rule>()
    for (const r of allRules) map.set(r.rule_id, r)
    return map
  }, [allRules])

  const handleAddRule = useCallback((ruleId: string) => {
    if (value.rules.some((r) => r.rule_id === ruleId)) return
    onChange({ ...value, rules: [...value.rules, { rule_id: ruleId, weight: 1.0 }] })
  }, [value, onChange])

  const handleRemoveRule = useCallback((ruleId: string) => {
    onChange({ ...value, rules: value.rules.filter((r) => r.rule_id !== ruleId) })
  }, [value, onChange])

  const handleUpdateWeight = useCallback((ruleId: string, weight: number) => {
    onChange({
      ...value,
      rules: value.rules.map((r) => (r.rule_id === ruleId ? { ...r, weight } : r)),
    })
  }, [value, onChange])

  const handleBuyCombinatorChange = useCallback((buy_combinator: Combinator) => {
    onChange({ ...value, buy_combinator })
  }, [value, onChange])

  const handleSellCombinatorChange = useCallback((sell_combinator: Combinator) => {
    onChange({ ...value, sell_combinator })
  }, [value, onChange])

  const availableRules = useMemo(
    () => allRules.filter((r) => !value.rules.some((vr) => vr.rule_id === r.rule_id)),
    [allRules, value.rules],
  )

  const columns: ColumnsType<{ rule_id: string; weight: number }> = [
    {
      title: '因子规则',
      dataIndex: 'rule_id',
      render: (rid: string) => {
        const r = ruleLookup.get(rid)
        if (!r) return <span style={{ color: 'var(--color-text-muted)' }}>{rid}</span>
        return (
          <Space direction="vertical" size={0}>
            <span style={{ fontWeight: 500 }}>{r.name}</span>
            <Space size={4} wrap>
              {r.buy_expr && <Tag color="red" style={{ margin: 0, fontSize: 11 }}>买: {r.buy_expr}</Tag>}
              {r.sell_expr && <Tag color="green" style={{ margin: 0, fontSize: 11 }}>卖: {r.sell_expr}</Tag>}
            </Space>
          </Space>
        )
      },
    },
    {
      title: '权重',
      dataIndex: 'weight',
      width: 100,
      render: (w: number, record) => (
        <InputNumber
          value={w}
          step={0.1}
          min={0}
          max={10}
          size="small"
          onChange={(v) => typeof v === 'number' && handleUpdateWeight(record.rule_id, v)}
        />
      ),
    },
    {
      title: '',
      key: 'op',
      width: 40,
      render: (_, record) => (
        <Button
          type="text"
          danger
          size="small"
          icon={<Trash2 size={14} />}
          onClick={() => handleRemoveRule(record.rule_id)}
        />
      ),
    },
  ]

  return (
    <Card
      size="small"
      title={<Space><Zap size={14} />规则组合</Space>}
      style={{ background: 'var(--bg-card)' }}
    >
      <div style={{ marginBottom: 12 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
          <label style={{ fontSize: 12, color: 'var(--text-muted)' }}>因子规则 ({value.rules.length})</label>
          <Select
            placeholder="添加因子规则"
            value={undefined}
            onChange={(v) => { if (typeof v === 'string') handleAddRule(v) }}
            options={availableRules.map((r) => ({
              value: r.rule_id,
              label: `${r.name} — 买:${r.buy_expr ?? '—'} / 卖:${r.sell_expr ?? '—'}`,
            }))}
            showSearch
            optionFilterProp="label"
            style={{ width: 280 }}
            size="small"
            suffixIcon={<Plus size={12} />}
          />
        </div>
        {value.rules.length > 0 ? (
          <Table<{ rule_id: string; weight: number }>
            rowKey="rule_id"
            size="small"
            dataSource={value.rules}
            columns={columns}
            pagination={false}
          />
        ) : (
          <Empty description="暂无因子规则，请从上方添加" image={Empty.PRESENTED_IMAGE_SIMPLE} />
        )}
      </div>

      <div className="backtest-page__config-row">
        <div className="backtest-page__config-item">
          <label>买入信号组合</label>
          <Select
            style={{ width: '100%' }}
            value={value.buy_combinator}
            onChange={handleBuyCombinatorChange}
            options={COMBINATOR_OPTIONS}
          />
        </div>
        <div className="backtest-page__config-item">
          <label>卖出信号组合</label>
          <Select
            style={{ width: '100%' }}
            value={value.sell_combinator}
            onChange={handleSellCombinatorChange}
            options={COMBINATOR_OPTIONS}
          />
        </div>
      </div>
    </Card>
  )
}
