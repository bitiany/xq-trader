import { useState, useMemo, useEffect, useCallback } from 'react';
import { App, Table, Tag, Switch, Badge, Button, Modal, Input, Spin } from 'antd';
import { Shield, Flame, CheckCircle, ChevronDown, ChevronRight, History } from 'lucide-react';
import {
  enableAccountKillSwitch,
  fetchRiskEvents,
  fetchRiskRules,
  resolveRiskEvent,
  updateRiskRule,
  type KillSwitchResult,
  type RiskEvent,
  type RiskRule,
} from '@/api/trading';
import { DEFAULT_OPERATOR, RISK_LEVEL_TAG } from '../utils/trading';

interface RiskSidePanelProps {
  accountId: number | null;
  instanceId: number | null;
  onOpenHistory: () => void;
}

function eventDetailText(event: RiskEvent) {
  if (event.display?.summary) return event.display.summary;
  const symbol = typeof event.detail?.symbol === 'string' ? event.detail.symbol : '账户级';
  const reasonText = event.display?.reasons_text ?? event.event_type;
  return `${symbol}：${reasonText}`;
}

export function RiskSidePanel({ accountId, instanceId, onOpenHistory }: RiskSidePanelProps) {
  const { message } = App.useApp();
  const [showRules, setShowRules] = useState(false);
  const [rules, setRules] = useState<RiskRule[]>([]);
  const [events, setEvents] = useState<RiskEvent[]>([]);
  const [loading, setLoading] = useState(false);
  const [killSwitchRunning, setKillSwitchRunning] = useState(false);

  useEffect(() => {
    let cancelled = false;
    Promise.resolve().then(() => {
      if (accountId === null) {
        setRules([]);
        setEvents([]);
        setLoading(false);
        return undefined;
      }

      setLoading(true);
      const eventRequest = fetchRiskEvents({
        account_id: accountId,
        instance_id: instanceId ?? undefined,
        resolved: false,
        page_size: 20,
      });

      return Promise.all([fetchRiskRules(), eventRequest]).then(([ruleRes, eventRes]) => {
        if (cancelled) return;
        setRules(ruleRes.items ?? []);
        setEvents(eventRes.items ?? []);
      }).catch(() => {
        if (!cancelled) message.error('风控数据加载失败');
      }).finally(() => {
        if (!cancelled) setLoading(false);
      });
    });
    return () => { cancelled = true; };
  }, [accountId, instanceId]);

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

  const showKillSwitchResult = useCallback((result: KillSwitchResult) => {
    const cancelSucceeded = result.cancelled_orders.filter(o => o.status === 'cancel_succeeded').length;
    const cancelFailed = result.cancelled_orders.length - cancelSucceeded;
    const closeSucceeded = result.close_orders.filter(o => o.status === 'submitted').length;
    const closeFailed = result.close_orders.length - closeSucceeded;
    const summary = [
      `撤单: ${cancelSucceeded}/${result.cancelled_orders.length} 成功` +
        (cancelFailed > 0 ? ` (${cancelFailed} 失败)` : ''),
      `平仓: ${closeSucceeded}/${result.close_orders.length} 成功` +
        (closeFailed > 0 ? ` (${closeFailed} 失败)` : ''),
    ].join(' | ');
    if (closeFailed > 0 || cancelFailed > 0) {
      message.warning(summary);
    } else {
      message.success(summary);
    }
  }, []);

  const handleKillSwitch = useCallback(() => {
    if (accountId === null) return;
    let reasonInput = 'manual_kill_switch';
    Modal.confirm({
      title: '账户紧急全平',
      content: (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 8 }}>
          <div style={{ fontSize: 12, color: 'var(--text-warning)' }}>
            将设置账户为仅减仓、取消所有挂单、并对所有持仓发起市价平仓委托。请确认。
          </div>
          <Input
            placeholder="触发原因 (默认 manual_kill_switch)"
            defaultValue={reasonInput}
            onChange={(e) => { reasonInput = e.target.value || 'manual_kill_switch'; }}
          />
        </div>
      ),
      okText: '确认全平',
      okType: 'danger',
      cancelText: '取消',
      onOk: async () => {
        setKillSwitchRunning(true);
        try {
          const result = await enableAccountKillSwitch(accountId, {
            operator: DEFAULT_OPERATOR,
            reason: reasonInput,
          });
          showKillSwitchResult(result);
          const eventRes = await fetchRiskEvents({
            account_id: accountId,
            instance_id: instanceId ?? undefined,
            resolved: false,
            page_size: 20,
          });
          setEvents(eventRes.items ?? []);
        } catch {
          message.error('紧急全平失败');
          throw new Error('kill switch failed');
        } finally {
          setKillSwitchRunning(false);
        }
      },
    });
  }, [accountId, instanceId, showKillSwitchResult]);

  const enabledCount = rules.filter(r => r.is_enabled).length;
  const activeAlerts = events.length;
  const circuitBreakerTriggered = events.some(e => e.event_type === 'circuit_breaker' || e.level === 'fatal');

  const ruleColumns = useMemo(() => [
    { title: '规则', dataIndex: 'rule_code', width: 105, render: (v: string) => <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10 }}>{v}</span> },
    { title: '类别', dataIndex: 'category', width: 55, render: (v: string) => {
      const labels: Record<string, string> = { circuit_breaker: '熔断', position: '仓位', capital: '资金', timing: '时段' };
      return <span style={{ fontSize: 10, color: 'var(--text-secondary)' }}>{labels[v] || v}</span>;
    }},
    { title: '级', dataIndex: 'level', width: 35, render: (v: 'info' | 'warn' | 'critical' | 'fatal') => {
      const labels: Record<string, string> = { info: '提示', warn: '警告', critical: '严重', fatal: '致命' };
      return <Tag color={RISK_LEVEL_TAG[v]} style={{ fontSize: 9, padding: '0 3px', margin: 0, lineHeight: '16px' }}>{labels[v] ?? v}</Tag>;
    }},
    { title: '参数', dataIndex: 'params', width: 70, render: (v: Record<string, unknown>) => <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10 }}>{v ? JSON.stringify(v) : '—'}</span> },
    { title: '', dataIndex: 'is_enabled', width: 35, render: (v: boolean, _: unknown, idx: number) => {
      const rule = rules[idx];
      return <Switch checked={v} size="small" onChange={(checked) => rule && handleToggleRule(rule.id, checked)} />;
    }},
  ], [rules, handleToggleRule]);

  const eventColumns = useMemo(() => [
    { title: '级别', dataIndex: 'level', width: 58, render: (v: 'info' | 'warn' | 'critical' | 'fatal', r: RiskEvent) => <Tag color={RISK_LEVEL_TAG[v]} style={{ fontSize: 9, padding: '0 4px', margin: 0 }}>{r.display?.level_label ?? v}</Tag> },
    { title: '告警', width: 150, render: (_: unknown, r: RiskEvent) => <span style={{ fontSize: 10 }}>{eventDetailText(r)}</span> },
    { title: '', width: 45, render: (_: unknown, r: RiskEvent) => <Button size="small" type="link" onClick={() => handleResolveEvent(r.id)} style={{ fontSize: 10, padding: 0 }}>处理</Button> },
  ], [handleResolveEvent]);

  const statusColor = activeAlerts > 0 ? 'var(--color-warning)' : 'var(--color-fall)';
  const statusText = activeAlerts > 0 ? '风控告警' : '风控正常';

  return (
    <Spin spinning={loading}>
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
            disabled={accountId === null || killSwitchRunning}
            onClick={handleKillSwitch}
          >
            <Flame size={13} />
            <span>{killSwitchRunning ? '执行中…' : '紧急全平'}</span>
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
          <div style={{ fontSize: 10, color: 'var(--text-muted)', lineHeight: 1.5, marginBottom: 6 }}>
            这里展示账户未处理风控事件；当前待审批信号以卡片上的“风控预检”为准，二者不必然矛盾。
          </div>
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
    </Spin>
  );
}
