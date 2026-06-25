import { useState, useMemo, useEffect, useCallback } from 'react';
import { Table, Tag, Switch, Badge, Button, message } from 'antd';
import { Shield, Flame, CheckCircle, ChevronDown, ChevronRight, History } from 'lucide-react';
import {
  enableAccountKillSwitch,
  fetchRiskEvents,
  fetchRiskRules,
  resolveRiskEvent,
  updateRiskRule,
  type RiskEvent,
  type RiskRule,
} from '@/api/trading';
import { RISK_LEVEL_TAG } from '../utils/trading';

interface RiskSidePanelProps {
  accountId: number | null;
  onOpenHistory: () => void;
}

function eventDetailText(event: RiskEvent) {
  const symbol = typeof event.detail?.symbol === 'string' ? event.detail.symbol : '';
  const reasons = Array.isArray(event.detail?.reasons) ? event.detail.reasons.join(',') : event.event_type;
  return symbol ? `${symbol} ${reasons}` : reasons;
}

export function RiskSidePanel({ accountId, onOpenHistory }: RiskSidePanelProps) {
  const [showRules, setShowRules] = useState(false);
  const [rules, setRules] = useState<RiskRule[]>([]);
  const [events, setEvents] = useState<RiskEvent[]>([]);

  useEffect(() => {
    let cancelled = false;
    Promise.resolve().then(() => {
      const eventRequest = accountId === null
        ? Promise.resolve({ items: [], total: 0, page: 1, page_size: 20 })
        : fetchRiskEvents({ account_id: accountId, resolved: false, page_size: 20 });

      return Promise.all([fetchRiskRules(), eventRequest]).then(([ruleRes, eventRes]) => {
        if (cancelled) return;
        setRules(ruleRes.items ?? []);
        setEvents(eventRes.items ?? []);
      }).catch(() => {
        if (!cancelled) message.error('风控数据加载失败');
      });
    });
    return () => { cancelled = true; };
  }, [accountId]);

  const handleToggleRule = useCallback(async (ruleId: number, enabled: boolean) => {
    try {
      const updated = await updateRiskRule(ruleId, { is_enabled: enabled });
      setRules(prev => prev.map(r => r.id === ruleId ? updated : r));
    } catch {
      message.error('更新失败');
    }
  }, []);

  const handleResolveEvent = useCallback(async (eventId: number) => {
    try {
      const updated = await resolveRiskEvent(eventId, { resolved_by: 'user' });
      setEvents(prev => prev.filter(item => item.id !== updated.id));
      message.success('告警已处理');
    } catch {
      message.error('处理失败');
    }
  }, []);

  const handleKillSwitch = useCallback(async () => {
    if (accountId === null) return;
    try {
      await enableAccountKillSwitch(accountId);
      const eventRes = await fetchRiskEvents({ account_id: accountId, resolved: false, page_size: 20 });
      setEvents(eventRes.items ?? []);
      message.success('已启用紧急只减仓');
    } catch {
      message.error('紧急全平失败');
    }
  }, [accountId]);

  const enabledCount = rules.filter(r => r.is_enabled).length;
  const activeAlerts = events.length;
  const circuitBreakerTriggered = events.some(e => e.event_type === 'circuit_breaker' || e.level === 'fatal');

  const ruleColumns = useMemo(() => [
    { title: '规则', dataIndex: 'rule_code', width: 105, render: (v: string) => <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10 }}>{v}</span> },
    { title: '类别', dataIndex: 'category', width: 55, render: (v: string) => {
      const labels: Record<string, string> = { circuit_breaker: '熔断', position: '仓位', capital: '资金', timing: '时段' };
      return <span style={{ fontSize: 10, color: 'var(--text-secondary)' }}>{labels[v] || v}</span>;
    }},
    { title: '级', dataIndex: 'level', width: 35, render: (v: 'info' | 'warn' | 'critical' | 'fatal') => <Tag color={RISK_LEVEL_TAG[v]} style={{ fontSize: 9, padding: '0 3px', margin: 0, lineHeight: '16px' }}>{v}</Tag> },
    { title: '参数', dataIndex: 'params', width: 70, render: (v: Record<string, unknown>) => <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10 }}>{v ? JSON.stringify(v) : '—'}</span> },
    { title: '', dataIndex: 'is_enabled', width: 35, render: (v: boolean, _: unknown, idx: number) => {
      const rule = rules[idx];
      return <Switch checked={v} size="small" onChange={(checked) => rule && handleToggleRule(rule.id, checked)} />;
    }},
  ], [rules, handleToggleRule]);

  const eventColumns = useMemo(() => [
    { title: '级别', dataIndex: 'level', width: 58, render: (v: 'info' | 'warn' | 'critical' | 'fatal') => <Tag color={RISK_LEVEL_TAG[v]} style={{ fontSize: 9, padding: '0 4px', margin: 0 }}>{v}</Tag> },
    { title: '告警', width: 150, render: (_: unknown, r: RiskEvent) => <span style={{ fontSize: 10 }}>{eventDetailText(r)}</span> },
    { title: '', width: 45, render: (_: unknown, r: RiskEvent) => <Button size="small" type="link" onClick={() => handleResolveEvent(r.id)} style={{ fontSize: 10, padding: 0 }}>处理</Button> },
  ], [handleResolveEvent]);

  const statusColor = activeAlerts > 0 ? 'var(--color-warning)' : 'var(--color-fall)';
  const statusText = activeAlerts > 0 ? '风控告警' : '风控正常';

  return (
    <div className={`risk-side-panel ${activeAlerts > 0 ? 'risk-side-panel--warning' : ''}`} data-component="Risk Side Panel">
      <div className="risk-side-panel__header">
        <div className="risk-side-panel__status">
          <Shield size={16} style={{ color: statusColor }} />
          <span className="risk-side-panel__status-text" style={{ color: statusColor }}>
            {statusText}
          </span>
          {activeAlerts > 0 && (
            <Badge count={activeAlerts} size="small" style={{ backgroundColor: 'var(--color-warning)' }} />
          )}
        </div>
        <button
          className="risk-side-panel__kill-btn"
          data-component="Kill Switch Button"
          disabled={accountId === null}
          onClick={handleKillSwitch}
        >
          <Flame size={13} />
          <span>紧急全平</span>
        </button>
      </div>

      <div className="risk-side-panel__section">
        <div className="risk-side-panel__section-title">熔断器</div>
        <div className="risk-side-panel__circuit">
          <div className="risk-side-panel__circuit-top">
            <CheckCircle size={18} style={{ color: circuitBreakerTriggered ? 'var(--color-warning)' : 'var(--color-fall)' }} />
            <span style={{ color: circuitBreakerTriggered ? 'var(--color-warning)' : 'var(--color-fall)', fontWeight: 700, fontSize: 13 }}>
              {circuitBreakerTriggered ? '已触发' : '未触发'}
            </span>
          </div>
        </div>
      </div>

      <div className="risk-side-panel__section">
        <div className="risk-side-panel__section-title">日内风控</div>
        <div className="risk-side-panel__kpis">
          <div className="risk-side-panel__kpi">
            <span className="risk-side-panel__kpi-label">活跃告警</span>
            <span className="risk-side-panel__kpi-value" style={{ color: activeAlerts > 0 ? 'var(--color-warning)' : 'var(--color-fall)' }}>{activeAlerts}</span>
          </div>
          <div className="risk-side-panel__kpi">
            <span className="risk-side-panel__kpi-label">活跃规则</span>
            <span className="risk-side-panel__kpi-value">{enabledCount}</span>
          </div>
        </div>
      </div>

      {events.length > 0 && (
        <div className="risk-side-panel__section">
          <div className="risk-side-panel__section-title">风控告警 ({events.length})</div>
          <Table dataSource={events} columns={eventColumns} rowKey="id" size="small" pagination={false} showHeader={false} />
        </div>
      )}

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
          <span>风控规则 ({rules.length})</span>
          <span style={{ fontSize: 10, color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: 2 }}>
            {showRules ? <ChevronDown size={10} /> : <ChevronRight size={10} />}
            {showRules ? '收起' : '展开'}
          </span>
        </div>
        {showRules && (
          <Table dataSource={rules} columns={ruleColumns} rowKey="id" size="small" pagination={false} showHeader={false} />
        )}
      </div>
    </div>
  );
}
