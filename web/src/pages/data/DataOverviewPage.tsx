import { Button } from 'antd'
import { RefreshCw } from 'lucide-react'
import { useTranslation } from 'react-i18next'

import {
  fetchDataSummary,
  fetchStockTables,
  fetchWatermarks,
  type DataSummaryResponse,
  type StockTableStatItem,
  type WatermarkSummaryItem,
  type WatermarksResponse,
} from '@/api/data'
import { AsyncSection } from '@/components/common/AsyncSection'
import { StockTablesPanel } from '@/components/data/StockTablesPanel'
import { WatermarkRangeChart } from '@/components/data/WatermarkRangeChart'
import { useRequest } from '@/hooks/useRequest'
import '@/styles/data.css'

function formatNumber(value: number): string {
  return value.toLocaleString()
}

function formatBytes(bytes: number): string {
  if (bytes >= 1024 ** 3) {
    return `${(bytes / 1024 ** 3).toFixed(2)} GB`
  }
  if (bytes >= 1024 ** 2) {
    return `${(bytes / 1024 ** 2).toFixed(1)} MB`
  }
  return `${(bytes / 1024).toFixed(1)} KB`
}

function SummaryCards({
  data,
  loading,
  error,
  onRetry,
}: {
  data: DataSummaryResponse | undefined
  loading: boolean
  error: string | null
  onRetry: () => void
}) {
  const { t } = useTranslation()
  return (
    <AsyncSection loading={loading && !data} error={error} onRetry={onRetry}>
      <div className="page-grid page-grid--4">
        <div className="card">
          <div className="card__header">
            <h3 className="card__title">{t('data.overview.pipelineCount')}</h3>
          </div>
          <div className="card__value">{data?.pipeline_count ?? '--'}</div>
        </div>
        <div className="card">
          <div className="card__header">
            <h3 className="card__title">{t('data.overview.totalCodes')}</h3>
          </div>
          <div className="card__value">{data ? formatNumber(data.total_codes) : '--'}</div>
        </div>
        <div className="card">
          <div className="card__header">
            <h3 className="card__title">{t('data.overview.totalRecords')}</h3>
          </div>
          <div className="card__value">{data ? formatNumber(data.total_records) : '--'}</div>
        </div>
        <div className="card">
          <div className="card__header">
            <h3 className="card__title">{t('data.overview.stockStorage')}</h3>
          </div>
          <div className="card__value">{data ? formatBytes(data.stock_total_bytes) : '--'}</div>
          <div className="card__sub">
            {t('data.overview.tableCount', { count: data?.stock_table_count ?? 0 })}
          </div>
        </div>
      </div>
    </AsyncSection>
  )
}

function WatermarkSection({
  items,
  referenceTradeDate,
  loading,
  error,
  onRetry,
}: {
  items: WatermarkSummaryItem[]
  referenceTradeDate: string | null
  loading: boolean
  error: string | null
  onRetry: () => void
}) {
  const { t } = useTranslation()
  return (
    <div className="card">
      <div className="card__header">
        <h3 className="card__title">{t('data.watermark.title')}</h3>
        <span className="card__sub">{t('data.watermark.subtitle')}</span>
      </div>
      <AsyncSection loading={loading && items.length === 0} error={error} onRetry={onRetry}>
        <WatermarkRangeChart items={items} referenceTradeDate={referenceTradeDate} />
      </AsyncSection>
    </div>
  )
}

function TablesSection({
  tables,
  loading,
  error,
  onRetry,
}: {
  tables: StockTableStatItem[]
  loading: boolean
  error: string | null
  onRetry: () => void
}) {
  const { t } = useTranslation()
  return (
    <div className="card">
      <div className="card__header">
        <h3 className="card__title">{t('data.tables.title')}</h3>
        <span className="card__sub">{t('data.tables.subtitle')}</span>
      </div>
      <AsyncSection loading={loading && tables.length === 0} error={error} onRetry={onRetry}>
        <StockTablesPanel tables={tables} />
      </AsyncSection>
    </div>
  )
}

export function DataOverviewPage() {
  const { t } = useTranslation()
  const summary = useRequest(fetchDataSummary)
  const watermarks = useRequest(fetchWatermarks)
  const tables = useRequest(fetchStockTables)

  const anyLoading = summary.loading || watermarks.loading || tables.loading

  const reloadAll = async () => {
    await Promise.all([summary.reload(), watermarks.reload(), tables.reload()])
  }

  return (
    <div className="page">
      <div className="page-header">
        <span />
        <Button icon={<RefreshCw size={14} />} loading={anyLoading} onClick={() => void reloadAll()}>
          {t('common.refresh')}
        </Button>
      </div>

      <SummaryCards
        data={summary.data as DataSummaryResponse | undefined}
        loading={summary.loading}
        error={summary.error}
        onRetry={() => void summary.reload()}
      />

      <WatermarkSection
        items={(watermarks.data as WatermarksResponse | undefined)?.items ?? []}
        referenceTradeDate={(watermarks.data as WatermarksResponse | undefined)?.reference_trade_date ?? null}
        loading={watermarks.loading}
        error={watermarks.error}
        onRetry={() => void watermarks.reload()}
      />

      <TablesSection
        tables={(tables.data as StockTableStatItem[] | undefined) ?? []}
        loading={tables.loading}
        error={tables.error}
        onRetry={() => void tables.reload()}
      />
    </div>
  )
}
