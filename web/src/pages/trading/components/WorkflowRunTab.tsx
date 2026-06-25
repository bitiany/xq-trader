import { useEffect, useMemo, useState } from 'react';
import { Card, Steps, Tag, Button, message } from 'antd';
import { GitBranch, Zap } from 'lucide-react';
import { fetchPreOrders, type PreOrder } from '@/api/trading';

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

export function WorkflowRunTab({ accountId, onOpenApproval }: WorkflowRunTabProps) {
  const [preOrders, setPreOrders] = useState<PreOrder[]>([]);

  useEffect(() => {
    let cancelled = false;
    Promise.resolve().then(() => {
      if (accountId === null) {
        setPreOrders([]);
        return undefined;
      }
      return fetchPreOrders({ account_id: accountId, page_size: 200 }).then((res) => {
        if (!cancelled) setPreOrders(res.items);
      }).catch(() => {
        if (!cancelled) message.error('工作流运行记录加载失败');
      });
    });
    return () => { cancelled = true; };
  }, [accountId]);

  const runs = useMemo(() => groupRuns(preOrders), [preOrders]);
  const latestRun = runs[0];

  return (
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
            <span className="workflow-run-tab__flow-name">trading_execution</span>
            <Tag color={latestRun?.pending ? 'processing' : 'default'} style={{ fontSize: 10, marginLeft: 6 }}>
              {latestRun?.pending ? 'pending_approval' : 'waiting'}
            </Tag>
          </div>
          <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
            {latestRun ? `执行日: ${latestRun.executionDate}` : '等待审批信号'}
          </span>
        </div>
        <Steps size="small" current={latestRun?.pending ? 0 : -1} items={EXECUTION_STEPS} style={{ marginTop: 8 }} />
        <div style={{ marginTop: 10 }}>
          <Button type="primary" size="small" icon={<Zap size={12} />} onClick={onOpenApproval}>
            打开审批列表
          </Button>
        </div>
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
  );
}
