import { useState, useEffect, useCallback } from 'react';
import { Tag, Button, Space, message, Modal, Form, InputNumber, Select, Input } from 'antd';
import { Zap, ArrowRight, History, AlertTriangle } from 'lucide-react';
import { ApiError } from '@/api/types';
import {
  approvePreOrder,
  batchApprovePreOrders,
  fetchPreOrders,
  fetchRiskEvents,
  runAccountDecisionWorkflow,
  updatePreOrder,
  type PreOrder,
  type SignalDetail,
  type RiskEvent,
} from '@/api/trading';
import { SIGNAL_SIDE_LABEL, SIGNAL_SIDE_COLOR } from '../utils/trading';

function formatWeight(value: number | null) {
  if (value === null || value === undefined) return '—';
  return `${(Number(value) * 100).toFixed(2)}%`;
}

// 信号方向标签与颜色
const DIRECTION_LABEL: Record<string, string> = { long: '看多', short: '看空', neutral: '中性' }
const DIRECTION_COLOR: Record<string, string> = { long: 'var(--color-rise)', short: 'var(--color-fall)', neutral: 'default' }

function formatPct(value: number | null) {
  if (value === null || value === undefined) return '—'
  return `${(Number(value) * 100).toFixed(0)}%`
}

interface ApprovalFormValues {
  target_qty?: number | null
  target_weight?: number | null
  order_type: 'limit' | 'market'
  limit_price?: number | null
  comment?: string
}

// 信号依据区域
function SignalDetailSection({ detail }: { detail: SignalDetail }) {
  return (
    <div className="signal-card__signal-detail">
      <div className="signal-card__metric">
        <span className="signal-card__metric-label">方向</span>
        <span className="signal-card__metric-value">
          <Tag color={DIRECTION_COLOR[detail.direction] ?? 'default'} style={{ fontSize: 11, padding: '0 6px', borderRadius: 4, fontWeight: 600 }}>
            {DIRECTION_LABEL[detail.direction] ?? detail.direction}
          </Tag>
        </span>
      </div>
      <div className="signal-card__metric">
        <span className="signal-card__metric-label">置信度</span>
        <span className="signal-card__metric-value">{formatPct(detail.confidence)}</span>
      </div>
      <div className="signal-card__metric">
        <span className="signal-card__metric-label">强度</span>
        <span className="signal-card__metric-value">{formatPct(detail.strength)}</span>
      </div>
      <div className="signal-card__metric">
        <span className="signal-card__metric-label">融合得分</span>
        <span className="signal-card__metric-value">{detail.fused_score ?? '—'}</span>
      </div>
      {detail.reason && (
        <div className="signal-card__metric" style={{ gridColumn: '1 / -1' }}>
          <span className="signal-card__metric-label">原因</span>
          <span className="signal-card__metric-value" style={{ overflow: 'hidden', display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', textOverflow: 'ellipsis' }}>{detail.reason}</span>
        </div>
      )}
      {detail.entry_price_detail && (
        <div className="signal-card__metric" style={{ gridColumn: '1 / -1' }}>
          <span className="signal-card__metric-label">入场依据</span>
          <span className="signal-card__metric-value--secondary" style={{ fontSize: 10 }}>
            收盘{String(detail.entry_price_detail.close ?? '—')}
            {' / '}
            ATR{String(detail.entry_price_detail.atr_14 ?? '—')}
            {' / '}
            缓冲{formatPct(
              detail.entry_price_detail.buffer_ratio == null
                ? null
                : Number(detail.entry_price_detail.buffer_ratio),
            )}
          </span>
        </div>
      )}
      {detail.strategy_id && (
        <div className="signal-card__metric" style={{ gridColumn: '1 / -1' }}>
          <span className="signal-card__metric-label">策略</span>
          <span className="signal-card__metric-value--secondary" style={{ fontSize: 10 }}>{detail.strategy_id}</span>
        </div>
      )}
    </div>
  )
}

function buildRiskAlertText(event: RiskEvent) {
  const symbol = typeof event.detail?.symbol === 'string' ? event.detail.symbol : '账户';
  const reasons = Array.isArray(event.detail?.reasons) ? event.detail.reasons.join(',') : event.event_type;
  return `${symbol} ${reasons}`;
}

function RiskAlertMarquee({ alerts }: { alerts: RiskEvent[] }) {
  if (alerts.length === 0) return null;
  const items = alerts.map(buildRiskAlertText);
  const doubled = [...items, ...items];
  return (
    <div className="risk-alert-marquee" data-component="Risk Alert Marquee">
      <AlertTriangle size={13} style={{ color: 'var(--color-warning)', flexShrink: 0 }} />
      <div className="risk-alert-marquee__track">
        <div className="risk-alert-marquee__content">
          {doubled.map((text, i) => (
            <span key={`${text}-${i}`} className="risk-alert-marquee__item">{text}</span>
          ))}
        </div>
      </div>
      <Tag color="warning" style={{ fontSize: 10, fontWeight: 600, flexShrink: 0 }}>{items.length}条告警</Tag>
    </div>
  );
}

interface SignalApprovalTabProps {
  accountId: number | null;
  onOpenHistory: () => void;
}

export function SignalApprovalTab({ accountId, onOpenHistory }: SignalApprovalTabProps) {
  const [preOrders, setPreOrders] = useState<PreOrder[]>([]);
  const [riskEvents, setRiskEvents] = useState<RiskEvent[]>([]);
  const [loading, setLoading] = useState(false);
  const [workflowRunning, setWorkflowRunning] = useState(false);
  const [approvalTarget, setApprovalTarget] = useState<PreOrder | null>(null);
  const [approvalSubmitting, setApprovalSubmitting] = useState(false);
  const [approvalForm] = Form.useForm<ApprovalFormValues>();

  const reloadPendingData = useCallback(async (targetAccountId: number) => {
    const [preOrderRes, riskEventRes] = await Promise.all([
      fetchPreOrders({ account_id: targetAccountId, status: 'pending_approval', approval_status: 'pending', page_size: 100 }),
      fetchRiskEvents({ account_id: targetAccountId, resolved: false, page_size: 20 }),
    ]);
    setPreOrders(preOrderRes.items);
    setRiskEvents(riskEventRes.items);
    return preOrderRes.items;
  }, []);

  useEffect(() => {
    let cancelled = false;
    Promise.resolve().then(() => {
      if (cancelled) return undefined;
      if (accountId === null) {
        setPreOrders([]);
        setRiskEvents([]);
        setLoading(false);
        return undefined;
      }

      setLoading(true);
      return reloadPendingData(accountId).then(() => {
        if (cancelled) return;
      }).catch(() => {
        if (!cancelled) message.error('待审批信号加载失败');
      }).finally(() => {
        if (!cancelled) setLoading(false);
      });
    });
    return () => { cancelled = true; };
  }, [accountId, reloadPendingData]);

  const handleRunWorkflow = useCallback(async () => {
    if (accountId === null) return;
    setWorkflowRunning(true);
    try {
      const result = await runAccountDecisionWorkflow(accountId);
      const items = await reloadPendingData(accountId);
      const runItems = items.filter(item => item.workflow_run_id === result.run.run_id);
      if (result.run.status !== 'succeeded') {
        message.error(`工作流未成功结束: ${result.run.status}`);
        return;
      }
      if (result.pre_orders_count !== runItems.length) {
        message.error('工作流结果与页面待审批数据不一致');
        return;
      }
      message.success(`工作流完成，生成 ${runItems.length} 条待审批信号`);
    } catch (error) {
      message.error(error instanceof ApiError ? error.message : '手动运行工作流失败');
    } finally {
      setWorkflowRunning(false);
    }
  }, [accountId, reloadPendingData]);

  const openApprovalDialog = useCallback((po: PreOrder) => {
    setApprovalTarget(po);
    approvalForm.setFieldsValue({
      target_qty: po.target_qty,
      target_weight: po.target_weight === null ? null : Number((Number(po.target_weight) * 100).toFixed(4)),
      order_type: po.order_type,
      limit_price: po.limit_price === null ? null : Number(po.limit_price),
      comment: po.approval_comment ?? '',
    });
  }, [approvalForm]);

  const handleConfirmApproval = useCallback(async () => {
    if (approvalTarget === null) return;
    const values = await approvalForm.validateFields();
    setApprovalSubmitting(true);
    try {
      await updatePreOrder(approvalTarget.id, {
        target_qty: values.target_qty ?? null,
        target_weight: values.target_weight == null ? null : Number(values.target_weight) / 100,
        order_type: values.order_type,
        limit_price: values.order_type === 'market'
          ? null
          : (values.limit_price == null ? null : values.limit_price.toFixed(4)),
      });
      await approvePreOrder(approvalTarget.id, {
        approved: true,
        approved_by: 'user',
        comment: values.comment ?? '',
      });
      setPreOrders(prev => prev.filter(po => po.id !== approvalTarget.id));
      setApprovalTarget(null);
      message.success('已批准');
    } catch (error) {
      message.error(error instanceof ApiError ? error.message : '审批失败');
    } finally {
      setApprovalSubmitting(false);
    }
  }, [approvalForm, approvalTarget]);

  const handleReject = useCallback(async (preOrderId: number) => {
    try {
      await approvePreOrder(preOrderId, { approved: false, approved_by: 'user' });
      setPreOrders(prev => prev.filter(po => po.id !== preOrderId));
      message.success('已拒绝');
    } catch (error) {
      message.error(error instanceof ApiError ? error.message : '操作失败');
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
            <Button
              size="small"
              icon={<Zap size={12} />}
              onClick={handleRunWorkflow}
              disabled={accountId === null}
              loading={workflowRunning}
            >
              手动运行工作流
            </Button>
            <Button size="small" icon={<History size={12} />} onClick={onOpenHistory}>历史信号</Button>
            <Button size="small" danger onClick={handleBatchReject} disabled={preOrders.length === 0}>
              全部拒绝
            </Button>
            <Button type="primary" size="small" icon={<Zap size={12} />} onClick={handleBatchApprove} disabled={preOrders.length === 0} loading={loading}>
              批量批准 ({preOrders.length})
            </Button>
          </Space>
        </div>

        <RiskAlertMarquee alerts={riskEvents} />

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
                {po.signal_detail && <SignalDetailSection detail={po.signal_detail} />}
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
                    目标{formatWeight(po.target_weight)}
                    <span style={{ color: 'var(--text-muted)', fontSize: 10 }}> 当前{formatWeight(po.current_weight)}</span>
                  </span>
                </div>
                <div className="signal-card__metric">
                  <span className="signal-card__metric-label">配仓</span>
                  <span className="signal-card__metric-value--secondary">{po.sizing_strategy || '—'}</span>
                </div>
              </div>
              <div className="signal-card__action">
                <Space size={4}>
                  <Button size="small" danger onClick={() => handleReject(po.id)}>拒绝</Button>
                  <Button size="small" type="primary" onClick={() => openApprovalDialog(po)}>批准</Button>
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

      <Modal
        title={approvalTarget ? `审批信号 ${approvalTarget.symbol}` : '审批信号'}
        open={approvalTarget !== null}
        onCancel={() => setApprovalTarget(null)}
        onOk={handleConfirmApproval}
        okText="确认批准"
        cancelText="取消"
        confirmLoading={approvalSubmitting}
        destroyOnHidden
      >
        <Form form={approvalForm} layout="vertical">
          <Form.Item name="target_qty" label="目标数量(股)">
            <InputNumber min={0} precision={0} step={100} style={{ width: '100%' }} placeholder="目标股数" />
          </Form.Item>
          <Form.Item name="target_weight" label="目标仓位(%)" rules={[{ required: true, message: '请输入目标仓位' }]}>
            <InputNumber min={0} max={100} precision={4} style={{ width: '100%' }} placeholder="目标仓位百分比" />
          </Form.Item>
          <Form.Item name="order_type" label="订单类型" rules={[{ required: true, message: '请选择订单类型' }]}>
            <Select options={[{ value: 'limit', label: '限价' }, { value: 'market', label: '市价' }]} />
          </Form.Item>
          <Form.Item noStyle shouldUpdate={(prev, curr) => prev.order_type !== curr.order_type}>
            {({ getFieldValue }) => getFieldValue('order_type') === 'limit' ? (
              <Form.Item name="limit_price" label="限价" rules={[{ required: true, message: '请输入限价' }]}>
                <InputNumber min={0.0001} precision={4} style={{ width: '100%' }} placeholder="委托限价" />
              </Form.Item>
            ) : null}
          </Form.Item>
          <Form.Item name="comment" label="审批意见">
            <Input.TextArea rows={2} maxLength={256} placeholder="可填写调价或调仓原因" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
