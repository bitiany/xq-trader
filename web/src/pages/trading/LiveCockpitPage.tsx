import { useState, useMemo, useEffect, useCallback } from 'react';
import { Tabs, Select, Space, Table, Tag, Modal } from 'antd';
import { Star, Briefcase, ListOrdered, GitBranch } from 'lucide-react';
import { usePageWebSocket } from '@/ws/usePageWebSocket';
import { TOPIC_TRADING_PNL, type TradingPnlData } from '@/ws/protocol';
import { brokerApi } from '@/api/broker';
import { useTradingStore } from '@/stores/tradingStore';
import { ACCOUNTS, SIGNAL_HISTORY } from './data/mock-trading';
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
  const [selectedAccount, setSelectedAccount] = useState('live-001');
  const [historyOpen, setHistoryOpen] = useState(false);

  const initFromAsset = useTradingStore((s) => s.initFromAsset);
  const updateFromPnl = useTradingStore((s) => s.updateFromPnl);
  const reset = useTradingStore((s) => s.reset);

  // 初始加载 REST API 资产数据
  useEffect(() => {
    let cancelled = false;
    brokerApi.getAsset().then((asset) => {
      if (!cancelled && asset) {
        initFromAsset(asset);
      }
    }).catch(() => {
      // REST 不可用时静默处理，WS 会补上
    });
    return () => { cancelled = true; };
  }, [initFromAsset]);

  // WebSocket 订阅交易 PnL
  const handlePnlUpdate = useCallback((_channel: string, data: TradingPnlData) => {
    if (data && typeof data === 'object') {
      updateFromPnl(data);
    }
  }, [updateFromPnl]);

  const { status: wsStatus } = usePageWebSocket<TradingPnlData>({
    topics: [TOPIC_TRADING_PNL],
    onSnapshot: handlePnlUpdate,
    onUpdate: handlePnlUpdate,
  });

  // WS 断开时重置数据
  useEffect(() => {
    if (wsStatus !== 'open') {
      reset();
    }
  }, [wsStatus, reset]);

  const secondaryItems = useMemo(() => [
    { key: 'watchlist', label: <Space size={4}><Star size={13} />自选&策略</Space>, children: <WatchlistStrategyTab /> },
    { key: 'positions', label: <Space size={4}><Briefcase size={13} />持仓&收益</Space>, children: <PositionPnLTab /> },
    { key: 'orders', label: <Space size={4}><ListOrdered size={13} />订单&成交</Space>, children: <OrderFlowTab /> },
    { key: 'workflow', label: <Space size={4}><GitBranch size={13} />工作流</Space>, children: <WorkflowRunTab /> },
  ], []);

  return (
    <div className="trading-page" data-component="Live Trading Cockpit">
      <div className="trading-page__header">
        <div className="trading-page__title-area">
          <span className="trading-page__title">实盘交易</span>
          <Select value={selectedAccount} onChange={setSelectedAccount} options={ACCOUNTS} size="small" style={{ width: 180 }} />
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
        destroyOnClose
      >
        <Table dataSource={SIGNAL_HISTORY} columns={historyColumns} rowKey="signalDate" size="small" pagination={false} />
      </Modal>
    </div>
  );
}
