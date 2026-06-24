import { useState, useMemo, useEffect, useCallback } from 'react';
import { Tabs, Select, Space, Table, Tag, Modal } from 'antd';
import { Star, Briefcase, ListOrdered, GitBranch } from 'lucide-react';
import { usePageWebSocket } from '@/ws/usePageWebSocket';
import { TOPIC_TRADING_PNL, type TradingPnlData } from '@/ws/protocol';
import { fetchAccounts, fetchAccountSnapshot, type TradingAccount } from '@/api/trading';
import { useTradingStore } from '@/stores/tradingStore';
import { SIGNAL_HISTORY } from './data/mock-trading';
import { SIGNAL_SIDE_LABEL, SIGNAL_SIDE_COLOR } from './utils/trading';
import { CockpitDashboard } from './components/CockpitDashboard';
import { SignalApprovalTab } from './components/SignalApprovalTab';
import { RiskSidePanel } from './components/RiskSidePanel';
import { WatchlistStrategyTab } from './components/WatchlistStrategyTab';
import { PositionPnLTab } from './components/PositionPnLTab';
import { OrderFlowTab } from './components/OrderFlowTab';
import { WorkflowRunTab } from './components/WorkflowRunTab';
import '@/styles/trading.css';

const historyColumns = [
  { title: '信号日', dataIndex: 'signalDate', width: 80 },
  { title: '标的', width: 140, render: (_: unknown, r: typeof SIGNAL_HISTORY[number]) => <span><span style={{ fontFamily: 'var(--font-mono)', fontWeight: 600 }}>{r.symbol}</span> <span style={{ color: 'var(--text-secondary)', fontSize: 11 }}>{r.name}</span></span> },
  { title: '方向', dataIndex: 'direction', width: 60, render: (v: 'open' | 'add' | 'reduce' | 'close') => <Tag color={SIGNAL_SIDE_COLOR[v]} style={{ fontSize: 10, margin: 0 }}>{SIGNAL_SIDE_LABEL[v]}</Tag> },
  { title: '状态', dataIndex: 'status', width: 70, render: (v: string) => <Tag color={v === 'filled' ? 'success' : 'error'} style={{ fontSize: 10 }}>{v === 'filled' ? '已成交' : '已拒绝'}</Tag> },
  { title: '审批人', dataIndex: 'approvedBy', width: 60 },
  { title: '结果', dataIndex: 'result', width: 65, render: (v: string) => <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 600, color: v.startsWith('+') ? 'var(--color-rise)' : v.startsWith('-') ? 'var(--color-fall)' : 'var(--text-muted)' }}>{v}</span> },
];

export function LiveCockpitPage() {
  const [accounts, setAccounts] = useState<TradingAccount[]>([]);
  const [selectedAccountId, setSelectedAccountId] = useState<number | null>(null);
  const [historyOpen, setHistoryOpen] = useState(false);

  const initFromAsset = useTradingStore((s) => s.initFromAsset);
  const updateFromPnl = useTradingStore((s) => s.updateFromPnl);
  const reset = useTradingStore((s) => s.reset);

  // 加载账户列表
  useEffect(() => {
    let cancelled = false;
    fetchAccounts({ page_size: 200 }).then((res) => {
      if (!cancelled && res.items.length > 0) {
        setAccounts(res.items);
        setSelectedAccountId(res.items[0].id);
      }
    }).catch(() => {
      // API 不可用时保持空列表
    });
    return () => { cancelled = true; };
  }, []);

  // 初始加载账户快照，后端无快照时回退 td_account 基础数据
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
          today_pnl: Number(snapshot.daily_pnl ?? 0),
          today_pnl_pct: Number(snapshot.daily_return ?? 0),
          cumulative_pnl: Number(snapshot.cumulative_pnl ?? 0),
        });
      }
    }).catch(() => {
      if (!cancelled) {
        reset(selectedAccountId);
      }
    });
    return () => { cancelled = true; };
  }, [selectedAccountId, initFromAsset, reset]);

  // WebSocket 订阅交易 PnL；支持 items 数组格式（多账户）和单对象格式（兼容旧版）
  const handlePnlUpdate = useCallback((_channel: string, data: TradingPnlData) => {
    if (!data || typeof data !== 'object' || selectedAccountId === null) return;

    // 新格式：items 数组，按 account_id 匹配当前账户
    if (data.items && Array.isArray(data.items)) {
      const item = data.items.find(i => i.account_id === selectedAccountId);
      if (item) {
        updateFromPnl(selectedAccountId, item);
      }
      return;
    }

    // 旧格式：单对象，无 account_id 或匹配时直接使用
    if (data.account_id === undefined || data.account_id === selectedAccountId) {
      updateFromPnl(selectedAccountId, data as Required<Pick<TradingPnlData, 'cash' | 'frozen_cash' | 'market_value' | 'total_asset' | 'today_pnl' | 'today_pnl_pct'>> & { account_id?: number });
    }
  }, [selectedAccountId, updateFromPnl]);

  usePageWebSocket<TradingPnlData>({
    topics: [TOPIC_TRADING_PNL],
    onSnapshot: handlePnlUpdate,
    onUpdate: handlePnlUpdate,
  });

  const secondaryItems = useMemo(() => [
    { key: 'watchlist', label: <Space size={4}><Star size={13} />自选&策略</Space>, children: <WatchlistStrategyTab accountId={selectedAccountId} /> },
    { key: 'positions', label: <Space size={4}><Briefcase size={13} />持仓&收益</Space>, children: <PositionPnLTab /> },
    { key: 'orders', label: <Space size={4}><ListOrdered size={13} />订单&成交</Space>, children: <OrderFlowTab /> },
    { key: 'workflow', label: <Space size={4}><GitBranch size={13} />工作流</Space>, children: <WorkflowRunTab /> },
  ], [selectedAccountId]);

  return (
    <div className="trading-page" data-component="Live Trading Cockpit">
      <div className="trading-page__header">
        <div className="trading-page__title-area">
          <span className="trading-page__title">实盘交易</span>
          <Select
            value={selectedAccountId ?? undefined}
            onChange={setSelectedAccountId}
            options={accounts.map((a) => ({
              value: a.id,
              label: `${a.account_name} (${a.broker_type.toUpperCase()})`,
            }))}
            size="small"
            style={{ width: 220 }}
            loading={accounts.length === 0}
          />
          <span className="live-tag"><span className="live-tag__dot" />LIVE</span>
        </div>
      </div>

      <div className="trading-page__content">
        <CockpitDashboard />

        <div className="trading-layout__main">
          <div className="trading-layout__signal">
            <SignalApprovalTab onOpenHistory={() => setHistoryOpen(true)} />
          </div>
          <div className="trading-layout__risk">
            <RiskSidePanel onOpenHistory={() => setHistoryOpen(true)} />
          </div>
        </div>

        <div className="trading-layout__secondary">
          <Tabs items={secondaryItems} size="small" defaultActiveKey="watchlist" />
        </div>
      </div>

      <Modal
        title={<span style={{ fontWeight: 600 }}>历史信号 ({SIGNAL_HISTORY.length})</span>}
        open={historyOpen}
        onCancel={() => setHistoryOpen(false)}
        footer={null}
        width={700}
        destroyOnHidden
      >
        <Table dataSource={SIGNAL_HISTORY} columns={historyColumns} rowKey="signalDate" size="small" pagination={false} />
      </Modal>
    </div>
  );
}
