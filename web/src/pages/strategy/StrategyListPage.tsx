import { useCallback, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import {
  App,
  Button,
  Form,
  Input,
  Modal,
  Popconfirm,
  Select,
  Space,
  Table,
  Tag,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { Edit, Plus, Trash2 } from 'lucide-react'

import {
  createStrategy,
  deleteStrategy,
  fetchStrategies,
  updateStrategy,
  type Strategy,
  type StrategyCreatePayload,
  type StrategyStatus,
  type StrategyType,
} from '@/api'
import { extractPageItems, isApiError } from '@/api/types'
import { useRequest } from '@/hooks/useRequest'

const STATUS_OPTIONS: { label: string; value: StrategyStatus | 'all' }[] = [
  { label: 'all', value: 'all' },
  { label: 'statusActive', value: 'active' },
  { label: 'statusDraft', value: 'draft' },
  { label: 'statusDeprecated', value: 'deprecated' },
]

interface StrategyFormValues {
  strategy_id: string
  name: string
  description?: string
  strategy_type: StrategyType
  status: StrategyStatus
}

export function StrategyListPage() {
  const { t } = useTranslation()
  const { message } = App.useApp()
  const navigate = useNavigate()
  const [keyword, setKeyword] = useState('')
  const [statusFilter, setStatusFilter] = useState<StrategyStatus | 'all'>('all')
  const [modalOpen, setModalOpen] = useState(false)
  const [editTarget, setEditTarget] = useState<Strategy | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [form] = Form.useForm<StrategyFormValues>()

  const params = useMemo(
    () => ({
      keyword: keyword || undefined,
      status: statusFilter === 'all' ? undefined : statusFilter,
      page: 1,
      page_size: 200,
    }),
    [keyword, statusFilter],
  )

  const { data: page, loading, error, reload } = useRequest(
    () => fetchStrategies(params),
    { deps: [params] },
  )

  const strategies = useMemo(() => extractPageItems<Strategy>(page), [page])

  const openCreate = useCallback(() => {
    setEditTarget(null)
    form.resetFields()
    form.setFieldsValue({ status: 'draft', strategy_type: 'selection' })
    setModalOpen(true)
  }, [form])

  const openEdit = useCallback(
    (record: Strategy) => {
      setEditTarget(record)
      form.setFieldsValue({
        strategy_id: record.strategy_id,
        name: record.name,
        description: record.description ?? '',
        strategy_type: record.strategy_type,
        status: record.status,
      })
      setModalOpen(true)
    },
    [form],
  )

  const handleSubmit = useCallback(async () => {
    const values = await form.validateFields()
    setSubmitting(true)
    try {
      if (editTarget) {
        await updateStrategy(editTarget.strategy_id, {
          name: values.name,
          description: values.description ?? null,
          strategy_type: values.strategy_type,
          status: values.status,
        })
        message.success(t('strategy.updateSuccess'))
      } else {
        const payload: StrategyCreatePayload = {
          strategy_id: values.strategy_id,
          name: values.name,
          description: values.description ?? null,
          strategy_type: values.strategy_type,
          config: { groups: [] },
          status: values.status,
        }
        await createStrategy(payload)
        message.success(t('strategy.createSuccess'))
      }
      setModalOpen(false)
      await reload()
    } catch (err) {
      if (err && typeof err === 'object' && 'errorFields' in err) {
        return
      }
      const msg = isApiError(err) ? err.message : err instanceof Error ? err.message : t('common.loadFailed')
      message.error(msg)
    } finally {
      setSubmitting(false)
    }
  }, [editTarget, form, reload, t])

  const handleDelete = useCallback(
    async (record: Strategy) => {
      try {
        await deleteStrategy(record.strategy_id)
        message.success(t('strategy.deleteSuccess'))
        await reload()
      } catch (err) {
        const msg = isApiError(err) ? err.message : err instanceof Error ? err.message : t('common.loadFailed')
        message.error(msg)
      }
    },
    [reload, t],
  )

  const statusColor = (status: StrategyStatus): string => {
    if (status === 'active') return 'green'
    if (status === 'draft') return 'gold'
    return 'default'
  }

  const typeColor = (type: StrategyType): string => (type === 'selection' ? 'purple' : 'blue')

  const columns: ColumnsType<Strategy> = useMemo(
    () => [
      {
        title: t('strategy.strategyId'),
        dataIndex: 'strategy_id',
        width: 200,
        render: (val: string) => (
          <a onClick={() => navigate(`/strategy/list/${encodeURIComponent(val)}`)} style={{ fontFamily: 'var(--font-mono)' }}>
            {val}
          </a>
        ),
      },
      { title: t('strategy.strategyName'), dataIndex: 'name', width: 220 },
      {
        title: t('strategy.strategyType'),
        dataIndex: 'strategy_type',
        width: 120,
        render: (type: StrategyType) => <Tag color={typeColor(type)}>{t(`strategy.strategyType_${type}`)}</Tag>,
      },
      {
        title: t('strategy.status'),
        dataIndex: 'status',
        width: 110,
        render: (status: StrategyStatus) => (
          <Tag color={statusColor(status)}>{t(`strategy.status${status.charAt(0).toUpperCase() + status.slice(1)}`)}</Tag>
        ),
      },
      {
        title: t('strategy.updatedAt'),
        dataIndex: 'updated_at',
        width: 180,
        render: (val?: string) => (val ? val.replace('T', ' ').slice(0, 19) : '—'),
      },
      {
        title: t('common.action'),
        key: 'actions',
        width: 160,
        fixed: 'right',
        render: (_, record) => (
          <Space size={4}>
            <Button
              type="text"
              size="small"
              icon={<Edit size={14} />}
              onClick={() => openEdit(record)}
            />
            <Popconfirm
              title={t('strategy.confirmDelete', { name: record.name })}
              onConfirm={() => handleDelete(record)}
              okText={t('common.yes')}
              cancelText={t('common.no')}
            >
              <Button type="text" size="small" danger icon={<Trash2 size={14} />} />
            </Popconfirm>
          </Space>
        ),
      },
    ],
    [handleDelete, navigate, openEdit, t],
  )

  return (
    <div className="strategy-page">
      <div className="card">
        <div className="strategy-toolbar">
          <div className="strategy-toolbar__field" style={{ minWidth: 260 }}>
            <label>{t('strategy.searchPlaceholder')}</label>
            <Input.Search
              allowClear
              placeholder={t('strategy.searchPlaceholder')}
              onSearch={setKeyword}
            />
          </div>
          <div className="strategy-toolbar__field" style={{ minWidth: 160 }}>
            <label>{t('strategy.filterStatus')}</label>
            <Select
              value={statusFilter}
              onChange={(v) => setStatusFilter(v)}
              options={STATUS_OPTIONS.map((opt) => ({
                label: opt.value === 'all' ? t('strategy.all') : t(`strategy.${opt.label}`),
                value: opt.value,
              }))}
            />
          </div>
          <div className="strategy-toolbar__actions">
            <Button type="primary" icon={<Plus size={14} />} onClick={openCreate}>
              {t('strategy.createStrategy')}
            </Button>
          </div>
        </div>
      </div>

      <div className="card">
        <Table<Strategy>
          dataSource={strategies}
          columns={columns}
          rowKey="strategy_id"
          loading={loading}
          pagination={{ pageSize: 20, showTotal: (total) => `Total ${total}` }}
          scroll={{ x: 'max-content' }}
        />
        {error && <p style={{ color: 'var(--color-fall)', marginTop: 8 }}>{error}</p>}
      </div>

      <Modal
        open={modalOpen}
        title={editTarget ? t('strategy.editStrategy') : t('strategy.createStrategy')}
        onCancel={() => setModalOpen(false)}
        onOk={() => void handleSubmit()}
        confirmLoading={submitting}
        destroyOnClose
      >
        <Form<StrategyFormValues> form={form} layout="vertical">
          <Form.Item
            label={t('strategy.strategyId')}
            name="strategy_id"
            rules={[{ required: true, message: t('strategy.strategyId') }]}
          >
            <Input disabled={!!editTarget} placeholder="my_strategy_id" />
          </Form.Item>
          <Form.Item
            label={t('strategy.strategyName')}
            name="name"
            rules={[{ required: true, message: t('strategy.strategyName') }]}
          >
            <Input />
          </Form.Item>
          <Form.Item
            label={t('strategy.strategyType')}
            name="strategy_type"
            rules={[{ required: true, message: t('strategy.strategyType') }]}
          >
            <Select
              options={[
                { label: t('strategy.strategyType_selection'), value: 'selection' },
                { label: t('strategy.strategyType_timing'), value: 'timing' },
              ]}
            />
          </Form.Item>
          <Form.Item label={t('strategy.description')} name="description">
            <Input.TextArea rows={3} />
          </Form.Item>
          <Form.Item
            label={t('strategy.status')}
            name="status"
            initialValue="draft"
            rules={[{ required: true }]}
          >
            <Select
              options={[
                { label: t('strategy.statusDraft'), value: 'draft' },
                { label: t('strategy.statusActive'), value: 'active' },
                { label: t('strategy.statusDeprecated'), value: 'deprecated' },
              ]}
            />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
