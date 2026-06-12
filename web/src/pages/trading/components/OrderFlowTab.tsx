import { Table, Tag } from 'antd';
import { ORDERS } from '../data/mock-trading';
import { STATUS_COLOR, STATUS_LABEL, SIDE_LABEL } from '../utils/trading';

export function OrderFlowTab() {
  const columns = [
    { title: '时间', dataIndex: 'time', width: 80 },
    { title: '代码', dataIndex: 'symbol', width: 90, render: (v: string) => <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 600 }}>{v}</span> },
    { title: '名称', dataIndex: 'name', width: 65, render: (v: string) => <span style={{ fontSize: 11, color: 'var(--text-secondary)' }}>{v}</span> },
    { title: '方向', dataIndex: 'side', width: 55, render: (v: 'buy' | 'sell') => <Tag color={v === 'buy' ? 'var(--color-rise)' : 'var(--color-fall)'} style={{ margin: 0 }}>{SIDE_LABEL[v]}</Tag> },
    { title: '数量', dataIndex: 'qty', width: 55, render: (v: number) => <span style={{ fontFamily: 'var(--font-mono)' }}>{v}</span> },
    { title: '价格', dataIndex: 'price', width: 75, render: (v: number) => <span style={{ fontFamily: 'var(--font-mono)' }}>{v.toFixed(2)}</span> },
    { title: '状态', dataIndex: 'status', width: 65, render: (v: 'filled' | 'partial_filled' | 'submitted' | 'rejected' | 'cancelled' | 'expired') => <Tag color={STATUS_COLOR[v]}>{STATUS_LABEL[v]}</Tag> },
    { title: '策略', dataIndex: 'strategy', width: 130, ellipsis: true },
  ];
  return (
    <div data-component="Order Flow Table">
      <Table
        dataSource={ORDERS} columns={columns} rowKey="id" size="small"
        pagination={{ pageSize: 10, size: 'small', showTotal: t => `共 ${t} 条` }}
        rowClassName={r => r.side === 'buy' ? 'order-row--buy' : 'order-row--sell'}
      />
    </div>
  );
}
