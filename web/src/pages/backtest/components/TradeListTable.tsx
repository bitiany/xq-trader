import { Table, Tag } from 'antd'
import type { TradeRecord } from '@/api/backtest'

export interface TradeListTableProps {
  trades: TradeRecord[]
}

export function TradeListTable({ trades }: TradeListTableProps) {
  const columns = [
    {
      title: '日期',
      dataIndex: 'date',
      key: 'date',
      width: 110,
    },
    {
      title: '标的',
      dataIndex: 'symbol',
      key: 'symbol',
      width: 100,
    },
    {
      title: '方向',
      dataIndex: 'direction',
      key: 'direction',
      width: 70,
      render: (dir: string) => (
        <Tag color={dir === 'buy' ? 'green' : 'red'}>
          {dir === 'buy' ? '买入' : '卖出'}
        </Tag>
      ),
    },
    {
      title: '价格',
      dataIndex: 'price',
      key: 'price',
      width: 90,
      render: (v: number) => v.toFixed(2),
    },
    {
      title: '数量',
      dataIndex: 'quantity',
      key: 'quantity',
      width: 90,
      render: (v: number) => Math.round(v),
    },
    {
      title: '金额',
      dataIndex: 'value',
      key: 'value',
      width: 110,
      render: (v: number) => v.toLocaleString(undefined, { maximumFractionDigits: 0 }),
    },
    {
      title: '信号依据',
      dataIndex: 'signal_reason',
      key: 'signal_reason',
      ellipsis: true,
    },
  ]

  return (
    <Table
      dataSource={trades}
      columns={columns}
      rowKey={(r) => `${r.date}-${r.symbol}-${r.direction}-${r.price}`}
      size="small"
      pagination={{ pageSize: 20, size: 'small', showSizeChanger: false }}
      scroll={{ y: 400 }}
    />
  )
}
