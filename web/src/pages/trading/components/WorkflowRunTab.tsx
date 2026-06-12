import { Card, Steps, Tag, Button } from 'antd';
import { GitBranch, Zap } from 'lucide-react';
import { DECISION_STEPS, EXECUTION_STEPS } from '../data/mock-trading';

interface WorkflowRunTabProps {
  onOpenApproval?: () => void;
}

export function WorkflowRunTab({ onOpenApproval }: WorkflowRunTabProps) {
  return (
    <div className="workflow-run-tab" data-component="Workflow Run Tab">
      <Card size="small" className="workflow-run-tab__flow">
        <div className="workflow-run-tab__flow-header">
          <div>
            <span className="workflow-run-tab__flow-name">trading_decision</span>
            <Tag color="success" style={{ fontSize: 10, marginLeft: 6 }}>succeeded</Tag>
          </div>
          <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
            信号日: 2026-06-09 | 启动: 18:00 | 耗时: 3m20s
          </span>
        </div>
        <Steps size="small" current={DECISION_STEPS.length - 1} items={DECISION_STEPS} style={{ marginTop: 8 }} />
        <div className="workflow-run-tab__output">
          position_sizing: &#123; 600519: 12%, 000858: 5%, 601318: 0% &#125;
        </div>
      </Card>

      <Card size="small" className="workflow-run-tab__flow">
        <div className="workflow-run-tab__flow-header">
          <div>
            <span className="workflow-run-tab__flow-name">trading_execution</span>
            <Tag color="default" style={{ fontSize: 10, marginLeft: 6 }}>pending</Tag>
          </div>
          <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
            执行日: 2026-06-10 | 预计启动: 09:25
          </span>
        </div>
        <Steps size="small" current={-1} items={EXECUTION_STEPS} style={{ marginTop: 8 }} />
        <div style={{ marginTop: 10 }}>
          <Button type="primary" size="small" icon={<Zap size={12} />} onClick={onOpenApproval}>
            打开审批抽屉
          </Button>
        </div>
      </Card>

      <Card size="small" className="workflow-run-tab__history">
        <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 8 }}>
          <GitBranch size={13} style={{ verticalAlign: 'middle', marginRight: 4 }} />
          Run 历史
        </div>
        <div className="workflow-run-tab__history-list">
          {[
            { flow: 'trading_decision', signalDate: '06-09', status: 'succeeded', duration: '3m20s' },
            { flow: 'trading_execution', signalDate: '06-10', status: 'pending', duration: '—' },
            { flow: 'trading_decision', signalDate: '06-08', status: 'succeeded', duration: '2m45s' },
            { flow: 'trading_execution', signalDate: '06-09', status: 'succeeded', duration: '1m10s' },
          ].map((run, idx) => (
            <div key={idx} className="workflow-run-tab__history-row">
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-secondary)', width: 120 }}>{run.flow}</span>
              <span style={{ fontSize: 11, color: 'var(--text-muted)', width: 60 }}>{run.signalDate}</span>
              <Tag color={run.status === 'succeeded' ? 'success' : 'default'} style={{ fontSize: 10 }}>{run.status}</Tag>
              <span style={{ fontSize: 11, color: 'var(--text-muted)', marginLeft: 'auto' }}>{run.duration}</span>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}
