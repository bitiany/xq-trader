import { useEffect, useMemo, useRef } from 'react'
import * as echarts from 'echarts'
import { useTranslation } from 'react-i18next'

import type { DiagnosisModuleScore } from '@/api/stock'
import { DiagnosisModuleCard } from '@/components/stock/DiagnosisModuleCard'
import { translateDiagnosisTerm } from '@/utils/diagnosisTechnical'

interface FlowSeriesItem {
  trade_date?: string
  main_net_pct?: number | null
}

interface CapitalFlowModuleCardProps {
  module: DiagnosisModuleScore
  onDetail?: () => void
}

export function CapitalFlowModuleCard({ module, onDetail }: CapitalFlowModuleCardProps) {
  const { t } = useTranslation()
  const chartRef = useRef<HTMLDivElement | null>(null)
  const detail = module.detail ?? {}
  const flowSeries = (detail.flow_series as FlowSeriesItem[] | undefined) ?? []

  const chartItems = useMemo(
    () =>
      flowSeries.map((item) => ({
        trade_date: item.trade_date ?? '',
        main_net_pct: item.main_net_pct ?? null,
      })),
    [flowSeries],
  )

  useEffect(() => {
    if (!chartRef.current || !chartItems.length) return
    const chart = echarts.init(chartRef.current)
    chart.setOption({
      grid: { left: 36, right: 8, top: 12, bottom: 24 },
      tooltip: { trigger: 'axis' },
      xAxis: {
        type: 'category',
        data: chartItems.map((item) => item.trade_date.slice(5)),
        axisLabel: { color: '#94a3b8', fontSize: 10 },
      },
      yAxis: {
        type: 'value',
        axisLabel: { color: '#94a3b8', fontSize: 10 },
        splitLine: { lineStyle: { color: 'rgba(148,163,184,0.15)' } },
      },
      series: [
        {
          type: 'line',
          smooth: true,
          data: chartItems.map((item) => item.main_net_pct),
          lineStyle: { color: '#06b6d4', width: 2 },
          areaStyle: { color: 'rgba(6,182,212,0.12)' },
        },
      ],
    })
    const onResize = () => chart.resize()
    window.addEventListener('resize', onResize)
    return () => {
      window.removeEventListener('resize', onResize)
      chart.dispose()
    }
  }, [chartItems])

  return (
    <DiagnosisModuleCard module={module} onDetail={onDetail}>
      <div className="diagnosis-module-card__meta">
        <span>
          {t('stock.diagnosis.capitalFlow.net5d')}{' '}
          {detail.net_5d != null ? `${Number(detail.net_5d).toFixed(2)}%` : '—'}
        </span>
        <span>
          {t('stock.diagnosis.capitalFlow.net10d')}{' '}
          {detail.net_10d != null ? `${Number(detail.net_10d).toFixed(2)}%` : '—'}
        </span>
        <span>
          {t('stock.diagnosis.capitalFlow.net20d')}{' '}
          {detail.net_20d != null ? `${Number(detail.net_20d).toFixed(2)}%` : '—'}
        </span>
      </div>
      <p className="diagnosis-module-card__hint">
        {t('stock.diagnosis.capitalFlow.trend')} {translateDiagnosisTerm(detail.flow_trend as string, t)}
      </p>
      <div ref={chartRef} className="diagnosis-module-card__mini-chart" />
    </DiagnosisModuleCard>
  )
}
