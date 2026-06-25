import { useEffect, useMemo, useState } from 'react';
import { Table, message } from 'antd';
import {
  fetchAccountSnapshots,
  fetchPositions,
  type AccountSnapshot,
  type PositionSnapshot,
} from '@/api/trading';
import { PnlCalendar } from './PnlCalendar';

interface PositionPnLTabProps {
  accountId: number | null;
}

function num(value: string | number | null) {
  return Number(value ?? 0);
}

export function PositionPnLTab({ accountId }: PositionPnLTabProps) {
  const [positions, setPositions] = useState<PositionSnapshot[]>([]);
  const [snapshots, setSnapshots] = useState<AccountSnapshot[]>([]);

  useEffect(() => {
    let cancelled = false;
    Promise.resolve().then(() => {
      if (accountId === null) {
        setPositions([]);
        setSnapshots([]);
        return undefined;
      }
      return Promise.all([
        fetchPositions(accountId),
        fetchAccountSnapshots(accountId, { page_size: 31 }),
      ]).then(([positionRes, snapshotRes]) => {
        if (cancelled) return;
        setPositions(positionRes.items);
        setSnapshots(snapshotRes.items);
      }).catch(() => {
        if (!cancelled) message.error('持仓与收益加载失败');
      });
    });
    return () => { cancelled = true; };
  }, [accountId]);

  const columns = useMemo(() => [
    { title: '代码', dataIndex: 'symbol', width: 90, render: (v: string) => <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 600 }}>{v}</span> },
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
    { title: '成本', dataIndex: 'cost_price', width: 70, render: (v: string | number | null) => num(v).toFixed(2) },
    { title: '现价', dataIndex: 'market_price', width: 70, render: (v: string | number | null) => num(v).toFixed(2) },
    {
      title: '浮盈亏', dataIndex: 'unrealized_pnl', width: 90,
      render: (v: string | number | null) => {
        const value = num(v);
        return <span style={{ color: value > 0 ? 'var(--color-rise)' : 'var(--color-fall)', fontFamily: 'var(--font-mono)', fontWeight: 600 }}>{value > 0 ? '+' : ''}{value.toFixed(0)}</span>;
      },
    },
  ], []);

  return (
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
  );
}
