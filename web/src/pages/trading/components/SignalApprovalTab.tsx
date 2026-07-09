import { useState, useEffect, useCallback } from 'react';
import { App, Tag, Button, Space, Modal, Form, InputNumber, Select, Input, Spin } from 'antd';
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
import {
  DEFAULT_OPERATOR,
  DIRECTION_COLOR,
  DIRECTION_LABEL,
  SIGNAL_SIDE_LABEL,
  SIGNAL_SIDE_COLOR,
} from '../utils/trading';

function formatWeight(value: number | null) {
  if (value === null || value === undefined) return '—';
  return `${(Number(value) * 100).toFixed(2)}%`;
}

function formatPct(value: number | null) {
  if (value === null || value === undefined) return '—'
  return `${(Number(value) * 100).toFixed(0)}%`
}

interface ApprovalFormValues {
  target_qty?: number | null
  target_weight?: number | null
  order_type: 'limit' | 'market'
  price_mode: 'manual' | 'atr_offset'
  limit_price?: number | null
  atr_multiplier?: number | null
  slippage_type?: 'none' | 'percent' | 'tick' | 'atr'
  slippage_rate?: number | null
  slippage_ticks?: number | null
  slippage_atr_multiplier?: number | null
  comment?: string
}

// 信号依据区域
function SignalDetailSection({ detail }: { detail: SignalDetail }) {
  return (
    <div className="signal-card__signal-detail">
      <div className="signal-card__metric">
        <span className="signal-card__metric-label">策略方向</span>
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
  if (event.display?.summary) return event.display.summary;
  const symbol = typeof event.detail?.symbol === 'string' ? event.detail.symbol : '账户级';
  const reasons = event.display?.reasons_text ?? event.event_type;
  return `${symbol}：${reasons}`;
}

function numberFromDetail(detail: Record<string, unknown> | null | undefined, key: string) {
  if (!detail) return null;
  const value = detail[key];
  if (value === null || value === undefined || value === '') return null;
  const num = Number(value);
  return Number.isFinite(num) ? num : null;
}

function getEntryPriceDetail(po: PreOrder) {
  return po.signal_detail?.entry_price_detail ?? null;
}

function calculateAtrLimitPrice(po: PreOrder, multiplier: number | null | undefined) {
  const detail = getEntryPriceDetail(po);
  const close = numberFromDetail(detail, 'close');
  const atr = numberFromDetail(detail, 'atr_14');
  if (close === null || atr === null) return null;
  const direction = po.side === 'open' || po.side === 'add' ? 1 : -1;
  return Number((close + direction * atr * Number(multiplier ?? 0)).toFixed(4));
}

function buildSlippage(values: ApprovalFormValues, po: PreOrder): Record<string, unknown> {
  const slippageType = values.slippage_type ?? 'none';
  if (slippageType === 'percent') {
    return { type: slippageType, rate: Number(values.slippage_rate ?? 0) / 100 };
  }
  if (slippageType === 'tick') {
    return { type: slippageType, ticks: Number(values.slippage_ticks ?? 0), tick_size: 0.01 };
  }
  if (slippageType === 'atr') {
    const atr = numberFromDetail(getEntryPriceDetail(po), 'atr_14') ?? 0;
    return { type: slippageType, multiplier: Number(values.slippage_atr_multiplier ?? 0), atr };
  }
  return { type: 'none' };
}

function riskPrecheckTag(po: PreOrder) {
  if (po.risk_check_passed === true) return <Tag color="success" style={{ fontSize: 10 }}>风控预检通过</Tag>;
  if (po.risk_check_passed === false) return <Tag color="error" style={{ fontSize: 10 }}>风控预检未通过</Tag>;
  return <Tag color="default" style={{ fontSize: 10 }}>风控预检未知</Tag>;
}

function RiskAlertMarquee({ alerts }: { alerts: RiskEvent[] }) {
  if (alerts.length === 0) return null;
  const items = alerts.map(buildRiskAlertText);
  const doubled = [...items, ...items];
  return (
    <div>
      <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 6 }}>
        这里展示账户未处理风控事件；当前待审批信号以卡片上的“风控预检”为准，二者不必然矛盾。
      </div>
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
    </div>
  );
}

interface SignalApprovalTabProps {
  accountId: number | null;
  instanceId: number | null;
  onInstanceChange: (instanceId: number | null) => void;
  onOpenHistory: () => void;
}

export function SignalApprovalTab({
  accountId,
  instanceId,
  onInstanceChange,
  onOpenHistory,
}: SignalApprovalTabProps) {
  const { message } = App.useApp();
  const [preOrders, setPreOrders] = useState<PreOrder[]>([]);
  const [riskEvents, setRiskEvents] = useState<RiskEvent[]>([]);
  const [loading, setLoading] = useState(false);
  const [workflowRunning, setWorkflowRunning] = useState(false);
  const [batchSubmitting, setBatchSubmitting] = useState(false);
  const [rejectingId, setRejectingId] = useState<number | null>(null);
  const [approvalTarget, setApprovalTarget] = useState<PreOrder | null>(null);
  const [approvalSubmitting, setApprovalSubmitting] = useState(false);
  const [approvalForm] = Form.useForm<ApprovalFormValues>();

  const reloadPendingData = useCallback(async (targetAccountId: number, targetInstanceId?: number | null) => {
    const [preOrderRes, riskEventRes] = await Promise.all([
      fetchPreOrders({
        account_id: targetAccountId,
        instance_id: targetInstanceId ?? undefined,
        status: 'pending_approval',
        approval_status: 'pending',
        page_size: 100,
      }),
      fetchRiskEvents({
        account_id: targetAccountId,
        instance_id: targetInstanceId ?? undefined,
        resolved: false,
        page_size: 20,
      }),
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
      return reloadPendingData(accountId, instanceId).then(() => {
        if (cancelled) return;
      }).catch(() => {
        if (!cancelled) message.error('待审批信号加载失败');
      }).finally(() => {
        if (!cancelled) setLoading(false);
      });
    });
    return () => { cancelled = true; };
  }, [accountId, instanceId, reloadPendingData]);

  const handleRunWorkflow = useCallback(async () => {
    if (accountId === null) return;
    setWorkflowRunning(true);
    try {
      const result = await runAccountDecisionWorkflow(accountId);
      onInstanceChange(result.instance_id);
      const items = await reloadPendingData(accountId, result.instance_id);
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
  }, [accountId, onInstanceChange, reloadPendingData]);

  const openApprovalDialog = useCallback((po: PreOrder) => {
    setApprovalTarget(po);
    approvalForm.setFieldsValue({
      target_qty: po.target_qty,
      target_weight: po.target_weight === null ? null : Number((Number(po.target_weight) * 100).toFixed(4)),
      order_type: po.order_type,
      price_mode: 'manual',
      limit_price: po.limit_price === null ? null : Number(po.limit_price),
      atr_multiplier: 0,
      slippage_type: 'none',
      slippage_rate: 0.1,
      slippage_ticks: 1,
      slippage_atr_multiplier: 0.1,
      comment: po.approval_comment ?? '',
    });
  }, [approvalForm]);

  const handleConfirmApproval = useCallback(async () => {
    if (approvalTarget === null) return;
    const values = await approvalForm.validateFields();
    const limitPrice = values.order_type === 'market'
      ? null
      : values.price_mode === 'atr_offset'
        ? calculateAtrLimitPrice(approvalTarget, values.atr_multiplier)
        : values.limit_price;
    if (values.order_type === 'limit' && limitPrice === null) {
      message.error('无法根据 ATR 计算限价，请改用手动价格');
      return;
    }
    setApprovalSubmitting(true);
    try {
      await updatePreOrder(approvalTarget.id, {
        target_qty: values.target_qty ?? null,
        target_weight: values.target_weight == null ? null : Number(values.target_weight) / 100,
        order_type: values.order_type,
        limit_price: values.order_type === 'market' ? null : limitPrice?.toFixed(4),
        approval_execution: {
          price_mode: values.order_type === 'market' ? 'market' : values.price_mode,
          atr_multiplier: values.price_mode === 'atr_offset' ? Number(values.atr_multiplier ?? 0) : null,
          slippage: buildSlippage(values, approvalTarget),
        },
      });
      await approvePreOrder(approvalTarget.id, {
        approved: true,
        approved_by: DEFAULT_OPERATOR,
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
    setRejectingId(preOrderId);
    try {
      await approvePreOrder(preOrderId, { approved: false, approved_by: DEFAULT_OPERATOR });
      setPreOrders(prev => prev.filter(po => po.id !== preOrderId));
      message.success('已拒绝');
    } catch (error) {
      message.error(error instanceof ApiError ? error.message : '操作失败');
    } finally {
      setRejectingId(null);
    }
  }, []);

  const handleBatchApprove = useCallback(async () => {
    if (preOrders.length === 0) return;
    setBatchSubmitting(true);
    try {
      const result = await batchApprovePreOrders({
        pre_order_ids: preOrders.map(po => po.id),
        approved: true,
        approved_by: DEFAULT_OPERATOR,
      });
      message.success(`批量批准: ${result.approved}条`);
      setPreOrders([]);
    } catch (error) {
      message.error(error instanceof ApiError ? error.message : '批量审批失败');
    } finally {
      setBatchSubmitting(false);
    }
  }, [preOrders]);

  const handleBatchReject = useCallback(async () => {
    if (preOrders.length === 0) return;
    setBatchSubmitting(true);
    try {
      const result = await batchApprovePreOrders({
        pre_order_ids: preOrders.map(po => po.id),
        approved: false,
        approved_by: DEFAULT_OPERATOR,
      });
      message.success(`批量拒绝: ${result.rejected}条`);
      setPreOrders([]);
    } catch (error) {
      message.error(error instanceof ApiError ? error.message : '批量审批失败');
    } finally {
      setBatchSubmitting(false);
    }
  }, [preOrders]);

  return (
    <Spin spinning={loading}>
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
            <Button size="small" danger onClick={handleBatchReject} disabled={preOrders.length === 0} loading={batchSubmitting}>
              全部拒绝
            </Button>
            <Button type="primary" size="small" icon={<Zap size={12} />} onClick={handleBatchApprove} disabled={preOrders.length === 0} loading={batchSubmitting}>
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
                  <span className="signal-card__symbol">{po.name && po.name !== po.symbol ? po.name : po.symbol}</span>
                  {po.name && po.name !== po.symbol && (
                    <span className="signal-card__name">{po.symbol}</span>
                  )}
                  {riskPrecheckTag(po)}
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
                  <Button size="small" danger loading={rejectingId === po.id} onClick={() => handleReject(po.id)}>拒绝</Button>
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
          <Form.Item noStyle shouldUpdate={(prev, curr) => prev.order_type !== curr.order_type || prev.price_mode !== curr.price_mode || prev.atr_multiplier !== curr.atr_multiplier}>
            {({ getFieldValue, setFieldValue }) => {
              if (getFieldValue('order_type') !== 'limit') return null;
              const priceMode = getFieldValue('price_mode');
              const calculatedPrice = approvalTarget && priceMode === 'atr_offset'
                ? calculateAtrLimitPrice(approvalTarget, getFieldValue('atr_multiplier'))
                : null;
              if (calculatedPrice !== null && getFieldValue('limit_price') !== calculatedPrice) {
                setFieldValue('limit_price', calculatedPrice);
              }
              return (
                <>
                  <Form.Item name="price_mode" label="定价方式" rules={[{ required: true, message: '请选择定价方式' }]}>
                    <Select options={[{ value: 'manual', label: '手动输入价格' }, { value: 'atr_offset', label: '+/- ATR 调整' }]} />
                  </Form.Item>
                  {priceMode === 'atr_offset' && (
                    <Form.Item
                      name="atr_multiplier"
                      label="ATR调整倍数"
                      extra="步长 0.1 ATR；负值表示回调买入/反向偏移。"
                      rules={[{ required: true, message: '请输入ATR调整倍数' }]}
                    >
                      <InputNumber precision={1} step={0.1} style={{ width: '100%' }} placeholder="例如 -0.3 或 0.2" />
                    </Form.Item>
                  )}
                  <Form.Item name="limit_price" label={priceMode === 'atr_offset' ? '计算限价' : '限价'} rules={[{ required: true, message: '请输入限价' }]}>
                    <InputNumber min={0.0001} precision={4} style={{ width: '100%' }} placeholder="委托限价" disabled={priceMode === 'atr_offset'} />
                  </Form.Item>
                </>
              );
            }}
          </Form.Item>
          <Form.Item name="slippage_type" label="模拟成交滑点">
            <Select
              options={[
                { value: 'none', label: '不设置' },
                { value: 'percent', label: '百分比滑点' },
                { value: 'tick', label: 'Tick滑点' },
                { value: 'atr', label: 'ATR滑点' },
              ]}
            />
          </Form.Item>
          <Form.Item noStyle shouldUpdate={(prev, curr) => prev.slippage_type !== curr.slippage_type}>
            {({ getFieldValue }) => {
              const slippageType = getFieldValue('slippage_type');
              if (slippageType === 'percent') {
                return (
                  <Form.Item name="slippage_rate" label="滑点比例(%)">
                    <InputNumber min={0} precision={4} step={0.01} style={{ width: '100%' }} />
                  </Form.Item>
                );
              }
              if (slippageType === 'tick') {
                return (
                  <Form.Item name="slippage_ticks" label="滑点Tick数">
                    <InputNumber min={0} precision={0} step={1} style={{ width: '100%' }} />
                  </Form.Item>
                );
              }
              if (slippageType === 'atr') {
                return (
                  <Form.Item name="slippage_atr_multiplier" label="滑点ATR倍数">
                    <InputNumber min={0} precision={2} step={0.01} style={{ width: '100%' }} />
                  </Form.Item>
                );
              }
              return null;
            }}
          </Form.Item>
          <Form.Item name="comment" label="审批意见">
            <Input.TextArea rows={2} maxLength={256} placeholder="可填写调价或调仓原因" />
          </Form.Item>
        </Form>
      </Modal>
      </div>
    </Spin>
  );
}
