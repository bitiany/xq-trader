import { useState } from 'react'
import { Button, message, Tag } from 'antd'
import { GitBranch, Play } from 'lucide-react'
import { useTranslation } from 'react-i18next'

import type { PipelineItem } from '@/api/data'
import { triggerPipeline } from '@/api/data'

interface PipelineCardProps {
  pipeline: PipelineItem
  onRefresh: () => void
}

function pipelineStatusClass(status: string): string {
  switch (status) {
    case 'running':
      return 'task-card__status--running'
    case 'success':
      return 'task-card__status--success'
    case 'failed':
      return 'task-card__status--failed'
    default:
      return 'task-card__status--idle'
  }
}

const STEP_NAME_MAP: Record<string, string> = {
  daily_incremental_collect: '日行情增量采集',
  daily_factor_compute: '日频因子计算',
  financial_indicator_collect: '财务指标采集',
  income_statement_collect: '利润表采集',
  balance_sheet_collect: '资产负债表采集',
  cash_flow_collect: '现金流量表采集',
  quarterly_factor_compute: '季度因子计算',
}

export function PipelineCard({ pipeline, onRefresh }: PipelineCardProps) {
  const { t } = useTranslation()
  const [triggering, setTriggering] = useState(false)

  const handleTrigger = async () => {
    try {
      setTriggering(true)
      const result = await triggerPipeline(pipeline.pipeline_name)
      if (result.queued) {
        message.success(result.message)
      } else {
        message.warning(result.message)
      }
      onRefresh()
    } catch (err) {
      message.error(err instanceof Error ? err.message : t('data.tasks.triggerFailed'))
    } finally {
      setTriggering(false)
    }
  }

  const pipelineDisplayName = t(`data.pipeline.name.${pipeline.pipeline_name}`, {
    defaultValue: pipeline.pipeline_name,
  })

  return (
    <article className="task-card card">
      <div className="task-card__header">
        <div className="task-card__title-wrap">
          <span className="task-card__icon">
            <GitBranch size={16} />
          </span>
          <div>
            <h3 className="task-card__title">{pipelineDisplayName}</h3>
            <span className={`task-card__status ${pipelineStatusClass(pipeline.status)}`}>
              {t(`data.tasks.status.${pipeline.status}`, { defaultValue: pipeline.status })}
            </span>
          </div>
        </div>
        <Tag color={pipeline.mode === 'canvas' ? 'blue' : 'orange'}>{pipeline.mode}</Tag>
      </div>

      <p className="task-card__desc">{t(`data.pipeline.desc.${pipeline.pipeline_name}`, { defaultValue: pipeline.description })}</p>

      <div className="task-card__meta">
        {pipeline.cron && <span>{pipeline.cron}</span>}
        {pipeline.last_run_at ? <span>{pipeline.last_run_at}</span> : null}
        <span className="task-card__pipeline">
          {t('data.pipeline.stepCount', { count: pipeline.step_count })}
        </span>
      </div>

      <div className="pipeline-card__steps">
        {pipeline.steps.map((step, idx) => {
          const stepLabel = STEP_NAME_MAP[step.name] || step.name
          return (
            <div key={step.name} className="pipeline-card__step">
              <span className="pipeline-card__step-index">{idx + 1}</span>
              <span className="pipeline-card__step-name">{stepLabel}</span>
              {step.depends_on && step.depends_on.length > 0 && (
                <span className="pipeline-card__step-dep">
                  ← {step.depends_on.map(d => STEP_NAME_MAP[d] || d).join(', ')}
                </span>
              )}
            </div>
          )
        })}
      </div>

      <div className="task-card__footer">
        <Button
          type="primary"
          size="small"
          icon={<Play size={14} />}
          loading={triggering}
          onClick={handleTrigger}
          disabled={!pipeline.enabled}
        >
          {t('data.tasks.trigger')}
        </Button>
      </div>
    </article>
  )
}
