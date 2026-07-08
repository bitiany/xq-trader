import { Alert, Button, Empty, Spin, Tag } from 'antd'

import { useMemo, useState, useCallback } from 'react'

import { useTranslation } from 'react-i18next'



import { triggerStockDiagnosisSummary, type StockDiagnosisHistoryResponse, type StockDiagnosisResponse } from '@/api/stock'

import { CapitalFlowModuleCard } from '@/components/stock/CapitalFlowModuleCard'

import { DiagnosisHero } from '@/components/stock/DiagnosisHero'

import { DiagnosisIntro } from '@/components/stock/DiagnosisIntro'

import { DiagnosisModuleDrawer } from '@/components/stock/DiagnosisModuleDrawer'

import { DiagnosisModuleStrip } from '@/components/stock/DiagnosisModuleStrip'

import { DiagnosisRadarChart } from '@/components/stock/DiagnosisRadarChart'

import { DiagnosisReportsDrawer } from '@/components/stock/DiagnosisReportsDrawer'

import { DiagnosisSummaryBox } from '@/components/stock/DiagnosisSummaryBox'

import { FundamentalModuleCard } from '@/components/stock/FundamentalModuleCard'

import { IndustryModuleCard } from '@/components/stock/IndustryModuleCard'

import { InstitutionalModuleCard } from '@/components/stock/InstitutionalModuleCard'

import { SentimentModuleCard } from '@/components/stock/SentimentModuleCard'

import { TechnicalModuleCard } from '@/components/stock/TechnicalModuleCard'



interface StockDiagnosisPanelProps {

  symbol: string

  data?: StockDiagnosisResponse

  history?: StockDiagnosisHistoryResponse

  loading?: boolean

  historyLoading?: boolean

  error?: string | null

  onDeepAnalysis?: () => void

  onRefresh?: () => void

  onSummaryRefresh?: () => void

  onRetry?: () => void

}



function formatMetric(value: number | null | undefined, suffix = ''): string {

  if (value == null || Number.isNaN(value)) return '—'

  return `${value.toFixed(2)}${suffix}`

}



export function StockDiagnosisPanel({

  symbol,

  data,

  history,

  loading,

  historyLoading,

  error,

  onDeepAnalysis,

  onRefresh,

  onSummaryRefresh,

  onRetry,

}: StockDiagnosisPanelProps) {

  const { t } = useTranslation()

  const [reportsOpen, setReportsOpen] = useState(false)

  const [moduleKey, setModuleKey] = useState<string | null>(null)

  const [summarySubmitting, setSummarySubmitting] = useState(false)



  const moduleLabels = useMemo(() => {

    const labels: Record<string, string> = {}

    for (const module of data?.module_scores ?? []) {

      labels[module.key] = module.label

    }

    return labels

  }, [data?.module_scores])



  const moduleMap = useMemo(

    () => Object.fromEntries((data?.module_scores ?? []).map((module) => [module.key, module])),

    [data?.module_scores],

  )



  const activeModule = moduleKey ? moduleMap[moduleKey] ?? null : null



  if (loading && !data) {

    return (

      <div className="stock-panel card stock-diagnosis stock-diagnosis--loading">

        <Spin tip={t('common.loading')} />

      </div>

    )

  }



  if (!data) {

    if (error) {

      return (

        <div className="stock-panel card stock-diagnosis">

          <Alert

            type="error"

            showIcon

            message={t('common.loadFailed')}

            description={error}

            action={

              onRetry ? (

                <Button size="small" onClick={onRetry}>

                  {t('common.retry')}

                </Button>

              ) : undefined

            }

          />

        </div>

      )

    }

    return (

      <div className="stock-panel card stock-diagnosis">

        <Empty description={t('stock.diagnosis.empty')} />

      </div>

    )

  }



  const metrics = data.key_metrics

  const holdLabel =

    metrics.institutional_hold_source === 'fund'

      ? t('stock.diagnosis.institutionalHoldFund')

      : t('stock.diagnosis.institutionalHold')



  const handleAiSummary = async () => {

    setSummarySubmitting(true)

    try {

      await triggerStockDiagnosisSummary(symbol)

      onSummaryRefresh?.()

    } finally {

      setSummarySubmitting(false)

    }

  }



  const hasSummary =

    Boolean(data.summary?.narrative) || (data.summary?.bullets?.length ?? 0) > 0



  const scrollToModule = useCallback((key: string) => {
    setModuleKey(key)
    document.getElementById(`diagnosis-module-${key}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }, [])

  const openModuleDrawer = useCallback((key: string) => {
    setModuleKey(key)
  }, [])



  return (

    <div className="stock-panel card stock-diagnosis diagnosis-dashboard">

      <DiagnosisHero

        data={data}

        history={history}

        historyLoading={historyLoading}

        loading={loading}

        onDeepAnalysis={onDeepAnalysis}

        onRefresh={onRefresh}

        onOpenReports={() => setReportsOpen(true)}

      />



      <DiagnosisModuleStrip

        modules={data.module_scores}

        activeKey={moduleKey}

        onModuleClick={scrollToModule}

      />



      <div className="diagnosis-dashboard__layout">

        <aside className="diagnosis-dashboard__sidebar">

          <DiagnosisIntro name={data.name} intro={data.intro} />

          <DiagnosisRadarChart

            modules={data.module_scores}

            onModuleClick={openModuleDrawer}

          />

          <div className="stock-diagnosis__metrics">

            <div className="stock-diagnosis__metric">

              <span>{t('stock.valuation.peTtm')}</span>

              <strong>{formatMetric(metrics.pe_ttm)}</strong>

            </div>

            <div className="stock-diagnosis__metric">

              <span>{t('stock.valuation.dvRatio')}</span>

              <strong>{formatMetric(metrics.dv_ttm, '%')}</strong>

            </div>

            <div className="stock-diagnosis__metric">

              <span>{holdLabel}</span>

              <strong>

                {metrics.institutional_hold_pct != null

                  ? `${metrics.institutional_hold_pct.toFixed(2)}%`

                  : '—'}

              </strong>

            </div>

            <div className="stock-diagnosis__metric">

              <span>{t('stock.diagnosis.industryRank')}</span>

              <strong>

                {metrics.industry_rank != null && metrics.industry_total != null

                  ? `${metrics.industry_rank} / ${metrics.industry_total}`

                  : '—'}

              </strong>

            </div>

            {metrics.industry_name ? (

              <Tag className="stock-diagnosis__industry">{metrics.industry_name}</Tag>

            ) : null}

          </div>



          {hasSummary ? (

            <div className="stock-diagnosis__summary diagnosis-dashboard__summary">

              <div className="stock-diagnosis__summary-title">

                {t('stock.diagnosis.aiSummary')}

                {data.summary?.generated_by === 'agent' ? (

                  <Tag color="purple">{t('stock.diagnosis.summaryAgent')}</Tag>

                ) : data.summary?.generated_by === 'rule' ? (

                  <Tag>{t('stock.diagnosis.summaryRule')}</Tag>

                ) : null}

                <Button

                  size="small"

                  loading={summarySubmitting}

                  onClick={() => void handleAiSummary()}

                >

                  {t('stock.diagnosis.generateAiSummary')}

                </Button>

              </div>

              <DiagnosisSummaryBox summary={data.summary} />

            </div>

          ) : (

            <div className="stock-diagnosis__summary diagnosis-dashboard__summary">

              <Button loading={summarySubmitting} onClick={() => void handleAiSummary()}>

                {t('stock.diagnosis.generateAiSummary')}

              </Button>

            </div>

          )}

        </aside>



        <div className="diagnosis-dashboard__grid">

          {moduleMap.technical ? (

            <TechnicalModuleCard

              module={moduleMap.technical}

              onDetail={() => setModuleKey('technical')}

            />

          ) : null}

          {moduleMap.capital_flow ? (

            <CapitalFlowModuleCard

              module={moduleMap.capital_flow}

              onDetail={() => setModuleKey('capital_flow')}

            />

          ) : null}

          {moduleMap.fundamental ? (

            <FundamentalModuleCard

              module={moduleMap.fundamental}

              onDetail={() => setModuleKey('fundamental')}

            />

          ) : null}

          {moduleMap.industry ? (

            <IndustryModuleCard

              module={moduleMap.industry}

              onDetail={() => setModuleKey('industry')}

            />

          ) : null}

          {moduleMap.sentiment ? (

            <SentimentModuleCard

              module={moduleMap.sentiment}

              onDetail={() => setModuleKey('sentiment')}

            />

          ) : null}

          {moduleMap.institutional ? (

            <InstitutionalModuleCard

              module={moduleMap.institutional}

              onDetail={() => setModuleKey('institutional')}

            />

          ) : null}

        </div>

      </div>



      {data.thesis ? (

        <div className="stock-diagnosis__thesis card">

          <div className="stock-diagnosis__thesis-title">

            {t('stock.diagnosis.thesisCard')} · {data.thesis.direction}

          </div>

          <p>{data.thesis.core_assumption}</p>

          <div className="stock-diagnosis__thesis-meta">

            {t('stock.diagnosis.thesisValidUntil')}: {data.thesis.valid_until}

          </div>

        </div>

      ) : null}



      <DiagnosisReportsDrawer

        open={reportsOpen}

        symbol={symbol}

        reportsCount={data.reports_count}

        moduleLabels={moduleLabels}

        onClose={() => setReportsOpen(false)}

      />



      <DiagnosisModuleDrawer

        open={moduleKey != null}

        module={activeModule}

        onClose={() => setModuleKey(null)}

      />

    </div>

  )

}


