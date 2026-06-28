import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Alert, Button, Input, Select, Space, Table, Tag } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { ArrowDown, ArrowUp, Layers } from 'lucide-react'
import { fetchFactors, type Factor, type FactorCategoryStat, type FactorStatus } from '@/api'
import { extractPageItems } from '@/api/types'
import { AsyncSection } from '@/components/common/AsyncSection'
import { useRequest } from '@/hooks/useRequest'
import { GRADE_COLOR, STATUS_COLOR, type FactorGrade } from '../utils/factor'

interface FactorLibraryTabProps {
  categories: FactorCategoryStat[]
  onSelectFactor: (factorId: string) => void
}

const PAGE_SIZE = 20
const GRADE_OPTIONS: FactorGrade[] = ['A', 'B', 'C', 'D']
const STATUS_OPTIONS: FactorStatus[] = ['active', 'testing', 'draft', 'deprecated']

export function FactorLibraryTab({ categories, onSelectFactor }: FactorLibraryTabProps) {
  const { t } = useTranslation()
  const [category, setCategory] = useState<string | undefined>(undefined)
  const [status, setStatus] = useState<FactorStatus | undefined>(undefined)
  const [keyword, setKeyword] = useState('')
  const [grade, setGrade] = useState<FactorGrade | undefined>(undefined)
  const [onlyUsable, setOnlyUsable] = useState(false)
  const [page, setPage] = useState(1)

  const { data, loading, error, reload } = useRequest(
    () =>
      fetchFactors({
        page,
        page_size: PAGE_SIZE,
        category,
        status,
        keyword: keyword || undefined,
        factor_grade: grade,
        usable_only: onlyUsable || undefined,
      }),
    { deps: [page, category, status, keyword, grade, onlyUsable] },
  )

  const items = data ? extractPageItems<Factor>(data) : []
  const total = data?.total ?? 0

  const columns: ColumnsType<Factor> = [
    {
      title: t('factor.library.name'),
      dataIndex: 'display_name',
      render: (v: string, r) => (
        <div>
          <div style={{ fontWeight: 600 }}>{v}</div>
          <div style={{ fontSize: 11, color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)' }}>
            {r.factor_id}
          </div>
        </div>
      ),
    },
    {
      title: t('factor.library.category'),
      dataIndex: 'category',
      width: 110,
      render: (v: string) => <Tag style={{ margin: 0 }}>{v}</Tag>,
    },
    {
      title: t('factor.library.direction'),
      dataIndex: 'direction',
      width: 80,
      render: (v: string) =>
        v === 'ASC' ? (
          <Space size={2}><ArrowUp size={12} />ASC</Space>
        ) : (
          <Space size={2}><ArrowDown size={12} />DESC</Space>
        ),
    },
    {
      title: t('factor.library.grade'),
      dataIndex: 'factor_grade',
      width: 80,
      render: (v: string | null) =>
        v ? <Tag color={GRADE_COLOR[v as FactorGrade]} style={{ margin: 0 }}>{v}</Tag> : <span style={{ color: 'var(--text-secondary)' }}>—</span>,
    },
    {
      title: t('factor.library.composite'),
      dataIndex: 'is_composite',
      width: 70,
      align: 'center',
      render: (v: number | null) => (v ? <Layers size={14} color="var(--accent-primary)" /> : null),
    },
    {
      title: t('factor.library.status'),
      dataIndex: 'status',
      width: 90,
      render: (v: FactorStatus) => <Tag color={STATUS_COLOR[v]} style={{ margin: 0 }}>{v}</Tag>,
    },
    {
      title: t('factor.library.actions'),
      key: 'actions',
      width: 80,
      render: (_, r) => (
        <Button type="link" size="small" onClick={() => onSelectFactor(r.factor_id)}>
          {t('factor.library.detail')}
        </Button>
      ),
    },
  ]

  return (
    <div>
      <Space wrap style={{ marginBottom: 10 }}>
        <Input.Search
          placeholder={t('factor.library.keyword')}
          allowClear
          size="small"
          style={{ width: 200 }}
          onSearch={(v) => { setKeyword(v); setPage(1) }}
        />
        <Select
          allowClear
          size="small"
          style={{ width: 150 }}
          placeholder={t('factor.library.allCategories')}
          value={category}
          onChange={(v) => { setCategory(v); setPage(1) }}
          options={categories.map((c) => ({ value: c.category, label: `${c.category} (${c.count})` }))}
        />
        <Select
          allowClear
          size="small"
          style={{ width: 130 }}
          placeholder={t('factor.library.allGrades')}
          value={grade}
          onChange={(v) => { setGrade(v); setPage(1) }}
          options={GRADE_OPTIONS.map((g) => ({ value: g, label: g }))}
        />
        <Select
          allowClear
          size="small"
          style={{ width: 130 }}
          placeholder={t('factor.library.allStatus')}
          value={status}
          onChange={(v) => { setStatus(v); setPage(1) }}
          options={STATUS_OPTIONS.map((s) => ({ value: s, label: s }))}
        />
        <Button
          size="small"
          type={onlyUsable ? 'primary' : 'default'}
          onClick={() => { setOnlyUsable((v) => !v); setPage(1) }}
        >
          {t('factor.library.onlyUsable')}
        </Button>
      </Space>

      <Alert
        type="info"
        showIcon
        banner
        message={t('factor.library.metricsHint')}
        style={{ marginBottom: 10 }}
      />

      <AsyncSection loading={loading} error={error} onRetry={reload}>
        <Table<Factor>
          rowKey="factor_id"
          size="small"
          columns={columns}
          dataSource={items}
          pagination={{
            current: page,
            pageSize: PAGE_SIZE,
            total,
            size: 'small',
            showSizeChanger: false,
            onChange: setPage,
          }}
          onRow={(r) => ({ onClick: () => onSelectFactor(r.factor_id), style: { cursor: 'pointer' } })}
        />
      </AsyncSection>
    </div>
  )
}
