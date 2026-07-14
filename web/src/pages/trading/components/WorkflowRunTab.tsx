import { useCallback, useEffect, useMemo, useState } from 'react';
import { App, Button, Card, Space, Spin, Steps, Table, Tag } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { GitBranch, Zap } from 'lucide-react';
import { ApiError } from '@/api/types';
import { batchSubmitPreOrders, fetchPreOrders, submitPreOrder, type PreOrder } from '@/api/trading';
import { SIGNAL_SIDE_COLOR, SIGNAL_SIDE_LABEL, DEFAULT_OPERATOR } from '../utils/trading';
import { StockSymbolCell } from './StockQuoteCell';

interface WorkflowRunTabProps {
  accountId: number | null;
  onOpenApproval?: () => void;
}

interface WorkflowRunSummary {
  runId: string;
  signalDate: string;
  executionDate: string;
  total: number;
  pending: number;
  approved: number;
  rejected: number;
}

const DECISION_STEPS = [
  { title: '加载自选标的', status: 'finish' as const },
  { title: '并行信号执行', status: 'finish' as const },
  { title: '组合融合', status: 'finish' as const },
  { title: '仓位管理', status: 'finish' as const },
  { title: '风控预检', status: 'finish' as const },
  { title: '预订单生成', status: 'finish' as const },
];

const EXECUTION_STEPS = [
  { title: '人工审批', status: 'process' as const },
  { title: '生成真实订单', status: 'wait' as const },
  { title: '交易提交', status: 'wait' as const },
  { title: '成交回报', status: 'wait' as const },
];

const PRE_ORDER_STATUS_LABEL: Record<string, string> = {
  pending_approval: '待审批',
  approved: '已批准',
  rejected: '已拒绝',
  submitted: '已下单',
  expired: '已过期',
};

function groupRuns(preOrders: PreOrder[]): WorkflowRunSummary[] {
  const groups = new Map<string, WorkflowRunSummary>();
  preOrders.forEach((order) => {
    if (!order.workflow_run_id) return;
    const summary = groups.get(order.workflow_run_id) ?? {
      runId: order.workflow_run_id,
      signalDate: order.signal_date,
      executionDate: order.execution_date,
      total: 0,
      pending: 0,
      approved: 0,
      rejected: 0,
    };
    summary.total += 1;
    if (order.approval_status === 'pending') summary.pending += 1;
    if (order.approval_status === 'approved') summary.approved += 1;
    if (order.approval_status === 'rejected') summary.rejected += 1;
    groups.set(order.workflow_run_id, summary);
  });
  return Array.from(groups.values());
}

function approvalStatus(run: WorkflowRunSummary) {
  if (run.pending > 0) return 'pending';
  if (run.rejected > 0 && run.approved === 0) return 'rejected';
  return 'approved';
}

function formatWeight(value: number | null) {
  if (value === null || value === undefined) return '—';
  return `${(Number(value) * 100).toFixed(2)}%`;
}

export function WorkflowRunTab({ accountId, onOpenApproval }: WorkflowRunTabProps) {
  const { message } = App.useApp();
  const [preOrders, setPreOrders] = useState<PreOrder[]>([]);
  const [loading, setLoading] = useState(false);
  const [submittingIds, setSubmittingIds] = useState<number[]>([]);
  const [batchSubmitting, setBatchSubmitting] = useState(false);

  const executablePreOrders = useMemo(
    () => preOrders.filter((item) => item.approval_status === 'approved' && item.status === 'approved'),
    [preOrders],
  );

  const loadPreOrders = useCallback(async () => {
    if (accountId === null) {
      setPreOrders([]);
      return;
    }
    try {
      const res = await fetchPreOrders({ account_id: accountId, page_size: 200 });
      setPreOrders(res.items);
    } catch {
      message.error('工作流运行记录加载失败');
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- message 为 antd 稳定引用
  }, [accountId]);

  useEffect(() => {
    let cancelled = false;
    Promise.resolve().then(() => {
      if (accountId === null) {
        setPreOrders([]);
        setLoading(false);
        return undefined;
      }
      setLoading(true);
      return fetchPreOrders({ account_id: accountId, page_size: 200 }).then((res) => {
        if (!cancelled) setPreOrders(res.items);
      }).catch(() => {
        if (!cancelled) message.error('工作流运行记录加载失败');
      }).finally(() => {
        if (!cancelled) setLoading(false);
      });
    });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- message 为 antd 稳定引用
  }, [accountId]);

  const handleSubmitOne = useCallback(async (preOrderId: number) => {
    setSubmittingIds((ids) => [...ids, preOrderId]);
    try {
      const operator = DEFAULT_OPERATOR;
      const result = await submitPreOrder(preOrderId, { operator });
      message.success(`已提交订单 ${result.order.id}${result.submitter === 'qmt' ? '（QMT）' : '（模拟）'}`);
      await loadPreOrders();
    } catch (error) {
      message.error(error instanceof ApiError ? error.message : error instanceof Error ? error.message : '预订单下单失败');
    } finally {
      setSubmittingIds((ids) => ids.filter((id) => id !== preOrderId));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- message 为 antd 稳定引用
  }, [loadPreOrders]);

  const handleSubmitBatch = useCallback(async () => {
    if (executablePreOrders.length === 0) return;
    setBatchSubmitting(true);
    try {
      const operator = DEFAULT_OPERATOR;
      const result = await batchSubmitPreOrders({
        pre_order_ids: executablePreOrders.map((item) => item.id),
        operator,
      });
      if (result.failed > 0) {
        message.warning(`批量下单完成：成功 ${result.submitted} 条，失败 ${result.failed} 条`);
      } else {
        message.success(`批量下单完成：成功 ${result.submitted} 条`);
      }
      await loadPreOrders();
    } catch (error) {
      message.error(error instanceof ApiError ? error.message : error instanceof Error ? error.message : '批量下单失败');
    } finally {
      setBatchSubmitting(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- message 为 antd 稳定引用
  }, [executablePreOrders, loadPreOrders]);

  const orderColumns: ColumnsType<PreOrder> = [
    {
      title: '标的',
      key: 'symbol',
      width: 130,
      render: (_: unknown, item: PreOrder) => <StockSymbolCell symbol={item.symbol} name={item.name} />,
    },
    {
      title: '方向',
      dataIndex: 'side',
      width: 76,
      render: (side: PreOrder['side']) => <Tag color={SIGNAL_SIDE_COLOR[side]}>{SIGNAL_SIDE_LABEL[side]}</Tag>,
    },
    { title: '数量', dataIndex: 'target_qty', width: 80, render: (value: number | null) => value ?? '—' },
    { title: '目标仓位', dataIndex: 'target_weight', width: 92, render: formatWeight },
    {
      title: '委托方式',
      dataIndex: 'order_type',
      width: 112,
      render: (_: PreOrder['order_type'], item) => (
        item.order_type === 'market' ? '市价' : `限价 ${item.limit_price ?? '—'}`
      ),
    },
    { title: '状态', dataIndex: 'status', width: 82, render: (status: string) => PRE_ORDER_STATUS_LABEL[status] ?? status },
    {
      title: '操作',
      key: 'action',
      width: 88,
      render: (_, item) => (
        <Button
          size="small"
          type="primary"
          loading={submittingIds.includes(item.id)}
          disabled={batchSubmitting}
          onClick={() => void handleSubmitOne(item.id)}
        >
          下单
        </Button>
      ),
    },
  ];

  const runs = useMemo(() => groupRuns(preOrders), [preOrders]);
  const latestRun = runs[0];
  const executionStep = executablePreOrders.length > 0 ? 1 : latestRun?.pending ? 0 : -1;

  return (
    <Spin spinning={loading}>
      <div className="workflow-run-tab" data-component="Workflow Run Tab">
      <Card size="small" className="workflow-run-tab__flow">
        <div className="workflow-run-tab__flow-header">
          <div>
            <span className="workflow-run-tab__flow-name">watchlist_after_close_decision</span>
            <Tag color={latestRun ? 'success' : 'default'} style={{ fontSize: 10, marginLeft: 6 }}>
              {latestRun ? 'completed' : 'no_run'}
            </Tag>
          </div>
          <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
            {latestRun ? `信号日: ${latestRun.signalDate} | 预订单: ${latestRun.total}` : '暂无决策流预订单'}
          </span>
        </div>
        <Steps size="small" current={latestRun ? DECISION_STEPS.length - 1 : -1} items={DECISION_STEPS} style={{ marginTop: 8 }} />
        <div className="workflow-run-tab__output">
          {latestRun
            ? `pending=${latestRun.pending}, approved=${latestRun.approved}, rejected=${latestRun.rejected}`
            : '等待工作流生成预订单'}
        </div>
      </Card>

      <Card size="small" className="workflow-run-tab__flow">
        <div className="workflow-run-tab__flow-header">
          <div>
            <span className="workflow-run-tab__flow-name">pre_order_execution_flow</span>
            <Tag color={executablePreOrders.length > 0 ? 'processing' : 'default'} style={{ fontSize: 10, marginLeft: 6 }}>
              {executablePreOrders.length > 0 ? 'ready_to_submit' : 'waiting'}
            </Tag>
          </div>
          <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
            {latestRun ? `执行日: ${latestRun.executionDate}` : '等待审批信号'}
          </span>
        </div>
        <Steps size="small" current={executionStep} items={EXECUTION_STEPS} style={{ marginTop: 8 }} />
        <Space style={{ marginTop: 10 }}>
          <Button type="primary" size="small" icon={<Zap size={12} />} onClick={onOpenApproval}>
            打开审批列表
          </Button>
          <Button
            size="small"
            disabled={executablePreOrders.length === 0}
            loading={batchSubmitting}
            onClick={() => void handleSubmitBatch()}
          >
            批量下单 {executablePreOrders.length > 0 ? `(${executablePreOrders.length})` : ''}
          </Button>
        </Space>
        <Table
          size="small"
          rowKey="id"
          columns={orderColumns}
          dataSource={executablePreOrders}
          pagination={false}
          style={{ marginTop: 10 }}
          locale={{ emptyText: '暂无已批准且待下单预订单' }}
        />
      </Card>

      <Card size="small" className="workflow-run-tab__history">
        <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 8 }}>
          <GitBranch size={13} style={{ verticalAlign: 'middle', marginRight: 4 }} />
          Run 历史
        </div>
        <div className="workflow-run-tab__history-list">
          {runs.map((run) => {
            const status = approvalStatus(run);
            return (
              <div key={run.runId} className="workflow-run-tab__history-row">
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-secondary)', width: 150 }}>{run.runId}</span>
                <span style={{ fontSize: 11, color: 'var(--text-muted)', width: 80 }}>{run.signalDate}</span>
                <Tag color={status === 'approved' ? 'success' : status === 'rejected' ? 'error' : 'default'} style={{ fontSize: 10 }}>{status}</Tag>
                <span style={{ fontSize: 11, color: 'var(--text-muted)', marginLeft: 'auto' }}>{run.total} 条</span>
              </div>
            );
          })}
          {runs.length === 0 && (
            <div style={{ color: 'var(--text-muted)', fontSize: 12 }}>暂无工作流预订单记录</div>
          )}
        </div>
      </Card>
      </div>
    </Spin>
  );
}
