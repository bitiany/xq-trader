import { useCallback, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import {
  Button,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Select,
  Space,
  Table,
  Tabs,
  Tag,
  message,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { ArrowLeft, Pencil, Plus, Trash2 } from 'lucide-react'

import {
  createRule,
  createRuleBinding,
  createRuleGroup,
  deleteRuleBinding,
  deleteRuleGroup,
  deleteStrategy,
  fetchFactors,
  fetchStrategyDetail,
  updateRule,
  updateRuleBinding,
  updateRuleGroup,
  type CombinationMethod,
  type Factor,
  type RuleBinding,
  type RuleGroup,
  type RuleGroupType,
} from '@/api'
import { extractPageItems, isApiError } from '@/api/types'
import { AsyncSection } from '@/components/common/AsyncSection'
import { useRequest } from '@/hooks/useRequest'

const COMBINATION_OPTIONS: CombinationMethod[] = [
  'and',
  'or',
  'weighted_score',
  'weighted_vote',
  'ic_weighted',
]

const GROUP_TYPE_OPTIONS: RuleGroupType[] = ['cross_section', 'time_series']

function canEditRuleDefinition(binding: RuleBinding | null): boolean {
  return binding?.rule?.type === 'expression' && binding.rule.is_builtin === false
}

interface BindingFormValues {
  rule_name: string
  factor_id: string
  operator: '>' | '>=' | '<' | '<=' | '==' | '!='
  threshold: number
  expression?: string
  weight: number
  sort_order: number
}

interface GroupFormValues {
  group_type: RuleGroupType
  combination_method: CombinationMethod
  threshold?: number | null
}

export function StrategyDetailPage() {
  const { strategyId = '' } = useParams()
  const decodedId = decodeURIComponent(strategyId)
  const navigate = useNavigate()
  const { t } = useTranslation()

  const { data: detail, loading, error, reload } = useRequest(
    () => fetchStrategyDetail(decodedId),
    { deps: [decodedId] },
  )

  const { data: factorsPage } = useRequest(() => fetchFactors({ page_size: 200 }))
  const factors = useMemo(() => extractPageItems<Factor>(factorsPage), [factorsPage])

  const [groupModalOpen, setGroupModalOpen] = useState(false)
  const [editingGroup, setEditingGroup] = useState<RuleGroup | null>(null)
  const [groupForm] = Form.useForm<GroupFormValues>()
  const [groupSubmitting, setGroupSubmitting] = useState(false)

  const [bindingModalOpen, setBindingModalOpen] = useState(false)
  const [bindingTargetGroupId, setBindingTargetGroupId] = useState<number | null>(null)
  const [editingBinding, setEditingBinding] = useState<RuleBinding | null>(null)
  const [bindingForm] = Form.useForm<BindingFormValues>()
  const [bindingSubmitting, setBindingSubmitting] = useState(false)

  const ruleGroups: RuleGroup[] = detail?.rule_groups ?? []

  const combinationLabel = (m: CombinationMethod): string => {
    const map: Record<CombinationMethod, string> = {
      and: t('strategy.combinationAnd'),
      or: t('strategy.combinationOr'),
      weighted_score: t('strategy.combinationWeightedScore'),
      weighted_vote: t('strategy.combinationWeightedVote'),
      ic_weighted: t('strategy.combinationIcWeighted'),
    }
    return map[m]
  }

  const groupTypeLabel = (g: RuleGroupType): string =>
    g === 'cross_section' ? t('strategy.groupTypeCrossSection') : t('strategy.groupTypeTimeSeries')

  const openCreateGroup = useCallback(() => {
    setEditingGroup(null)
    groupForm.resetFields()
    groupForm.setFieldsValue({ group_type: 'cross_section', combination_method: 'weighted_score' })
    setGroupModalOpen(true)
  }, [groupForm])

  const openEditGroup = useCallback((group: RuleGroup) => {
    setEditingGroup(group)
    groupForm.setFieldsValue({
      group_type: group.group_type,
      combination_method: group.combination_method,
      threshold: group.threshold,
    })
    setGroupModalOpen(true)
  }, [groupForm])

  const handleSaveGroup = useCallback(async () => {
    const values = await groupForm.validateFields()
    setGroupSubmitting(true)
    try {
      if (editingGroup?.id != null) {
        await updateRuleGroup(decodedId, editingGroup.id, {
          combination_method: values.combination_method,
          threshold: values.threshold ?? null,
        })
      } else {
        await createRuleGroup(decodedId, {
          group_type: values.group_type,
          combination_method: values.combination_method,
          threshold: values.threshold ?? null,
        })
      }
      message.success(t('common.saveSuccess'))
      setGroupModalOpen(false)
      setEditingGroup(null)
      await reload()
    } catch (err) {
      if (err && typeof err === 'object' && 'errorFields' in err) return
      const msg = isApiError(err) ? err.message : err instanceof Error ? err.message : t('common.loadFailed')
      message.error(msg)
    } finally {
      setGroupSubmitting(false)
    }
  }, [decodedId, editingGroup, groupForm, reload, t])

  const handleDeleteGroup = useCallback(
    async (group: RuleGroup) => {
      if (group.id == null) return
      try {
        await deleteRuleGroup(decodedId, group.id)
        message.success(t('strategy.groupDeleteSuccess'))
        await reload()
      } catch (err) {
        const msg = isApiError(err) ? err.message : err instanceof Error ? err.message : t('common.loadFailed')
        message.error(msg)
      }
    },
    [decodedId, reload, t],
  )

  const openCreateBinding = useCallback(
    (groupId: number) => {
      setEditingBinding(null)
      bindingForm.resetFields()
      bindingForm.setFieldsValue({ operator: '>', weight: 1, sort_order: 0 })
      setBindingTargetGroupId(groupId)
      setBindingModalOpen(true)
    },
    [bindingForm],
  )

  const openEditBinding = useCallback(
    (groupId: number, binding: RuleBinding) => {
      setEditingBinding(binding)
      bindingForm.setFieldsValue({
        rule_name: binding.rule?.name ?? binding.rule_id,
        factor_id: binding.rule?.factors?.[0] ?? '',
        operator: '>',
        threshold: 0,
        expression: binding.rule?.expression ?? binding.rule?.spi_class ?? '',
        weight: binding.weight,
        sort_order: binding.sort_order,
      })
      setBindingTargetGroupId(groupId)
      setBindingModalOpen(true)
    },
    [bindingForm],
  )

  const handleSaveBinding = useCallback(async () => {
    if (bindingTargetGroupId == null) return
    const values = await bindingForm.validateFields()
    setBindingSubmitting(true)
    try {
      const expression = values.expression?.trim()
        || `${values.factor_id} ${values.operator} ${values.threshold}`
      if (editingBinding?.id != null) {
        await updateRuleBinding(decodedId, bindingTargetGroupId, editingBinding.id, {
          weight: values.weight,
          sort_order: values.sort_order,
        })
        if (canEditRuleDefinition(editingBinding)) {
          await updateRule(editingBinding.rule_id, {
            name: values.rule_name,
            expression,
            factors: [values.factor_id],
            description: `用户编辑规则：${expression}`,
          })
        }
      } else {
        const ruleId = `user_${Date.now()}`
        const rule = await createRule({
          rule_id: ruleId,
          name: values.rule_name,
          category: 'cross_section',
          type: 'expression',
          expression,
          factors: [values.factor_id],
          signal_mapping: {
            true: { direction: 'long', confidence: 1 },
            false: { direction: 'neutral', confidence: 0 },
          },
          default_config: {},
          description: `用户自定义规则：${expression}`,
          status: 'active',
        })
        await createRuleBinding(decodedId, bindingTargetGroupId, {
          rule_id: rule.rule_id,
          weight: values.weight,
          sort_order: values.sort_order,
        })
      }
      message.success(t('common.saveSuccess'))
      setBindingModalOpen(false)
      setEditingBinding(null)
      await reload()
    } catch (err) {
      if (err && typeof err === 'object' && 'errorFields' in err) return
      const msg = isApiError(err) ? err.message : err instanceof Error ? err.message : t('common.loadFailed')
      message.error(msg)
    } finally {
      setBindingSubmitting(false)
    }
  }, [bindingForm, bindingTargetGroupId, decodedId, editingBinding, reload, t])

  const handleDeleteBinding = useCallback(
    async (groupId: number, binding: RuleBinding) => {
      if (binding.id == null) return
      try {
        await deleteRuleBinding(decodedId, groupId, binding.id)
        message.success(t('strategy.bindingDeleteSuccess'))
        await reload()
      } catch (err) {
        const msg = isApiError(err) ? err.message : err instanceof Error ? err.message : t('common.loadFailed')
        message.error(msg)
      }
    },
    [decodedId, reload, t],
  )

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

  const bindingColumns = (groupId: number): ColumnsType<RuleBinding> => [
    {
      title: t('strategy.selectRule'),
      dataIndex: 'rule_id',
      width: 220,
      render: (val: string, record) => (
        <Space direction="vertical" size={0}>
          <span style={{ fontFamily: 'var(--font-mono)' }}>{val}</span>
          {record.rule?.name && <span style={{ color: 'var(--text-muted)', fontSize: 11 }}>{record.rule.name}</span>}
        </Space>
      ),
    },
    {
      title: t('strategy.ruleType'),
      width: 90,
      render: (_, record) => <Tag>{record.rule?.type ?? '—'}</Tag>,
    },
    {
      title: t('strategy.ruleExpression'),
      key: 'rule_expression',
      render: (_, record) => (
        <Space direction="vertical" size={0}>
          <span style={{ fontFamily: 'var(--font-mono)', whiteSpace: 'pre-wrap' }}>
            {record.rule?.type === 'spi' ? record.rule?.spi_class : record.rule?.expression ?? '—'}
          </span>
          {record.rule?.factors?.length ? (
            <span style={{ color: 'var(--text-muted)', fontSize: 11 }}>
              {t('strategy.relatedFactors')}: {record.rule.factors.join(', ')}
            </span>
          ) : null}
        </Space>
      ),
    },
    {
      title: t('strategy.weight'),
      dataIndex: 'weight',
      width: 100,
      render: (v: number) => v.toFixed(3),
    },
    { title: t('strategy.sortOrder'), dataIndex: 'sort_order', width: 90 },
    {
      title: t('common.action'),
      key: 'actions',
      width: 120,
      render: (_, record) => (
        <Space>
          <Button
            type="text"
            size="small"
            icon={<Pencil size={14} />}
            onClick={() => openEditBinding(groupId, record)}
          />
          <Popconfirm
            title={t('common.delete')}
            onConfirm={() => handleDeleteBinding(groupId, record)}
            okText={t('common.yes')}
            cancelText={t('common.no')}
          >
            <Button type="text" size="small" danger icon={<Trash2 size={14} />} />
          </Popconfirm>
        </Space>
      ),
    },
  ]

  const isEditingRuleDefinition = canEditRuleDefinition(editingBinding)
  const canConfigureRuleDefinition = editingBinding == null || isEditingRuleDefinition

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
                  <Tag color={detail.status === 'active' ? 'green' : detail.status === 'draft' ? 'gold' : 'default'}>
                    {t(`strategy.status${detail.status.charAt(0).toUpperCase() + detail.status.slice(1)}`)}
                  </Tag>
                </Space>
                <Space>
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
                  <span className="strategy-detail__meta-label">{t('strategy.universePool')}</span>
                  <span className="strategy-detail__meta-value">{detail.universe_pool ?? '—'}</span>
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
                  key: 'rules',
                  label: t('strategy.ruleGroups'),
                  children: (
                    <div className="card">
                      <div className="card__header">
                        <h3 className="card__title">{t('strategy.ruleGroups')}</h3>
                        <Button size="small" icon={<Plus size={14} />} onClick={openCreateGroup}>
                          {t('strategy.addRuleGroup')}
                        </Button>
                      </div>
                      <div className="strategy-rule-group__relation-note">
                        {t('strategy.groupRelationNote')}
                      </div>
                      {ruleGroups.length === 0 ? (
                        <div className="strategy-empty">
                          <span>{t('strategy.emptyResult')}</span>
                        </div>
                      ) : (
                        ruleGroups.map((group) => (
                          <div key={group.id ?? group.group_type} className="strategy-rule-group">
                            <div className="strategy-rule-group__header">
                              <div className="strategy-rule-group__title">
                                <Tag color="blue">{groupTypeLabel(group.group_type)}</Tag>
                                <Tag>{combinationLabel(group.combination_method)}</Tag>
                                {group.threshold != null && (
                                  <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>
                                    {t('strategy.threshold')}: {group.threshold}
                                  </span>
                                )}
                              </div>
                              <Space>
                                <Button
                                  size="small"
                                  icon={<Pencil size={12} />}
                                  onClick={() => openEditGroup(group)}
                                >
                                  {t('common.edit')}
                                </Button>
                                <Button
                                  size="small"
                                  icon={<Plus size={12} />}
                                  onClick={() => group.id != null && openCreateBinding(group.id)}
                                  disabled={group.id == null}
                                >
                                  {t('strategy.addRuleBinding')}
                                </Button>
                                <Popconfirm
                                  title={t('common.delete')}
                                  onConfirm={() => handleDeleteGroup(group)}
                                  okText={t('common.yes')}
                                  cancelText={t('common.no')}
                                >
                                  <Button size="small" danger type="text" icon={<Trash2 size={14} />} />
                                </Popconfirm>
                              </Space>
                            </div>
                            {group.combination_params && Object.keys(group.combination_params).length > 0 && (
                              <details>
                                <summary style={{ cursor: 'pointer', color: 'var(--text-muted)', fontSize: 12 }}>
                                  combination_params
                                </summary>
                                <pre className="strategy-code-block">
                                  {JSON.stringify(group.combination_params, null, 2)}
                                </pre>
                              </details>
                            )}
                            <Table<RuleBinding>
                              size="small"
                              dataSource={group.bindings ?? []}
                              columns={group.id != null ? bindingColumns(group.id) : []}
                              rowKey={(r) => String(r.id ?? `${r.rule_id}_${r.sort_order}`)}
                              pagination={false}
                              locale={{ emptyText: '—' }}
                            />
                          </div>
                        ))
                      )}
                    </div>
                  ),
                },
                {
                  key: 'json',
                  label: t('strategy.jsonConfig'),
                  children: (
                    <div className="card">
                      <h4 style={{ marginTop: 0, color: 'var(--text-secondary)', fontSize: 12 }}>
                        {t('strategy.crossSectionConfig')}
                      </h4>
                      <pre className="strategy-code-block">
                        {JSON.stringify(detail.cross_section_config ?? null, null, 2)}
                      </pre>
                      <h4 style={{ color: 'var(--text-secondary)', fontSize: 12 }}>
                        {t('strategy.timeSeriesConfig')}
                      </h4>
                      <pre className="strategy-code-block">
                        {JSON.stringify(detail.time_series_config ?? null, null, 2)}
                      </pre>
                      <h4 style={{ color: 'var(--text-secondary)', fontSize: 12 }}>
                        {t('strategy.positionSizingConfig')}
                      </h4>
                      <pre className="strategy-code-block">
                        {JSON.stringify(detail.position_sizing_config ?? null, null, 2)}
                      </pre>
                      <h4 style={{ color: 'var(--text-secondary)', fontSize: 12 }}>
                        {t('strategy.riskOverrides')}
                      </h4>
                      <pre className="strategy-code-block">
                        {JSON.stringify(detail.risk_overrides ?? null, null, 2)}
                      </pre>
                    </div>
                  ),
                },
              ]}
            />
          </>
        )}
      </AsyncSection>

      <Modal
        open={groupModalOpen}
        title={editingGroup ? t('strategy.editRuleGroup') : t('strategy.addRuleGroup')}
        onCancel={() => {
          setGroupModalOpen(false)
          setEditingGroup(null)
        }}
        onOk={() => void handleSaveGroup()}
        confirmLoading={groupSubmitting}
        destroyOnClose
      >
        <Form<GroupFormValues> form={groupForm} layout="vertical">
          <Form.Item label={t('strategy.groupType')} name="group_type" rules={[{ required: true }]}>
            <Select
              disabled={editingGroup != null}
              options={GROUP_TYPE_OPTIONS.map((g) => ({ label: groupTypeLabel(g), value: g }))}
            />
          </Form.Item>
          <Form.Item
            label={t('strategy.combinationMethod')}
            name="combination_method"
            rules={[{ required: true }]}
          >
            <Select
              options={COMBINATION_OPTIONS.map((m) => ({ label: combinationLabel(m), value: m }))}
            />
          </Form.Item>
          <Form.Item label={t('strategy.threshold')} name="threshold">
            <InputNumber style={{ width: '100%' }} step={0.01} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        open={bindingModalOpen}
        title={editingBinding ? t('strategy.editRuleBinding') : t('strategy.addRuleBinding')}
        onCancel={() => {
          setBindingModalOpen(false)
          setEditingBinding(null)
        }}
        onOk={() => void handleSaveBinding()}
        confirmLoading={bindingSubmitting}
        destroyOnClose
      >
        <Form<BindingFormValues> form={bindingForm} layout="vertical">
          <Form.Item
            label={t('strategy.ruleName')}
            name="rule_name"
            rules={[{ required: canConfigureRuleDefinition }]}
          >
            <Input disabled={!canConfigureRuleDefinition} placeholder={t('strategy.ruleNamePlaceholder')} />
          </Form.Item>
          <Form.Item
            label={t('strategy.selectFactor')}
            name="factor_id"
            rules={[{ required: canConfigureRuleDefinition }]}
          >
            <Select
              disabled={!canConfigureRuleDefinition}
              showSearch
              optionFilterProp="label"
              placeholder={t('strategy.selectFactor')}
              options={factors.map((f) => ({
                label: `${f.display_name} (${f.factor_id})${f.description ? ` — ${f.description}` : ''}`,
                value: f.factor_id,
              }))}
            />
          </Form.Item>
          <Space.Compact style={{ width: '100%' }}>
            <Form.Item
              label={t('strategy.operator')}
              name="operator"
              rules={[{ required: true }]}
              style={{ width: '35%' }}
            >
              <Select
                disabled={!canConfigureRuleDefinition}
                options={['>', '>=', '<', '<=', '==', '!='].map((op) => ({ label: op, value: op }))}
              />
            </Form.Item>
            <Form.Item
              label={t('strategy.factorThreshold')}
              name="threshold"
              rules={[{ required: true }]}
              style={{ width: '65%' }}
            >
              <InputNumber style={{ width: '100%' }} />
            </Form.Item>
          </Space.Compact>
          <Form.Item label={t('strategy.expressionPreview')} name="expression">
            <Input.TextArea
              disabled={!canConfigureRuleDefinition}
              rows={2}
              placeholder={!canConfigureRuleDefinition ? t('strategy.ruleReadonly') : t('strategy.expressionPlaceholder')}
            />
          </Form.Item>
          <Form.Item label={t('strategy.weight')} name="weight" initialValue={1}>
            <InputNumber style={{ width: '100%' }} step={0.1} min={0} />
          </Form.Item>
          <Form.Item label={t('strategy.sortOrder')} name="sort_order" initialValue={0}>
            <InputNumber style={{ width: '100%' }} step={1} min={0} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
