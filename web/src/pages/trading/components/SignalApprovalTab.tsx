import { useState, useEffect, useCallback } from 'react';
import { Tag, Button, Space, message } from 'antd';
import { Zap, ArrowRight, History, AlertTriangle } from 'lucide-react';
import { fetchPreOrders, approvePreOrder, batchApprovePreOrders, type PreOrder } from '@/api/trading';
import { SIGNAL_SIDE_LABEL, SIGNAL_SIDE_COLOR } from '../utils/trading';

function RiskAlertMarquee() {
  const items = [
    '⚠ 600519 权重偏离 +1.2%',
    '⚠ 000858 单票仓位 12%/10%',
  ];
  if (items.length === 0) return null;
  const doubled = [...items, ...items];
  return (
    <div className="risk-alert-marquee" data-component="Risk Alert Marquee">
      <AlertTriangle size={13} style={{ color: 'var(--color-warning)', flexShrink: 0 }} />
      <div className="risk-alert-marquee__track">
        <div className="risk-alert-marquee__content">
          {doubled.map((text, i) => (
            <span key={i} className="risk-alert-marquee__item">{text}</span>
          ))}
        </div>
      </div>
      <Tag color="warning" style={{ fontSize: 10, fontWeight: 600, flexShrink: 0 }}>{items.length}条告警</Tag>
    </div>
  );
}

interface SignalApprovalTabProps {
  onOpenHistory: () => void;
}

export function SignalApprovalTab({ onOpenHistory }: SignalApprovalTabProps) {
  const [preOrders, setPreOrders] = useState<PreOrder[]>([]);
  const [loading, setLoading] = useState(false);

  const loadPendingPreOrders = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetchPreOrders({ approval_status: 'pending', page_size: 100 });
      setPreOrders(res.items);
    } catch {
      // API 不可用时保持空列表
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadPendingPreOrders();
  }, [loadPendingPreOrders]);

  const handleApprove = useCallback(async (preOrderId: number, approved: boolean) => {
    try {
      await approvePreOrder(preOrderId, { approved, approved_by: 'user' });
      setPreOrders(prev => prev.filter(po => po.id !== preOrderId));
      message.success(approved ? '已批准' : '已拒绝');
    } catch {
      message.error('操作失败');
    }
  }, []);

  const handleBatchApprove = useCallback(async () => {
    if (preOrders.length === 0) return;
    try {
      const result = await batchApprovePreOrders({
        pre_order_ids: preOrders.map(po => po.id),
        approved: true,
        approved_by: 'user',
      });
      message.success(`批量批准: ${result.approved}条`);
      setPreOrders([]);
    } catch {
      message.error('批量审批失败');
    }
  }, [preOrders]);

  const handleBatchReject = useCallback(async () => {
    if (preOrders.length === 0) return;
    try {
      const result = await batchApprovePreOrders({
        pre_order_ids: preOrders.map(po => po.id),
        approved: false,
        approved_by: 'user',
      });
      message.success(`批量拒绝: ${result.rejected}条`);
      setPreOrders([]);
    } catch {
      message.error('批量审批失败');
    }
  }, [preOrders]);

  return (
    <div className="signal-approval-tab" data-component="Signal & Approval Tab">
      <div className="signal-approval-tab__active">
        <div className="signal-approval-tab__header">
          <div className="signal-approval-tab__title">
            <Zap size={15} style={{ color: 'var(--accent-primary)' }} />
            <span>待审批信号</span>
            <Tag color="gold" style={{ fontWeight: 600, fontSize: 11 }}>{preOrders.length}</Tag>
          </div>
          {preOrders.length > 0 && (
            <div className="signal-approval-tab__dates">
              <span className="signal-approval-tab__date-label">信号日 T:</span>
              <span className="signal-approval-tab__date-value">{preOrders[0].signal_date}</span>
              <ArrowRight size={14} style={{ color: 'var(--accent-primary)' }} />
              <span className="signal-approval-tab__date-label">执行日 T+1:</span>
              <span className="signal-approval-tab__date-value">{preOrders[0].execution_date}</span>
            </div>
          )}
          <Space>
            <Button size="small" icon={<History size={12} />} onClick={onOpenHistory}>历史信号</Button>
            <Button size="small" danger onClick={handleBatchReject} disabled={preOrders.length === 0}>
              全部拒绝
            </Button>
            <Button type="primary" size="small" icon={<Zap size={12} />} onClick={handleBatchApprove} disabled={preOrders.length === 0} loading={loading}>
              批量批准 ({preOrders.length})
            </Button>
          </Space>
        </div>

        <RiskAlertMarquee />

        <div className="signal-approval-tab__cards">
          {preOrders.map(po => (
            <div
              key={po.id}
              className={`signal-card ${po.side === 'open' || po.side === 'add' ? 'signal-card--open' : 'signal-card--reduce'}`}
              data-component="Signal Card"
            >
              <div className="signal-card__top">
                <div className="signal-card__identity">
                  <span className="signal-card__symbol">{po.symbol}</span>
                </div>
                <Tag color={SIGNAL_SIDE_COLOR[po.side]} style={{ fontSize: 11, padding: '0 6px', borderRadius: 4, fontWeight: 600 }}>
                  {SIGNAL_SIDE_LABEL[po.side]}
                </Tag>
              </div>
              <div className="signal-card__body">
                <div className="signal-card__metric">
                  <span className="signal-card__metric-label">建议</span>
                  <span className="signal-card__metric-value">
                    {po.target_qty ? `${po.target_qty}股` : '—'}
                    {po.order_type === 'limit' && po.limit_price ? ` @¥${po.limit_price}` : ' @市价'}
                  </span>
                </div>
                <div className="signal-card__metric">
                  <span className="signal-card__metric-label">权重</span>
                  <span className="signal-card__metric-value">
                    目标{po.target_weight ?? '—'}%
                    <span style={{ color: 'var(--text-muted)', fontSize: 10 }}> 当前{po.current_weight ?? '—'}%</span>
                  </span>
                </div>
                <div className="signal-card__metric">
                  <span className="signal-card__metric-label">配仓</span>
                  <span className="signal-card__metric-value--secondary">{po.sizing_strategy || '—'}</span>
                </div>
              </div>
              <div className="signal-card__action">
                <Space size={4}>
                  <Button size="small" danger onClick={() => handleApprove(po.id, false)}>拒绝</Button>
                  <Button size="small" type="primary" onClick={() => handleApprove(po.id, true)}>批准</Button>
                </Space>
              </div>
            </div>
          ))}
          {preOrders.length === 0 && !loading && (
            <div style={{ textAlign: 'center', color: 'var(--text-muted)', padding: 20, fontSize: 12 }}>
              暂无待审批信号
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
