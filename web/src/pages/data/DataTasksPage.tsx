import { useMemo, useState } from 'react'
import { Button, Input, Segmented } from 'antd'
import { LayoutGrid, List, RefreshCw, Search } from 'lucide-react'
import { useTranslation } from 'react-i18next'

import { fetchCollectTasks, fetchPipelines } from '@/api/data'
import { AsyncSection } from '@/components/common/AsyncSection'
import { PipelineCard } from '@/components/data/PipelineCard'
import { TaskCard, TaskGridStats } from '@/components/data/TaskCard'
import { useRequest } from '@/hooks/useRequest'
import '@/styles/data.css'

type TabKey = 'tasks' | 'pipelines'

export function DataTasksPage() {
  const { t } = useTranslation()
  const tasksReq = useRequest(fetchCollectTasks)
  const pipelinesReq = useRequest(fetchPipelines)
  const [keyword, setKeyword] = useState('')
  const [viewMode, setViewMode] = useState<'grid' | 'list'>('grid')
  const [activeTab, setActiveTab] = useState<TabKey>('tasks')

  const tasks = useMemo(() => {
    const items = tasksReq.data ?? []
    const query = keyword.trim().toLowerCase()
    if (!query) {
      return items
    }
    return items.filter(
      (item) =>
        item.task_name.toLowerCase().includes(query) ||
        item.task_name_en.toLowerCase().includes(query) ||
        item.task_id.toLowerCase().includes(query),
    )
  }, [tasksReq.data, keyword])

  const pipelines = useMemo(() => {
    const items = pipelinesReq.data ?? []
    const query = keyword.trim().toLowerCase()
    if (!query) {
      return items
    }
    return items.filter(
      (item) =>
        item.pipeline_name.toLowerCase().includes(query) ||
        item.description.toLowerCase().includes(query),
    )
  }, [pipelinesReq.data, keyword])

  const workerAvailable = tasksReq.data?.some((item) => item.worker_available) ?? false
  const loading = activeTab === 'tasks' ? tasksReq.loading : pipelinesReq.loading
  const error = activeTab === 'tasks' ? tasksReq.error : pipelinesReq.error
  const reload = activeTab === 'tasks' ? tasksReq.reload : pipelinesReq.reload
  const itemCount = activeTab === 'tasks' ? tasks.length : pipelines.length

  return (
    <div className="page">
      <div className="data-toolbar card">
        <div className="data-toolbar__left">
          <Input
            allowClear
            prefix={<Search size={14} />}
            placeholder={t('data.tasks.searchPlaceholder')}
            value={keyword}
            onChange={(event) => setKeyword(event.target.value)}
            className="data-toolbar__search"
          />
          <div className="data-toolbar__view-toggle">
            <Button
              type={viewMode === 'grid' ? 'primary' : 'text'}
              size="small"
              icon={<LayoutGrid size={14} />}
              onClick={() => setViewMode('grid')}
            />
            <Button
              type={viewMode === 'list' ? 'primary' : 'text'}
              size="small"
              icon={<List size={14} />}
              onClick={() => setViewMode('list')}
            />
          </div>
        </div>
        <div className="data-toolbar__right">
          <Segmented
            value={activeTab}
            onChange={(val) => setActiveTab(val as TabKey)}
            options={[
              { label: t('data.tasks.tabTasks'), value: 'tasks' },
              { label: t('data.tasks.tabPipelines'), value: 'pipelines' },
            ]}
          />
          <TaskGridStats count={itemCount} workerAvailable={workerAvailable} />
          <Button icon={<RefreshCw size={14} />} onClick={() => void reload()}>
            {t('data.tasks.refresh')}
          </Button>
        </div>
      </div>

      <AsyncSection loading={loading && !tasksReq.data} error={error} onRetry={() => void reload()}>
        <div className={viewMode === 'grid' ? 'task-grid' : 'task-list'}>
          {activeTab === 'tasks' &&
            tasks.map((task) => (
              <TaskCard key={task.task_id} task={task} onRefresh={() => void reload()} />
            ))}
          {activeTab === 'pipelines' &&
            pipelines.map((pipeline) => (
              <PipelineCard key={pipeline.pipeline_name} pipeline={pipeline} onRefresh={() => void reload()} />
            ))}
        </div>
      </AsyncSection>
    </div>
  )
}
