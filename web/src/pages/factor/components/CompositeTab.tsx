import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { Alert, Button, Empty, Table, Tag } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import type { Factor } from '@/api'
import { GRADE_COLOR, type FactorGrade } from '../utils/factor'

interface CompositeTabProps {
  factors: Factor[]
  onSelectFactor: (factorId: string) => void
}

export function CompositeTab({ factors, onSelectFactor }: CompositeTabProps) {
  const { t } = useTranslation()

  const composites = useMemo(
    () => factors.filter((f) => Number(f.is_composite) === 1),
    [factors],
  )

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
      title: t('factor.composite.method'),
      dataIndex: 'composite_method',
      width: 130,
      render: (v: string | null) => (v ? <Tag style={{ margin: 0 }}>{v}</Tag> : '—'),
    },
    {
      title: t('factor.composite.childCount'),
      dataIndex: 'composite_factor_ids',
      width: 100,
      align: 'center',
      render: (v: string | null) => (v ? v.split(',').filter(Boolean).length : 0),
    },
    {
      title: t('factor.library.grade'),
      dataIndex: 'factor_grade',
      width: 80,
      render: (v: string | null) =>
        v ? <Tag color={GRADE_COLOR[v as FactorGrade]} style={{ margin: 0 }}>{v}</Tag> : '—',
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
      <Alert
        type="info"
        showIcon
        banner
        message={t('factor.composite.lineageHint')}
        style={{ marginBottom: 10 }}
      />
      {composites.length === 0 ? (
        <Empty description={t('factor.composite.empty')} />
      ) : (
        <Table<Factor>
          rowKey="factor_id"
          size="small"
          columns={columns}
          dataSource={composites}
          pagination={false}
          onRow={(r) => ({ onClick: () => onSelectFactor(r.factor_id), style: { cursor: 'pointer' } })}
        />
      )}
    </div>
  )
}
