import { useEffect, useMemo, useState } from 'react';
import { App, Spin, Table } from 'antd';
import {
  fetchAccountSnapshots,
  fetchPositions,
  type AccountSnapshot,
  type PositionSnapshot,
} from '@/api/trading';
import { PnlCalendar } from './PnlCalendar';
import { StockSymbolCell } from './StockQuoteCell';
import { PositionPriceCostCell } from './PositionPriceCostCell';

interface PositionPnLTabProps {
  accountId: number | null;
}

function num(value: string | number | null) {
  return Number(value ?? 0);
}

export function PositionPnLTab({ accountId }: PositionPnLTabProps) {
  const { message } = App.useApp();
  const [positions, setPositions] = useState<PositionSnapshot[]>([]);
  const [snapshots, setSnapshots] = useState<AccountSnapshot[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    Promise.resolve().then(() => {
      if (accountId === null) {
        setPositions([]);
        setSnapshots([]);
        setLoading(false);
        return undefined;
      }
      setLoading(true);
      return Promise.all([
        fetchPositions(accountId),
        fetchAccountSnapshots(accountId, { page_size: 31 }),
      ]).then(([positionRes, snapshotRes]) => {
        if (cancelled) return;
        setPositions(positionRes.items);
        setSnapshots(snapshotRes.items);
      }).catch(() => {
        if (!cancelled) message.error('持仓与收益加载失败');
      }).finally(() => {
        if (!cancelled) setLoading(false);
      });
    });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- message 为 antd 稳定引用
  }, [accountId]);

  const columns = useMemo(() => [
    {
      title: '标的',
      key: 'symbol',
      width: 110,
      render: (_: unknown, row: PositionSnapshot) => (
        <StockSymbolCell symbol={row.symbol} name={row.name} />
      ),
    },
    {
      title: '现价/成本',
      key: 'price_cost',
      width: 100,
      render: (_: unknown, row: PositionSnapshot) => (
        <PositionPriceCostCell marketPrice={row.market_price} costPrice={row.cost_price} />
      ),
    },
    { title: '数量', dataIndex: 'qty', width: 70 },
    {
      title: '目标权重', dataIndex: 'target_weight', width: 75,
      render: (v: string | number | null) => <span style={{ fontFamily: 'var(--font-mono)' }}>{(num(v) * 100).toFixed(2)}%</span>,
    },
    {
      title: '实际权重', dataIndex: 'weight', width: 75,
      render: (v: string | number | null) => <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 500 }}>{(num(v) * 100).toFixed(2)}%</span>,
    },
    {
      title: '偏离', dataIndex: 'weight_deviation', width: 65,
      render: (v: string | number | null) => {
        const value = num(v) * 100;
        const color = Math.abs(value) > 1 ? 'var(--color-warning)' : 'var(--text-secondary)';
        return <span style={{ color, fontFamily: 'var(--font-mono)', fontWeight: 600 }}>{value > 0 ? '+' : ''}{value.toFixed(2)}%</span>;
      },
    },
    {
      title: '浮盈亏', dataIndex: 'unrealized_pnl', width: 90,
      render: (v: string | number | null) => {
        const value = num(v);
        return <span style={{ color: value > 0 ? 'var(--color-rise)' : 'var(--color-fall)', fontFamily: 'var(--font-mono)', fontWeight: 600 }}>{value > 0 ? '+' : ''}{value.toFixed(0)}</span>;
      },
    },
  ], []);

  return (
    <Spin spinning={loading}>
      <div className="position-pnl-tab" data-component="Position & PnL Tab">
        <div className="position-pnl-tab__table">
          <Table
            dataSource={positions} columns={columns} rowKey="id" size="small" pagination={false}
            scroll={{ y: 300 }}
            rowClassName={(r) => Math.abs(num(r.weight_deviation)) > 0.01 ? 'position-row--deviated' : ''}
          />
        </div>
        <div className="position-pnl-tab__calendar">
          <PnlCalendar snapshots={snapshots} />
        </div>
      </div>
    </Spin>
  );
}
