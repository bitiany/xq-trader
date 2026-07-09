import { useState } from 'react'
import { App, Button, DatePicker, Form, Modal, Switch } from 'antd'
import dayjs from 'dayjs'
import {
  BarChart3,
  CalendarDays,
  Cpu,
  Database,
  LineChart,
  Play,
  Settings2,
  Sparkles,
  TrendingUp,
} from 'lucide-react'
import { useTranslation } from 'react-i18next'

import type { CollectTaskItem } from '@/api/data'
import { triggerCollectTask } from '@/api/data'

const CATEGORY_ICONS = {
  macro: CalendarDays,
  reference: Database,
  market: LineChart,
  fundamental: BarChart3,
  compute: Cpu,
  ml: Cpu,
} as const

interface TaskCardProps {
  task: CollectTaskItem
  onRefresh: () => void
}

function statusClass(status: string): string {
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

interface TriggerParamsFormValues {
  start_date: dayjs.Dayjs | null
  force_refresh: boolean
}

export function TaskCard({ task, onRefresh }: TaskCardProps) {
  const { t, i18n } = useTranslation()
  const { message } = App.useApp()
  const isZh = i18n.language.startsWith('zh')
  const Icon = CATEGORY_ICONS[task.category as keyof typeof CATEGORY_ICONS] ?? Sparkles

  const [settingsVisible, setSettingsVisible] = useState(false)
  const [triggering, setTriggering] = useState(false)
  const [form] = Form.useForm<TriggerParamsFormValues>()

  const handleDirectTrigger = async () => {
    try {
      setTriggering(true)
      const result = await triggerCollectTask(task.task_id)
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

  const handleSettings = () => {
    form.resetFields()
    setSettingsVisible(true)
  }

  const handleConfirmParams = async () => {
    try {
      const values = await form.validateFields()
      setTriggering(true)
      const params: Record<string, unknown> = {}
      if (values.start_date) {
        params.start_date = values.start_date.format('YYYY-MM-DD')
      }
      if (values.force_refresh) {
        params.force_refresh = true
      }
      const result = await triggerCollectTask(task.task_id, params)
      if (result.queued) {
        message.success(result.message)
      } else {
        message.warning(result.message)
      }
      setSettingsVisible(false)
      onRefresh()
    } catch (err) {
      if (err instanceof Error) {
        message.error(err.message)
      }
    } finally {
      setTriggering(false)
    }
  }

  const displayName = isZh ? task.task_name : task.task_name_en || task.task_name
  const displayDesc = isZh ? task.description : task.description_en || task.description
  const displaySchedule = isZh ? task.schedule_display : task.schedule_display_en || task.schedule_display

  return (
    <article className="task-card card">
      <div className="task-card__header">
        <div className="task-card__title-wrap">
          <span className="task-card__icon">
            <Icon size={16} />
          </span>
          <div>
            <h3 className="task-card__title">{displayName}</h3>
            <span className={`task-card__status ${statusClass(task.status)}`}>
              {t(`data.tasks.status.${task.status}`, { defaultValue: task.status })}
            </span>
          </div>
        </div>
        <Switch checked={task.enabled} disabled size="small" />
      </div>

      <p className="task-card__desc">{displayDesc}</p>

      <div className="task-card__meta">
        <span>{displaySchedule || t('data.tasks.status.idle')}</span>
        {task.last_run_at ? <span>{task.last_run_at}</span> : null}
        <span className="task-card__pipeline">{t(`data.tasks.taskType.${task.task_type}`, { defaultValue: task.task_type })}</span>
      </div>

      <div className="task-card__footer">
        <Button type="text" size="small" icon={<Settings2 size={14} />} onClick={handleSettings} />
        <Button
          type="primary"
          size="small"
          icon={<Play size={14} />}
          loading={triggering}
          onClick={handleDirectTrigger}
        >
          {t('data.tasks.trigger')}
        </Button>
      </div>

      <Modal
        title={t('data.tasks.taskSettings')}
        open={settingsVisible}
        onCancel={() => setSettingsVisible(false)}
        footer={[
          <Button key="cancel" onClick={() => setSettingsVisible(false)}>
            {t('common.cancel')}
          </Button>,
          <Button key="confirm" type="primary" loading={triggering} onClick={() => void handleConfirmParams()}>
            {t('data.tasks.confirmTrigger')}
          </Button>,
        ]}
        destroyOnClose
      >
        <Form form={form} layout="vertical" initialValues={{ force_refresh: false }}>
          <Form.Item name="start_date" label={t('data.tasks.startDate')}>
            <DatePicker style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="force_refresh" label={t('data.tasks.forceRefresh')} valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>
    </article>
  )
}

export function TaskGridStats({ count, workerAvailable }: { count: number; workerAvailable: boolean }) {
  const { t } = useTranslation()

  return (
    <div className="data-toolbar__stats">
      <span>
        <TrendingUp size={14} />
        {t('data.tasks.total', { count })}
      </span>
      <span className={workerAvailable ? 'text-profit' : 'text-loss'}>
        {workerAvailable ? t('data.tasks.workerOnline') : t('data.tasks.workerOffline')}
      </span>
    </div>
  )
}
