import { Button, Tag, Tooltip } from 'antd'
import { FileText, RefreshCw } from 'lucide-react'
import { useTranslation } from 'react-i18next'

import type { StockDiagnosisHistoryResponse, StockDiagnosisResponse } from '@/api/stock'
import { DiagnosisTrendChart } from '@/components/stock/DiagnosisTrendChart'

const SCORE_TOOLTIP =
  '综合得分 0–10 分，由六模块加权：技术面 20%、资金面 20%、基本面 20%、消息面 15%、行业面 15%、机构面 10%。'

interface DiagnosisHeroProps {
  data: StockDiagnosisResponse
  history?: StockDiagnosisHistoryResponse
  historyLoading?: boolean
  loading?: boolean
  onRefresh?: () => void
  onOpenReports?: () => void
}

export function DiagnosisHero({
  data,
  history,
  historyLoading,
  loading,
  onRefresh,
  onOpenReports,
}: DiagnosisHeroProps) {
  const { t } = useTranslation()
  const trendItems = history?.items ?? []

  const hasScore = data.overall_score != null
  const scoreDelta =
    hasScore && data.prev_overall_score != null
      ? Number((data.overall_score! - data.prev_overall_score).toFixed(1))
      : null

  return (
    <section className="diagnosis-hero">
      <div className="diagnosis-hero__score-block">
        <div className="stock-diagnosis__score-label">
          {t('stock.diagnosis.overallScore')}
          <Tooltip title={SCORE_TOOLTIP}>
            <span className="stock-diagnosis__score-help">?</span>
          </Tooltip>
        </div>
        <div className="stock-diagnosis__score-value">
          {hasScore ? `${data.overall_score}分` : '—'}
          {data.rating_label ? (
            <Tag className="stock-diagnosis__rating-tag">{data.rating_label}</Tag>
          ) : null}
        </div>
        <div className="stock-diagnosis__score-meta">
          {data.market_percentile != null ? (
            <span className="diagnosis-hero__percentile">
              {t('stock.diagnosis.beatPercentile', { pct: data.market_percentile.toFixed(0) })}
            </span>
          ) : null}
          <span className="stock-diagnosis__legend stock-diagnosis__legend--current">
            {t('stock.diagnosis.currentPeriod')}
          </span>
          {data.prev_overall_score != null ? (
            <span className="stock-diagnosis__legend stock-diagnosis__legend--prev">
              {t('stock.diagnosis.prevScore', { score: data.prev_overall_score.toFixed(1) })}
            </span>
          ) : null}
          {scoreDelta != null && scoreDelta !== 0 ? (
            <span
              className={
                scoreDelta > 0
                  ? 'stock-diagnosis__score-delta stock-diagnosis__score-delta--up'
                  : 'stock-diagnosis__score-delta stock-diagnosis__score-delta--down'
              }
            >
              {scoreDelta > 0
                ? t('stock.diagnosis.scoreDeltaUp', { delta: scoreDelta.toFixed(1) })
                : t('stock.diagnosis.scoreDeltaDown', { delta: scoreDelta.toFixed(1) })}
            </span>
          ) : null}
          <span className="stock-diagnosis__as-of">{data.as_of}</span>
          {data.cached ? <Tag color="blue">{t('stock.diagnosis.cached')}</Tag> : null}
        </div>
      </div>

      <div className="diagnosis-hero__trend-block">
        <div className="diagnosis-hero__trend-title">{t('stock.diagnosis.scoreTrend')}</div>
        {trendItems.length > 0 ? <DiagnosisTrendChart items={trendItems} compact /> : null}
        {!historyLoading && trendItems.length === 0 ? (
          <span className="diagnosis-hero__trend-empty">{t('stock.diagnosis.trendEmpty')}</span>
        ) : null}
        {historyLoading ? <span className="diagnosis-hero__trend-loading">{t('common.loading')}</span> : null}
      </div>

      <div className="stock-diagnosis__actions diagnosis-hero__actions">
        {data.reports_count > 0 ? (
          <Button icon={<FileText size={14} />} onClick={onOpenReports}>
            {t('stock.diagnosis.viewAllReports', { count: data.reports_count })}
          </Button>
        ) : null}
        <Tooltip title={t('stock.diagnosis.refreshTooltip')}>
          <Button icon={<RefreshCw size={14} />} onClick={onRefresh} loading={loading}>
            {t('common.refresh')}
          </Button>
        </Tooltip>
      </div>
    </section>
  )
}
