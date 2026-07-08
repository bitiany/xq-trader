import { Descriptions, Drawer, Empty, Table } from 'antd'
import { useTranslation } from 'react-i18next'

import type { DiagnosisDimension, DiagnosisEarningsPreviewItem } from '@/api/stock'

interface DiagnosisDimensionDrawerProps {
  open: boolean
  dimension: DiagnosisDimension | null
  earningsPreview?: DiagnosisEarningsPreviewItem[]
  onClose: () => void
}

function formatDetailValue(value: unknown): string {
  if (value == null) return '—'
  if (typeof value === 'number') return Number.isInteger(value) ? String(value) : value.toFixed(2)
  if (typeof value === 'boolean') return value ? '是' : '否'
  if (Array.isArray(value)) return value.length > 0 ? JSON.stringify(value) : '—'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

const DETAIL_LABELS: Record<string, string> = {
  report_count: '研报数量',
  rating_part: '评级得分',
  eps_part: 'EPS 得分',
  reason: '说明',
  factor_percentile: '因子分位',
  technical_score: '技术得分',
  volatility_percentile: '波动分位',
  beta_percentile: 'Beta 分位',
  growth_percentile: '成长分位',
  quality_percentile: '质量分位',
  leverage_percentile: '杠杆分位',
  value_percentile: '估值分位',
  liquidity_percentile: '流动性分位',
  sentiment_penalty: '舆情惩罚',
}

export function DiagnosisDimensionDrawer({
  open,
  dimension,
  earningsPreview,
  onClose,
}: DiagnosisDimensionDrawerProps) {
  const { t } = useTranslation()

  if (!dimension) {
    return (
      <Drawer open={open} onClose={onClose} title={t('stock.diagnosis.dimensionDetail')} width={560}>
        <Empty />
      </Drawer>
    )
  }

  const detailEntries = Object.entries(dimension.detail ?? {}).filter(
    ([, value]) => value != null && value !== '',
  )

  const earningsColumns = [
    { title: t('stock.diagnosis.reportDate'), dataIndex: 'publish_date', key: 'publish_date', width: 110 },
    { title: t('stock.diagnosis.reportOrg'), dataIndex: 'org_name', key: 'org_name', ellipsis: true },
    { title: t('stock.diagnosis.reportRating'), dataIndex: 'rating', key: 'rating', width: 80 },
    {
      title: t('stock.diagnosis.reportTitle'),
      dataIndex: 'title',
      key: 'title',
      ellipsis: true,
    },
  ]

  return (
    <Drawer
      open={open}
      onClose={onClose}
      title={`${dimension.label} · ${dimension.score != null ? dimension.score.toFixed(1) : '—'}分`}
      width={640}
      destroyOnClose
    >
      <Descriptions column={1} size="small" bordered>
        <Descriptions.Item label={t('stock.diagnosis.dimensionWeight')}>
          {(dimension.weight * 100).toFixed(0)}%
        </Descriptions.Item>
        {dimension.prev_score != null ? (
          <Descriptions.Item label={t('stock.diagnosis.prevPeriod')}>
            {dimension.prev_score.toFixed(1)}分
          </Descriptions.Item>
        ) : null}
        {detailEntries.map(([key, value]) => (
          <Descriptions.Item key={key} label={DETAIL_LABELS[key] ?? key}>
            {formatDetailValue(value)}
          </Descriptions.Item>
        ))}
      </Descriptions>

      {dimension.key === 'earnings' ? (
        <div className="stock-diagnosis__earnings-preview">
          <h4>{t('stock.diagnosis.earningsReports')}</h4>
          {earningsPreview && earningsPreview.length > 0 ? (
            <Table
              size="small"
              rowKey="info_code"
              pagination={{ pageSize: 8, showSizeChanger: false }}
              dataSource={earningsPreview}
              columns={earningsColumns}
            />
          ) : (
            <Empty description={t('stock.diagnosis.earningsReportsEmpty')} image={Empty.PRESENTED_IMAGE_SIMPLE} />
          )}
        </div>
      ) : null}
    </Drawer>
  )
}
