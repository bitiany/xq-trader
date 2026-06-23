import { Table } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import type { PositionRecord } from '@/api/backtest'

export interface PositionListTableProps {
  positions: PositionRecord[]
}

function fmtMoney(v: number | null | undefined) {
  if (v == null) return '—'
  return v.toLocaleString(undefined, { maximumFractionDigits: 2 })
}

function fmtPct(v: number | null | undefined) {
  if (v == null) return '—'
  return `${(v * 100).toFixed(2)}%`
}

function signedColor(v: number | null | undefined) {
  if (v == null) return undefined
  return v > 0 ? 'var(--color-rise)' : v < 0 ? 'var(--color-fall)' : undefined
}

export function PositionListTable({ positions }: PositionListTableProps) {
  const columns: ColumnsType<PositionRecord> = [
    { title: '日期', dataIndex: 'date', key: 'date', width: 110 },
    { title: '标的', dataIndex: 'symbol', key: 'symbol', width: 110 },
    {
      title: '持仓量',
      dataIndex: 'quantity',
      key: 'quantity',
      width: 100,
      render: (v: number) => Math.round(v).toLocaleString(),
    },
    {
      title: '成本价',
      dataIndex: 'avg_cost',
      key: 'avg_cost',
      width: 100,
      render: (v: number) => v.toFixed(2),
    },
    {
      title: '市值',
      dataIndex: 'market_value',
      key: 'market_value',
      width: 130,
      render: fmtMoney,
    },
    {
      title: '浮动盈亏',
      dataIndex: 'pnl',
      key: 'pnl',
      width: 120,
      render: (v: number) => <span style={{ color: signedColor(v) }}>{fmtMoney(v)}</span>,
    },
    {
      title: '盈亏率',
      dataIndex: 'pnl_pct',
      key: 'pnl_pct',
      width: 100,
      render: (v: number) => <span style={{ color: signedColor(v) }}>{fmtPct(v)}</span>,
    },
    {
      title: '组合权重',
      dataIndex: 'weight',
      key: 'weight',
      width: 100,
      render: fmtPct,
    },
  ]

  return (
    <Table<PositionRecord>
      dataSource={positions}
      columns={columns}
      rowKey={(r) => `${r.date}-${r.symbol}-${r.quantity}-${r.market_value}`}
      size="small"
      pagination={{ pageSize: 20, size: 'small', showSizeChanger: false }}
      scroll={{ x: 860, y: 400 }}
    />
  )
}
