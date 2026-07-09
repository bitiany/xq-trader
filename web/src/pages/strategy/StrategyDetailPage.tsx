import { useCallback, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import {
  App,
  Button,
  Input,
  Modal,
  Popconfirm,
  Space,
  Table,
  Tabs,
  Tag,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { ArrowLeft, Pencil, Trash2 } from 'lucide-react'

import {
  deleteStrategy,
  fetchStrategyDetail,
  updateStrategy,
  type RuleRegistryItem,
  type StrategyType,
} from '@/api'
import { isApiError } from '@/api/types'
import { AsyncSection } from '@/components/common/AsyncSection'
import { useRequest } from '@/hooks/useRequest'

interface ReferencedRuleRow extends RuleRegistryItem {
  key: string
}

export function StrategyDetailPage() {
  const { strategyId = '' } = useParams()
  const decodedId = decodeURIComponent(strategyId)
  const navigate = useNavigate()
  const { t } = useTranslation()
  const { message } = App.useApp()

  const { data: detail, loading, error, reload } = useRequest(
    () => fetchStrategyDetail(decodedId),
    { deps: [decodedId] },
  )

  const [configModalOpen, setConfigModalOpen] = useState(false)
  const [configText, setConfigText] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const handleDeleteStrategy = useCallback(async () => {
    try {
      await deleteStrategy(decodedId)
      message.success(t('strategy.deleteSuccess'))
      navigate('/strategy/list')
    } catch (err) {
      const msg = isApiError(err) ? err.message : err instanceof Error ? err.message : t('common.loadFailed')
      message.error(msg)
    }
  }, [decodedId, navigate, t])

  const openConfigEditor = useCallback(() => {
    if (!detail) return
    setConfigText(JSON.stringify(detail.config ?? {}, null, 2))
    setConfigModalOpen(true)
  }, [detail])

  const handleSaveConfig = useCallback(async () => {
    if (!detail) return
    let parsed: Record<string, unknown>
    try {
      const value = JSON.parse(configText) as unknown
      if (!value || typeof value !== 'object' || Array.isArray(value)) {
        message.error(t('strategy.configMustBeObject'))
        return
      }
      parsed = value as Record<string, unknown>
    } catch {
      message.error(t('strategy.invalidJsonConfig'))
      return
    }

    setSubmitting(true)
    try {
      await updateStrategy(detail.strategy_id, { config: parsed })
      message.success(t('common.saveSuccess'))
      setConfigModalOpen(false)
      await reload()
    } catch (err) {
      const msg = isApiError(err) ? err.message : err instanceof Error ? err.message : t('common.loadFailed')
      message.error(msg)
    } finally {
      setSubmitting(false)
    }
  }, [configText, detail, reload, t])

  const typeColor = (type: StrategyType): string => (type === 'selection' ? 'purple' : 'blue')

  const ruleRows: ReferencedRuleRow[] = Object.entries(detail?.rule_registry ?? {}).map(([ruleId, rule]) => ({
    ...rule,
    key: ruleId,
    rule_id: rule.rule_id || ruleId,
  }))

  const ruleColumns: ColumnsType<ReferencedRuleRow> = [
    {
      title: t('strategy.selectRule'),
      dataIndex: 'rule_id',
      width: 220,
      render: (val: string, record) => (
        <Space direction="vertical" size={0}>
          <span style={{ fontFamily: 'var(--font-mono)' }}>{val}</span>
          {record.name && <span style={{ color: 'var(--text-muted)', fontSize: 11 }}>{record.name}</span>}
        </Space>
      ),
    },
    {
      title: t('strategy.ruleType'),
      dataIndex: 'rule_type',
      width: 100,
      render: (val?: string) => <Tag>{val ?? '—'}</Tag>,
    },
    {
      title: t('strategy.groupType'),
      dataIndex: 'category',
      width: 120,
      render: (val?: string) => val ?? '—',
    },
    {
      title: t('strategy.ruleDefinition'),
      dataIndex: 'definition',
      render: (val?: Record<string, unknown>) => (
        <pre className="strategy-code-block" style={{ margin: 0 }}>
          {JSON.stringify(val ?? {}, null, 2)}
        </pre>
      ),
    },
  ]

  return (
    <div className="strategy-page">
      <AsyncSection loading={loading} error={error} onRetry={() => void reload()}>
        {detail && (
          <>
            <div className="card">
              <div className="strategy-detail__header">
                <Space>
                  <Button
                    type="text"
                    icon={<ArrowLeft size={16} />}
                    onClick={() => navigate('/strategy/list')}
                  />
                  <h2 style={{ margin: 0, fontSize: 18, color: 'var(--text-primary)' }}>
                    {detail.name}
                  </h2>
                  <span style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
                    {detail.strategy_id}
                  </span>
                  <Tag color={typeColor(detail.strategy_type)}>{t(`strategy.strategyType_${detail.strategy_type}`)}</Tag>
                  <Tag color={detail.status === 'active' ? 'green' : detail.status === 'draft' ? 'gold' : 'default'}>
                    {t(`strategy.status${detail.status.charAt(0).toUpperCase() + detail.status.slice(1)}`)}
                  </Tag>
                </Space>
                <Space>
                  <Button icon={<Pencil size={14} />} onClick={openConfigEditor}>
                    {t('strategy.editConfig')}
                  </Button>
                  <Popconfirm
                    title={t('strategy.confirmDelete', { name: detail.name })}
                    onConfirm={() => void handleDeleteStrategy()}
                    okText={t('common.yes')}
                    cancelText={t('common.no')}
                  >
                    <Button danger icon={<Trash2 size={14} />}>{t('common.delete')}</Button>
                  </Popconfirm>
                </Space>
              </div>
              <div className="strategy-detail__meta">
                <div className="strategy-detail__meta-item">
                  <span className="strategy-detail__meta-label">{t('strategy.strategyType')}</span>
                  <span className="strategy-detail__meta-value">{t(`strategy.strategyType_${detail.strategy_type}`)}</span>
                </div>
                <div className="strategy-detail__meta-item">
                  <span className="strategy-detail__meta-label">{t('strategy.updatedAt')}</span>
                  <span className="strategy-detail__meta-value">
                    {detail.updated_at ? detail.updated_at.replace('T', ' ').slice(0, 19) : '—'}
                  </span>
                </div>
                <div className="strategy-detail__meta-item">
                  <span className="strategy-detail__meta-label">{t('strategy.description')}</span>
                  <span className="strategy-detail__meta-value">{detail.description ?? '—'}</span>
                </div>
              </div>
            </div>

            <Tabs
              items={[
                {
                  key: 'config',
                  label: t('strategy.jsonConfig'),
                  children: (
                    <div className="card">
                      <pre className="strategy-code-block">
                        {JSON.stringify(detail.config ?? {}, null, 2)}
                      </pre>
                    </div>
                  ),
                },
                {
                  key: 'rules',
                  label: t('strategy.referencedRules'),
                  children: (
                    <div className="card">
                      <Table<ReferencedRuleRow>
                        size="small"
                        dataSource={ruleRows}
                        columns={ruleColumns}
                        rowKey="key"
                        pagination={false}
                        locale={{ emptyText: '—' }}
                      />
                    </div>
                  ),
                },
              ]}
            />
          </>
        )}
      </AsyncSection>

      <Modal
        open={configModalOpen}
        title={t('strategy.editConfig')}
        onCancel={() => setConfigModalOpen(false)}
        onOk={() => void handleSaveConfig()}
        confirmLoading={submitting}
        destroyOnClose
        width={760}
      >
        <Input.TextArea
          rows={18}
          value={configText}
          onChange={(event) => setConfigText(event.target.value)}
          style={{ fontFamily: 'var(--font-mono)' }}
        />
      </Modal>
    </div>
  )
}
