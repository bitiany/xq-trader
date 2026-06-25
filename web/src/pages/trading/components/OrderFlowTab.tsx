import { useEffect, useMemo, useState } from 'react';
import { Table, Tag, message } from 'antd';
import { fetchOrders, type TradingOrder } from '@/api/trading';
import { STATUS_COLOR, STATUS_LABEL, SIDE_LABEL } from '../utils/trading';
import type { OrderStatus } from '../types';

interface OrderFlowTabProps {
  accountId: number | null;
}

function formatTime(value: string) {
  return new Date(value).toLocaleTimeString('zh-CN', { hour12: false });
}

function formatPrice(order: TradingOrder) {
  const price = order.filled_price ?? order.order_price;
  return price === null ? '—' : Number(price).toFixed(2);
}

export function OrderFlowTab({ accountId }: OrderFlowTabProps) {
  const [orders, setOrders] = useState<TradingOrder[]>([]);

  useEffect(() => {
    let cancelled = false;
    Promise.resolve().then(() => {
      if (accountId === null) {
        setOrders([]);
        return undefined;
      }
      return fetchOrders({ account_id: accountId, page_size: 100 }).then((res) => {
        if (!cancelled) setOrders(res.items);
      }).catch(() => {
        if (!cancelled) message.error('订单列表加载失败');
      });
    });
    return () => { cancelled = true; };
  }, [accountId]);

  const columns = useMemo(() => [
    { title: '时间', dataIndex: 'created_at', width: 80, render: (v: string) => formatTime(v) },
    { title: '代码', dataIndex: 'symbol', width: 90, render: (v: string) => <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 600 }}>{v}</span> },
    { title: '方向', dataIndex: 'side', width: 55, render: (v: 'buy' | 'sell') => <Tag color={v === 'buy' ? 'var(--color-rise)' : 'var(--color-fall)'} style={{ margin: 0 }}>{SIDE_LABEL[v]}</Tag> },
    { title: '数量', dataIndex: 'order_qty', width: 55, render: (v: number) => <span style={{ fontFamily: 'var(--font-mono)' }}>{v}</span> },
    { title: '价格', width: 75, render: (_: unknown, r: TradingOrder) => <span style={{ fontFamily: 'var(--font-mono)' }}>{formatPrice(r)}</span> },
    { title: '状态', dataIndex: 'status', width: 65, render: (v: OrderStatus) => <Tag color={STATUS_COLOR[v]}>{STATUS_LABEL[v]}</Tag> },
    { title: '券商单号', dataIndex: 'broker_order_id', width: 130, ellipsis: true, render: (v: string | null) => v || '—' },
  ], []);

  return (
    <div data-component="Order Flow Table">
      <Table
        dataSource={orders} columns={columns} rowKey="id" size="small"
        pagination={{ pageSize: 10, size: 'small', showTotal: t => `共 ${t} 条` }}
        rowClassName={r => r.side === 'buy' ? 'order-row--buy' : 'order-row--sell'}
      />
    </div>
  );
}
