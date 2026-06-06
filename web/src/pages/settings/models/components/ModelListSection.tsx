import { Bot, MoreHorizontal, Pencil, Trash2 } from 'lucide-react'
import { Button, Dropdown, Empty, Switch, Table, Tag, type MenuProps } from 'antd'
import { useTranslation } from 'react-i18next'
import type { AiModelItem } from '@/api/ai/models'
import { AsyncSection } from '@/components/common/AsyncSection'
import './ModelListSection.css'

interface ModelListSectionProps {
  models: AiModelItem[]
  loading: boolean
  error: string | null
  onRetry: () => void
  onCreate: () => void
  onEdit: (model: AiModelItem) => void
  onDelete: (model: AiModelItem) => void
  onToggleStatus: (model: AiModelItem, enabled: boolean) => void
}

export function ModelListSection({
  models,
  loading,
  error,
  onRetry,
  onCreate,
  onEdit,
  onDelete,
  onToggleStatus,
}: ModelListSectionProps) {
  const { t } = useTranslation()

  const columns = [
    {
      title: t('settings.models.colName'),
      dataIndex: 'name',
      key: 'name',
      render: (name: string) => (
        <span className="model-list__name">
          <Bot size={14} />
          {name}
        </span>
      ),
    },
    {
      title: t('settings.models.colType'),
      dataIndex: 'type',
      key: 'type',
      render: (type: string) => <Tag>{type || 'chat'}</Tag>,
    },
    {
      title: t('settings.models.colProviders'),
      dataIndex: 'provider_count',
      key: 'provider_count',
      render: (count: number | undefined) => count ?? 0,
    },
    {
      title: t('settings.models.colStatus'),
      dataIndex: 'status',
      key: 'status',
      render: (status: boolean | undefined, record: AiModelItem) => (
        <Switch
          size="small"
          checked={status !== false}
          onChange={(checked) => onToggleStatus(record, checked)}
        />
      ),
    },
    {
      title: t('settings.models.colActions'),
      key: 'actions',
      width: 80,
      render: (_: unknown, record: AiModelItem) => {
        const items: MenuProps['items'] = [
          {
            key: 'edit',
            icon: <Pencil size={13} />,
            label: t('settings.models.editModel'),
            onClick: () => onEdit(record),
          },
          {
            key: 'delete',
            icon: <Trash2 size={13} />,
            label: t('settings.models.deleteModel'),
            danger: true,
            onClick: () => onDelete(record),
          },
        ]
        return (
          <Dropdown menu={{ items }} trigger={['click']}>
            <Button type="text" size="small" icon={<MoreHorizontal size={14} />} />
          </Dropdown>
        )
      },
    },
  ]

  return (
    <AsyncSection loading={loading && models.length === 0} error={error} onRetry={onRetry}>
      {models.length === 0 && !loading ? (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={
            <div className="model-list__empty">
              <p>{t('settings.models.emptyTitle')}</p>
              <span>{t('settings.models.emptyDesc')}</span>
            </div>
          }
        >
          <Button type="primary" onClick={onCreate}>
            {t('settings.models.createFirstModel')}
          </Button>
        </Empty>
      ) : (
        <Table<AiModelItem>
          size="small"
          rowKey={(row) => String(row.id ?? row.name)}
          columns={columns}
          dataSource={models}
          pagination={false}
          loading={loading && models.length > 0}
        />
      )}
    </AsyncSection>
  )
}
