import { useState, useMemo } from 'react';
import { Table, Tag, Switch, Badge, Button } from 'antd';
import { Shield, Flame, CheckCircle, ChevronDown, ChevronRight, History } from 'lucide-react';
import { RISK_STATUS, RISK_RULES } from '../data/mock-trading';
import { RISK_LEVEL_TAG } from '../utils/trading';

interface RiskSidePanelProps {
  onOpenHistory: () => void;
}

export function RiskSidePanel({ onOpenHistory }: RiskSidePanelProps) {
  const [showRules, setShowRules] = useState(false);
  const cbTriggered = RISK_STATUS.circuitBreakerTriggered;

  const ruleColumns = useMemo(() => [
    { title: '规则', dataIndex: 'code', width: 105, render: (v: string) => <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10 }}>{v}</span> },
    { title: '类别', dataIndex: 'category', width: 55, render: (v: string) => {
      const labels: Record<string, string> = { circuit_breaker: '熔断', position: '仓位', capital: '资金', timing: '时段' };
      return <span style={{ fontSize: 10, color: 'var(--text-secondary)' }}>{labels[v] || v}</span>;
    }},
    { title: '级', dataIndex: 'level', width: 35, render: (v: 'info' | 'warn' | 'critical' | 'fatal') => <Tag color={RISK_LEVEL_TAG[v]} style={{ fontSize: 9, padding: '0 3px', margin: 0, lineHeight: '16px' }}>{v}</Tag> },
    { title: '参数', dataIndex: 'params', width: 70, render: (v: string) => <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10 }}>{v}</span> },
    { title: '', dataIndex: 'enabled', width: 35, render: (v: boolean) => <Switch checked={v} size="small" /> },
  ], []);

  const lossPct = RISK_STATUS.dailyLossPct;
  const lossRatio = Math.min(Math.abs(lossPct) / 2, 1);
  const lossColor = lossPct <= -2 ? 'var(--color-rise)' : lossPct <= -1.5 ? 'var(--color-warning)' : 'var(--color-fall)';

  const statusColor = cbTriggered ? 'var(--color-rise)' : RISK_STATUS.activeAlerts > 0 ? 'var(--color-warning)' : 'var(--color-fall)';
  const statusText = cbTriggered ? '熔断触发' : RISK_STATUS.activeAlerts > 0 ? '风控告警' : '风控正常';

  return (
    <div className={`risk-side-panel ${cbTriggered ? 'risk-side-panel--triggered' : RISK_STATUS.activeAlerts > 0 ? 'risk-side-panel--warning' : ''}`} data-component="Risk Side Panel">
      <div className="risk-side-panel__header">
        <div className="risk-side-panel__status">
          <Shield size={16} style={{ color: statusColor }} />
          <span className="risk-side-panel__status-text" style={{ color: statusColor }}>
            {statusText}
          </span>
          {RISK_STATUS.activeAlerts > 0 && (
            <Badge count={RISK_STATUS.activeAlerts} size="small" style={{ backgroundColor: 'var(--color-warning)' }} />
          )}
        </div>
        <button className="risk-side-panel__kill-btn" data-component="Kill Switch Button">
          <Flame size={13} />
          <span>紧急全平</span>
        </button>
      </div>

      <div className="risk-side-panel__section">
        <div className="risk-side-panel__section-title">熔断器</div>
        <div className="risk-side-panel__circuit">
          <div className="risk-side-panel__circuit-top">
            {cbTriggered
              ? <><Flame size={18} style={{ color: 'var(--color-rise)' }} /><span style={{ color: 'var(--color-rise)', fontWeight: 700, fontSize: 13 }}>已触发</span></>
              : <><CheckCircle size={18} style={{ color: 'var(--color-fall)' }} /><span style={{ color: 'var(--color-fall)', fontWeight: 700, fontSize: 13 }}>未触发</span></>
            }
          </div>
          <div className="risk-side-panel__loss-bar">
            <div className="risk-side-panel__loss-track">
              <div className="risk-side-panel__loss-fill" style={{ width: `${lossRatio * 100}%`, background: lossColor }} />
              <div className="risk-side-panel__loss-threshold" style={{ left: '100%' }} />
            </div>
            <div className="risk-side-panel__loss-labels">
              <span style={{ color: lossColor, fontWeight: 600 }}>{lossPct}%</span>
              <span style={{ color: 'var(--text-muted)', fontSize: 10 }}>限 -2%</span>
            </div>
          </div>
        </div>
      </div>

      <div className="risk-side-panel__section">
        <div className="risk-side-panel__section-title">仓位概览</div>
        <div className="risk-side-panel__kv">
          <div className="risk-side-panel__kv-row">
            <span>持仓数</span>
            <span style={{ fontWeight: 600 }}>5<span style={{ color: 'var(--text-muted)', fontWeight: 400 }}>/10</span></span>
          </div>
          <div className="risk-side-panel__kv-row">
            <span>单票上限</span>
            <span style={{ fontWeight: 600, color: RISK_STATUS.activeAlerts > 0 ? 'var(--color-warning)' : 'var(--text-primary)' }}>12%<span style={{ color: 'var(--text-muted)', fontWeight: 400 }}>/10%</span></span>
          </div>
        </div>
      </div>

      <div className="risk-side-panel__section">
        <div className="risk-side-panel__section-title">日内风控</div>
        <div className="risk-side-panel__kpis">
          <div className="risk-side-panel__kpi">
            <span className="risk-side-panel__kpi-label">今日拦截</span>
            <span className="risk-side-panel__kpi-value">{RISK_STATUS.todayBlocked}</span>
          </div>
          <div className="risk-side-panel__kpi">
            <span className="risk-side-panel__kpi-label">活跃告警</span>
            <span className="risk-side-panel__kpi-value" style={{ color: RISK_STATUS.activeAlerts > 0 ? 'var(--color-warning)' : 'var(--color-fall)' }}>{RISK_STATUS.activeAlerts}</span>
          </div>
          <div className="risk-side-panel__kpi">
            <span className="risk-side-panel__kpi-label">活跃规则</span>
            <span className="risk-side-panel__kpi-value">{RISK_STATUS.activeRules}</span>
          </div>
        </div>
      </div>

      <div className="risk-side-panel__section">
        <Button
          size="small"
          icon={<History size={12} />}
          onClick={onOpenHistory}
          block
          style={{ fontSize: 12, fontWeight: 500 }}
        >
          查看历史信号
        </Button>
      </div>

      <div className="risk-side-panel__section">
        <div className="risk-side-panel__section-title risk-side-panel__section-title--clickable" onClick={() => setShowRules(!showRules)}>
          <span>风控规则 ({RISK_RULES.length})</span>
          <span style={{ fontSize: 10, color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: 2 }}>
            {showRules ? <ChevronDown size={10} /> : <ChevronRight size={10} />}
            {showRules ? '收起' : '展开'}
          </span>
        </div>
        {showRules && (
          <Table dataSource={RISK_RULES} columns={ruleColumns} rowKey="code" size="small" pagination={false} showHeader={false} />
        )}
      </div>
    </div>
  );
}
