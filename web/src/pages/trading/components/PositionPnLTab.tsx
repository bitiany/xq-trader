import { Table } from 'antd';
import { POSITIONS } from '../data/mock-trading';
import { PnlCalendar } from './PnlCalendar';

export function PositionPnLTab() {
  const columns = [
    { title: '代码', dataIndex: 'symbol', width: 90, render: (v: string) => <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 600 }}>{v}</span> },
    { title: '名称', dataIndex: 'name', width: 70 },
    {
      title: '目标权重', dataIndex: 'targetWeight', width: 75,
      render: (v: number) => <span style={{ fontFamily: 'var(--font-mono)' }}>{v}%</span>,
    },
    {
      title: '实际权重', dataIndex: 'actualWeight', width: 75,
      render: (v: number) => <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 500 }}>{v}%</span>,
    },
    {
      title: '偏离', dataIndex: 'deviation', width: 65,
      render: (v: number) => {
        const color = Math.abs(v) > 1 ? 'var(--color-warning)' : 'var(--text-secondary)';
        return <span style={{ color, fontFamily: 'var(--font-mono)', fontWeight: 600 }}>{v > 0 ? '+' : ''}{v}%</span>;
      },
    },
    { title: '成本', dataIndex: 'costPrice', width: 70, render: (v: number) => v.toFixed(2) },
    { title: '现价', dataIndex: 'lastPrice', width: 70, render: (v: number) => v.toFixed(2) },
    {
      title: '盈亏', dataIndex: 'pnl', width: 90,
      render: (v: number) => <span style={{ color: v > 0 ? 'var(--color-rise)' : 'var(--color-fall)', fontFamily: 'var(--font-mono)', fontWeight: 600 }}>{v > 0 ? '+' : ''}{v.toFixed(0)}</span>,
    },
    {
      title: '盈亏%', dataIndex: 'pnlPct', width: 65,
      render: (v: number) => <span style={{ color: v > 0 ? 'var(--color-rise)' : 'var(--color-fall)' }}>{v > 0 ? '+' : ''}{v.toFixed(2)}%</span>,
    },
  ];

  return (
    <div className="position-pnl-tab" data-component="Position & PnL Tab">
      <div className="position-pnl-tab__table">
        <Table
          dataSource={POSITIONS} columns={columns} rowKey="symbol" size="small" pagination={false}
          scroll={{ y: 300 }}
          rowClassName={(r) => Math.abs(r.deviation) > 1 ? 'position-row--deviated' : ''}
        />
      </div>
      <div className="position-pnl-tab__calendar">
        <PnlCalendar />
      </div>
    </div>
  );
}
