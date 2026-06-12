import { useState } from 'react';
import { Tag, Button, Space } from 'antd';
import { Zap, ArrowRight, History, AlertTriangle } from 'lucide-react';
import { PRE_ORDERS, RISK_STATUS } from '../data/mock-trading';
import { SIGNAL_SIDE_LABEL, SIGNAL_SIDE_COLOR } from '../utils/trading';
import { SingleApprovalPopover } from './SingleApprovalPopover';
import { PreOrderApprovalDrawer } from './PreOrderApprovalDrawer';

function RiskAlertMarquee() {
  const allAlerts = [
    ...RISK_STATUS.deviationAlerts.map(a => `⚠ ${a.symbol} 权重偏离 +${a.deviation}%（目标${a.targetWeight}%→当前${a.currentWeight}%）`),
  ];
  const recentWarnEvents = [
    '⚠ 600519 权重偏离 +1.2%',
    '⚠ 000858 单票仓位 12%/10%',
  ];
  const items = [...allAlerts, ...recentWarnEvents];
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
  const [drawerOpen, setDrawerOpen] = useState(false);

  return (
    <div className="signal-approval-tab" data-component="Signal & Approval Tab">
      <div className="signal-approval-tab__active">
        <div className="signal-approval-tab__header">
          <div className="signal-approval-tab__title">
            <Zap size={15} style={{ color: 'var(--accent-primary)' }} />
            <span>待审批信号</span>
            <Tag color="gold" style={{ fontWeight: 600, fontSize: 11 }}>{PRE_ORDERS.length}</Tag>
          </div>
          <div className="signal-approval-tab__dates">
            <span className="signal-approval-tab__date-label">信号日 T:</span>
            <span className="signal-approval-tab__date-value">2026-06-09</span>
            <ArrowRight size={14} style={{ color: 'var(--accent-primary)' }} />
            <span className="signal-approval-tab__date-label">执行日 T+1:</span>
            <span className="signal-approval-tab__date-value">2026-06-10</span>
          </div>
          <Space>
            <Button size="small" icon={<History size={12} />} onClick={onOpenHistory}>历史信号</Button>
            <Button size="small" danger>全部拒绝</Button>
            <Button type="primary" size="small" icon={<Zap size={12} />} onClick={() => setDrawerOpen(true)}>
              批量批准 ({PRE_ORDERS.length})
            </Button>
          </Space>
        </div>

        <RiskAlertMarquee />

        <div className="signal-approval-tab__cards">
          {PRE_ORDERS.map(po => (
            <SingleApprovalPopover key={po.id} po={po}>
              <div className={`signal-card ${po.side === 'open' || po.side === 'add' ? 'signal-card--open' : 'signal-card--reduce'}`} data-component="Signal Card">
                <div className="signal-card__top">
                  <div className="signal-card__identity">
                    <span className="signal-card__symbol">{po.symbol}</span>
                    <span className="signal-card__name">{po.name}</span>
                  </div>
                  <Tag color={SIGNAL_SIDE_COLOR[po.side]} style={{ fontSize: 11, padding: '0 6px', borderRadius: 4, fontWeight: 600 }}>
                    {SIGNAL_SIDE_LABEL[po.side]}
                  </Tag>
                </div>
                <div className="signal-card__body">
                  <div className="signal-card__metric">
                    <span className="signal-card__metric-label">建议</span>
                    <span className="signal-card__metric-value">{po.suggestedQty}股 {po.priceType === 'limit' ? `@¥${po.suggestedPrice}` : '@市价'}</span>
                  </div>
                  <div className="signal-card__metric">
                    <span className="signal-card__metric-label">权重</span>
                    <span className="signal-card__metric-value">目标{po.targetWeight}% <span style={{ color: 'var(--text-muted)', fontSize: 10 }}>当前{po.currentWeight}%</span></span>
                  </div>
                  <div className="signal-card__metric">
                    <span className="signal-card__metric-label">配仓</span>
                    <span className="signal-card__metric-value--secondary">{po.sizingStrategy}</span>
                  </div>
                </div>
                <div className="signal-card__action">
                  <span style={{ fontSize: 12, color: 'var(--accent-primary)' }}>点击审批</span>
                </div>
              </div>
            </SingleApprovalPopover>
          ))}
        </div>
      </div>

      <PreOrderApprovalDrawer open={drawerOpen} onClose={() => setDrawerOpen(false)} preOrders={PRE_ORDERS} />
    </div>
  );
}
