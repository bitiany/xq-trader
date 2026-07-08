import { Descriptions, Drawer, Empty, Table } from 'antd'
import { useTranslation } from 'react-i18next'

import type { DiagnosisEarningsPreviewItem, DiagnosisModuleScore } from '@/api/stock'
import { formatDate } from '@/utils/format'
import { translateDiagnosisTerm } from '@/utils/diagnosisTechnical'

interface DiagnosisModuleDrawerProps {
  open: boolean
  module: DiagnosisModuleScore | null
  onClose: () => void
}

const HIDDEN_DETAIL_KEYS = new Set([
  'earnings_preview',
  'recent_news',
  'rings',
  'signals',
  'flow_series',
  'period_trend',
  'highlights',
])

function formatScalarValue(value: unknown): string {
  if (value == null) return '—'
  if (typeof value === 'number') return Number.isInteger(value) ? String(value) : value.toFixed(2)
  if (typeof value === 'boolean') return value ? '是' : '否'
  return String(value)
}

interface FlowSeriesItem {
  trade_date?: string
  main_net_pct?: number | null
  main_net_amt?: number | null
}

function CapitalFlowDetail({ detail }: { detail: Record<string, unknown> }) {
  const { t } = useTranslation()
  const flowSeries = (detail.flow_series as FlowSeriesItem[] | undefined) ?? []

  const columns = [
    {
      title: t('stock.fundFlow.tradeDate'),
      dataIndex: 'trade_date',
      key: 'trade_date',
      width: 110,
      render: (value: string) => formatDate(value),
    },
    {
      title: `${t('stock.fundFlow.mainNetPct')}（%）`,
      dataIndex: 'main_net_pct',
      key: 'main_net_pct',
      width: 120,
      render: (value: number | null) => (value != null ? value.toFixed(2) : '—'),
    },
    {
      title: `${t('stock.fundFlow.mainNetAmt')}（万元）`,
      dataIndex: 'main_net_amt',
      key: 'main_net_amt',
      width: 130,
      render: (value: number | null) => (value != null ? value.toFixed(2) : '—'),
    },
  ]

  return (
    <div className="diagnosis-module-drawer__section">
      <h4>{t('stock.diagnosis.capitalFlow.seriesTitle')}</h4>
      {flowSeries.length > 0 ? (
        <Table
          size="small"
          rowKey={(row) => row.trade_date ?? String(row.main_net_pct)}
          pagination={false}
          dataSource={[...flowSeries].reverse()}
          columns={columns}
          scroll={{ y: 280 }}
        />
      ) : (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} />
      )}
    </div>
  )
}

function TechnicalDetail({ detail }: { detail: Record<string, unknown> }) {
  const { t } = useTranslation()
  const signals = (detail.signals as Array<{ name: string; value: string }> | undefined) ?? []

  const horizons = [
    { key: 'short', label: t('stock.diagnosis.technical.horizon.short'), value: detail.short_label },
    { key: 'mid', label: t('stock.diagnosis.technical.horizon.mid'), value: detail.mid_label },
    { key: 'long', label: t('stock.diagnosis.technical.horizon.long'), value: detail.long_label },
  ]

  return (
    <>
      <div className="diagnosis-module-drawer__badges">
        {horizons.map((item) => (
          <span key={item.key} className="diagnosis-badge">
            {item.label} {translateDiagnosisTerm(item.value as string, t)}
          </span>
        ))}
      </div>
      {signals.length > 0 ? (
        <Table
          size="small"
          rowKey={(row) => row.name}
          pagination={false}
          dataSource={signals}
          columns={[
            { title: t('stock.diagnosis.technical.indicator'), dataIndex: 'name', key: 'name', width: 100 },
            {
              title: t('stock.diagnosis.technical.signalLabel'),
              dataIndex: 'value',
              key: 'value',
              render: (value: string) => translateDiagnosisTerm(value, t),
            },
          ]}
        />
      ) : null}
    </>
  )
}

function FundamentalDetail({ detail }: { detail: Record<string, unknown> }) {
  const { t } = useTranslation()
  const rings = (detail.rings as Record<string, number | null> | undefined) ?? {}
  const highlights = (detail.highlights as Record<string, number | string | null> | undefined) ?? {}
  const periodTrend = (detail.period_trend as Array<Record<string, unknown>> | undefined) ?? []

  const ringRows = Object.entries(rings).map(([key, value]) => ({
    key,
    label: t(`stock.diagnosis.fundamental.rings.${key}`, key),
    score: value,
  }))

  return (
    <>
      {ringRows.length > 0 ? (
        <Table
          size="small"
          rowKey="key"
          pagination={false}
          dataSource={ringRows}
          columns={[
            { title: t('stock.diagnosis.fundamental.ringDimension'), dataIndex: 'label', key: 'label' },
            {
              title: t('stock.diagnosis.moduleScore'),
              dataIndex: 'score',
              key: 'score',
              width: 90,
              render: (value: number | null) => (value != null ? value.toFixed(1) : '—'),
            },
          ]}
        />
      ) : null}
      {Object.keys(highlights).length > 0 ? (
        <Descriptions column={2} size="small" bordered className="diagnosis-module-drawer__highlights">
          {Object.entries(highlights).map(([key, value]) => (
            <Descriptions.Item key={key} label={t(`stock.diagnosis.fundamental.highlights.${key}`, key)}>
              {formatScalarValue(value)}
            </Descriptions.Item>
          ))}
        </Descriptions>
      ) : null}
      {periodTrend.length > 0 ? (
        <div className="diagnosis-module-drawer__section">
          <h4>{t('stock.diagnosis.fundamental.periodTrend')}</h4>
          <Table
            size="small"
            rowKey={(row) => String(row.end_date)}
            pagination={false}
            dataSource={periodTrend}
            columns={[
              {
                title: t('stock.financials.reportPeriod'),
                dataIndex: 'end_date',
                key: 'end_date',
                width: 110,
                render: (value: string) => formatDate(value),
              },
              { title: 'ROE', dataIndex: 'roe', key: 'roe', render: (v: number) => formatScalarValue(v) },
              { title: 'ROA', dataIndex: 'roa', key: 'roa', render: (v: number) => formatScalarValue(v) },
              {
                title: t('stock.financials.debtRatio'),
                dataIndex: 'debt_to_assets',
                key: 'debt_to_assets',
                render: (v: number) => formatScalarValue(v),
              },
            ]}
            scroll={{ x: 480 }}
          />
        </div>
      ) : null}
    </>
  )
}

function SentimentDetail({ detail }: { detail: Record<string, unknown> }) {
  const recentNews = (detail.recent_news as Array<{ title?: string; published_at?: string }> | undefined) ?? []
  if (recentNews.length === 0) return null

  return (
    <div className="diagnosis-module-drawer__section">
      <ul className="diagnosis-news-list">
        {recentNews.map((item, index) => (
          <li key={`${item.published_at ?? index}-${item.title ?? index}`}>
            <span className="diagnosis-news-list__date">{formatDate(item.published_at)}</span>
            <span className="diagnosis-news-list__title">{item.title ?? '—'}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

export function DiagnosisModuleDrawer({ open, module, onClose }: DiagnosisModuleDrawerProps) {
  const { t } = useTranslation()

  if (!module) {
    return (
      <Drawer open={open} onClose={onClose} title={t('stock.diagnosis.moduleDetail')} size={560}>
        <Empty />
      </Drawer>
    )
  }

  const detail = module.detail ?? {}
  const earningsPreview = (detail.earnings_preview as DiagnosisEarningsPreviewItem[] | undefined) ?? []
  const extraHidden =
    module.key === 'technical'
      ? ['short_label', 'mid_label', 'long_label', 'direction', 'support', 'resistance', 'adx']
      : []
  const detailEntries = Object.entries(detail).filter(
    ([key, value]) =>
      !HIDDEN_DETAIL_KEYS.has(key) &&
      !extraHidden.includes(key) &&
      value != null &&
      value !== '',
  )

  const detailLabel = (key: string): string => t(`stock.diagnosis.detail.${key}`, key)

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
      title={`${module.label} · ${module.score != null ? module.score.toFixed(1) : '—'}${t('stock.diagnosis.scoreUnit')}`}
      size={640}
      destroyOnClose
    >
      <Descriptions column={1} size="small" bordered>
        <Descriptions.Item label={t('stock.diagnosis.moduleWeight')}>
          {(module.weight * 100).toFixed(0)}%
        </Descriptions.Item>
        <Descriptions.Item label={t('stock.diagnosis.prevPeriod')}>
          {module.prev_score != null ? `${module.prev_score.toFixed(1)}${t('stock.diagnosis.scoreUnit')}` : '—'}
        </Descriptions.Item>
        {detailEntries.map(([key, value]) => (
          <Descriptions.Item key={key} label={detailLabel(key)}>
            {typeof value === 'string' && (key.endsWith('_label') || key === 'flow_trend' || key === 'direction')
              ? translateDiagnosisTerm(value, t)
              : formatScalarValue(value)}
          </Descriptions.Item>
        ))}
      </Descriptions>

      {module.key === 'capital_flow' ? <CapitalFlowDetail detail={detail} /> : null}
      {module.key === 'technical' ? <TechnicalDetail detail={detail} /> : null}
      {module.key === 'fundamental' ? <FundamentalDetail detail={detail} /> : null}
      {module.key === 'sentiment' ? <SentimentDetail detail={detail} /> : null}

      {module.key === 'institutional' && earningsPreview.length > 0 ? (
        <div className="stock-diagnosis__earnings-preview">
          <h4>{t('stock.diagnosis.earningsReports')}</h4>
          <Table
            size="small"
            rowKey="info_code"
            pagination={false}
            dataSource={earningsPreview}
            columns={earningsColumns}
            scroll={{ x: 520 }}
          />
        </div>
      ) : null}
    </Drawer>
  )
}
