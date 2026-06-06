import { useMemo, useState } from 'react'
import { Button, Input } from 'antd'
import { LayoutGrid, List, RefreshCw, Search } from 'lucide-react'
import { useTranslation } from 'react-i18next'

import { fetchCollectTasks } from '@/api/data'
import { AsyncSection } from '@/components/common/AsyncSection'
import { TaskCard, TaskGridStats } from '@/components/data/TaskCard'
import { useRequest } from '@/hooks/useRequest'
import '@/styles/data.css'

export function DataTasksPage() {
  const { t } = useTranslation()
  const { data, loading, error, reload } = useRequest(fetchCollectTasks)
  const [keyword, setKeyword] = useState('')
  const [viewMode, setViewMode] = useState<'grid' | 'list'>('grid')

  const tasks = useMemo(() => {
    const items = data ?? []
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
  }, [data, keyword])

  const workerAvailable = data?.some((item) => item.worker_available) ?? false

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
          <TaskGridStats count={tasks.length} workerAvailable={workerAvailable} />
          <Button icon={<RefreshCw size={14} />} onClick={() => void reload()}>
            {t('data.tasks.refresh')}
          </Button>
        </div>
      </div>

      <AsyncSection loading={loading && !data} error={error} onRetry={() => void reload()}>
        <div className={viewMode === 'grid' ? 'task-grid' : 'task-list'}>
          {tasks.map((task) => (
            <TaskCard key={task.task_id} task={task} onRefresh={() => void reload()} />
          ))}
        </div>
      </AsyncSection>
    </div>
  )
}
