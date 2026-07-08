import { useEffect, useMemo, useState } from 'react';
import { Spin, Table, Tag, message } from 'antd';
import { fetchOrders, type TradingOrder } from '@/api/trading';
import { STATUS_COLOR, STATUS_LABEL, SIDE_LABEL } from '../utils/trading';
import type { OrderStatus } from '../types';
import { StockSymbolCell } from './StockQuoteCell';
import { SignalBasisCell } from './SignalBasisCell';

interface OrderFlowTabProps {
  accountId: number | null;
}

function formatOrderTime(order: TradingOrder): string {
  const raw = order.trade_time ?? order.created_at;
  if (!raw) return '—';
  const dt = new Date(raw);
  const datePart = order.execution_date ?? order.signal_date;
  if (datePart) {
    return `${datePart} ${dt.toLocaleTimeString('zh-CN', { hour12: false, hour: '2-digit', minute: '2-digit' })}`;
  }
  return dt.toLocaleString('zh-CN', { hour12: false, month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
}

function formatPrice(order: TradingOrder) {
  const price = order.filled_price ?? order.order_price;
  return price === null ? '—' : Number(price).toFixed(2);
}

export function OrderFlowTab({ accountId }: OrderFlowTabProps) {
  const [orders, setOrders] = useState<TradingOrder[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    Promise.resolve().then(() => {
      if (accountId === null) {
        setOrders([]);
        setLoading(false);
        return undefined;
      }
      setLoading(true);
      return fetchOrders({ account_id: accountId, page_size: 100 }).then((res) => {
        if (!cancelled) setOrders(res.items);
      }).catch(() => {
        if (!cancelled) message.error('订单列表加载失败');
      }).finally(() => {
        if (!cancelled) setLoading(false);
      });
    });
    return () => { cancelled = true; };
  }, [accountId]);

  const columns = useMemo(() => [
    {
      title: '成交时间',
      key: 'trade_time',
      width: 108,
      render: (_: unknown, row: TradingOrder) => (
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11 }}>{formatOrderTime(row)}</span>
      ),
    },
    {
      title: '标的',
      key: 'symbol',
      width: 96,
      render: (_: unknown, row: TradingOrder) => (
        <StockSymbolCell symbol={row.symbol} name={row.name} />
      ),
    },
    { title: '方向', dataIndex: 'side', width: 48, render: (v: 'buy' | 'sell') => <Tag color={v === 'buy' ? 'var(--color-rise)' : 'var(--color-fall)'} style={{ margin: 0 }}>{SIDE_LABEL[v]}</Tag> },
    { title: '数量', dataIndex: 'order_qty', width: 48, render: (v: number) => <span style={{ fontFamily: 'var(--font-mono)' }}>{v}</span> },
    { title: '价格', width: 64, render: (_: unknown, r: TradingOrder) => <span style={{ fontFamily: 'var(--font-mono)' }}>{formatPrice(r)}</span> },
    { title: '状态', dataIndex: 'status', width: 58, render: (v: OrderStatus) => <Tag color={STATUS_COLOR[v]}>{STATUS_LABEL[v]}</Tag> },
    {
      title: '信号依据',
      key: 'signal_detail',
      ellipsis: true,
      render: (_: unknown, row: TradingOrder) => <SignalBasisCell detail={row.signal_detail} />,
    },
    { title: '券商单号', dataIndex: 'broker_order_id', width: 96, ellipsis: true, render: (v: string | null) => v || '—' },
  ], []);

  return (
    <Spin spinning={loading}>
      <div data-component="Order Flow Table">
        <Table
          dataSource={orders} columns={columns} rowKey="id" size="small"
          pagination={{ pageSize: 10, size: 'small', showTotal: t => `共 ${t} 条` }}
          rowClassName={r => r.side === 'buy' ? 'order-row--buy' : 'order-row--sell'}
          scroll={{ x: 860 }}
          tableLayout="fixed"
        />
      </div>
    </Spin>
  );
}
