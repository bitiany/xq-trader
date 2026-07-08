import { useState, useMemo, useEffect, useCallback } from 'react';
import { Tabs, Select, Space, Table, Tag, Modal, message } from 'antd';
import { Star, Briefcase, ListOrdered, GitBranch } from 'lucide-react';
import { usePageWebSocket } from '@/ws/usePageWebSocket';
import { TOPIC_TRADING_PNL, type TradingPnlData } from '@/ws/protocol';
import {
  fetchAccounts,
  fetchAccountDecisionWorkflowInstance,
  fetchAccountSnapshot,
  fetchPreOrders,
  type PreOrder,
  type TradingAccount,
} from '@/api/trading';
import { useTradingStore } from '@/stores/tradingStore';
import { SIGNAL_SIDE_LABEL, SIGNAL_SIDE_COLOR } from './utils/trading';
import { CockpitDashboard } from './components/CockpitDashboard';
import { SignalApprovalTab } from './components/SignalApprovalTab';
import { RiskSidePanel } from './components/RiskSidePanel';
import { WatchlistStrategyTab } from './components/WatchlistStrategyTab';
import { PositionPnLTab } from './components/PositionPnLTab';
import { OrderFlowTab } from './components/OrderFlowTab';
import { WorkflowRunTab } from './components/WorkflowRunTab';
import { StockSymbolCell } from './components/StockQuoteCell';
import '@/styles/trading.css';

const historyColumns = [
  { title: '信号日', dataIndex: 'signal_date', width: 90 },
  {
    title: '标的',
    key: 'symbol',
    width: 130,
    render: (_: unknown, row: PreOrder) => <StockSymbolCell symbol={row.symbol} name={row.name} />,
  },
  { title: '方向', dataIndex: 'side', width: 60, render: (v: PreOrder['side']) => <Tag color={SIGNAL_SIDE_COLOR[v]} style={{ fontSize: 10, margin: 0 }}>{SIGNAL_SIDE_LABEL[v]}</Tag> },
  { title: '状态', dataIndex: 'approval_status', width: 70, render: (v: PreOrder['approval_status']) => <Tag color={v === 'approved' ? 'success' : v === 'rejected' ? 'error' : 'default'} style={{ fontSize: 10 }}>{v}</Tag> },
  { title: '目标权重', dataIndex: 'target_weight', width: 80, render: (v: number | null) => v === null ? '—' : `${(Number(v) * 100).toFixed(2)}%` },
  { title: '审批时间', dataIndex: 'approved_at', width: 150, render: (v: string | null) => v ? new Date(v).toLocaleString('zh-CN', { hour12: false }) : '—' },
];

const ACCOUNT_TYPE_LABEL: Record<TradingAccount['account_type'], string> = {
  live: 'LIVE',
  paper: 'PAPER',
};

const ACCOUNT_TYPE_COLOR: Record<TradingAccount['account_type'], string> = {
  live: 'red',
  paper: 'blue',
};

export function LiveCockpitPage() {
  const [accounts, setAccounts] = useState<TradingAccount[]>([]);
  const [selectedAccountId, setSelectedAccountId] = useState<number | null>(null);
  const [activeDecisionInstanceId, setActiveDecisionInstanceId] = useState<number | null>(null);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [signalHistory, setSignalHistory] = useState<PreOrder[]>([]);

  const selectedAccount = useMemo(
    () => accounts.find(account => account.id === selectedAccountId) ?? null,
    [accounts, selectedAccountId],
  );

  const initFromAsset = useTradingStore((s) => s.initFromAsset);
  const updateFromPnl = useTradingStore((s) => s.updateFromPnl);
  const reset = useTradingStore((s) => s.reset);

  useEffect(() => {
    let cancelled = false;
    Promise.resolve().then(() => {
      return fetchAccounts({ page_size: 200 }).then((res) => {
        if (!cancelled && res.items.length > 0) {
          setAccounts(res.items);
          setSelectedAccountId(res.items.find(account => account.account_type === 'paper')?.id ?? res.items[0].id);
        }
      });
    });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    setActiveDecisionInstanceId(null);
    if (selectedAccountId === null) {
      return;
    }
    let cancelled = false;
    fetchAccountDecisionWorkflowInstance(selectedAccountId).then((instance) => {
      if (!cancelled) setActiveDecisionInstanceId(instance.id);
    }).catch(() => {
      if (!cancelled) setActiveDecisionInstanceId(null);
    });
    return () => { cancelled = true; };
  }, [selectedAccountId]);

  useEffect(() => {
    if (selectedAccountId === null) return;
    reset();
    let cancelled = false;
    fetchAccountSnapshot(selectedAccountId).then((snapshot) => {
      if (!cancelled && snapshot && snapshot.total_assets !== undefined) {
        initFromAsset(selectedAccountId, {
          cash: Number(snapshot.available_cash),
          frozen_cash: Number(snapshot.frozen_cash),
          market_value: Number(snapshot.market_value),
          total_asset: Number(snapshot.total_assets),
          today_pnl: Number(snapshot.daily_pnl),
          today_pnl_pct: Number(snapshot.daily_return),
          cumulative_pnl: Number(snapshot.cumulative_pnl),
        });
      }
    });
    return () => { cancelled = true; };
  }, [selectedAccountId, initFromAsset, reset]);

  useEffect(() => {
    let cancelled = false;
    Promise.resolve().then(() => {
      if (!historyOpen || selectedAccountId === null) {
        setSignalHistory([]);
        return undefined;
      }
      return fetchPreOrders({ account_id: selectedAccountId, page_size: 200 }).then((res) => {
        if (!cancelled) setSignalHistory(res.items);
      }).catch(() => {
        if (!cancelled) message.error('历史信号加载失败');
      });
    });
    return () => { cancelled = true; };
  }, [historyOpen, selectedAccountId]);

  const handlePnlUpdate = useCallback((_channel: string, data: TradingPnlData) => {
    if (!data || typeof data !== 'object' || selectedAccountId === null) return;
    if (data.items && Array.isArray(data.items)) {
      const item = data.items.find(i => i.account_id === selectedAccountId);
      if (item) updateFromPnl(selectedAccountId, item);
      return;
    }
    if (data.account_id === selectedAccountId) {
      updateFromPnl(selectedAccountId, data);
    }
  }, [selectedAccountId, updateFromPnl]);

  usePageWebSocket<TradingPnlData>({
    topics: [TOPIC_TRADING_PNL],
    onSnapshot: handlePnlUpdate,
    onUpdate: handlePnlUpdate,
  });

  const secondaryItems = useMemo(() => [
    { key: 'watchlist', label: <Space size={4}><Star size={13} />自选&策略</Space>, children: <WatchlistStrategyTab accountId={selectedAccountId} /> },
    { key: 'positions', label: <Space size={4}><Briefcase size={13} />持仓&收益</Space>, children: <PositionPnLTab accountId={selectedAccountId} /> },
    { key: 'orders', label: <Space size={4}><ListOrdered size={13} />订单&成交</Space>, children: <OrderFlowTab accountId={selectedAccountId} /> },
    { key: 'workflow', label: <Space size={4}><GitBranch size={13} />工作流</Space>, children: <WorkflowRunTab accountId={selectedAccountId} onOpenApproval={() => setHistoryOpen(true)} /> },
  ], [selectedAccountId]);

  return (
    <div className="trading-page" data-component="Live Trading Cockpit">
      <div className="trading-page__header">
        <div className="trading-page__title-area">
          <span className="trading-page__title">交易工作台</span>
          <Select
            value={selectedAccountId ?? undefined}
            onChange={setSelectedAccountId}
            options={accounts.map((a) => ({
              value: a.id,
              label: `${ACCOUNT_TYPE_LABEL[a.account_type]} #${a.id} ${a.account_name} (${a.broker_type.toUpperCase()})`,
            }))}
            size="small"
            style={{ width: 280 }}
            loading={accounts.length === 0}
          />
          {selectedAccount && (
            <Tag color={ACCOUNT_TYPE_COLOR[selectedAccount.account_type]} style={{ fontWeight: 600 }}>
              {ACCOUNT_TYPE_LABEL[selectedAccount.account_type]}
            </Tag>
          )}
        </div>
      </div>

      <div className="trading-page__content">
        <CockpitDashboard />

        <div className="trading-layout__main">
          <div className="trading-layout__signal">
            <SignalApprovalTab
              accountId={selectedAccountId}
              instanceId={activeDecisionInstanceId}
              onInstanceChange={setActiveDecisionInstanceId}
              onOpenHistory={() => setHistoryOpen(true)}
            />
          </div>
          <div className="trading-layout__risk">
            <RiskSidePanel
              accountId={selectedAccountId}
              instanceId={activeDecisionInstanceId}
              onOpenHistory={() => setHistoryOpen(true)}
            />
          </div>
        </div>

        <div className="trading-layout__secondary">
          <Tabs items={secondaryItems} size="small" defaultActiveKey="watchlist" />
        </div>
      </div>

      <Modal
        title={<span style={{ fontWeight: 600 }}>历史信号 ({signalHistory.length})</span>}
        open={historyOpen}
        onCancel={() => setHistoryOpen(false)}
        footer={null}
        width={760}
        destroyOnHidden
      >
        <Table dataSource={signalHistory} columns={historyColumns} rowKey="id" size="small" pagination={{ pageSize: 10, size: 'small' }} />
      </Modal>
    </div>
  );
}