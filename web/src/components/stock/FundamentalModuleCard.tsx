import { useEffect, useMemo, useRef } from 'react'
import * as echarts from 'echarts'
import { useTranslation } from 'react-i18next'

import type { DiagnosisModuleScore } from '@/api/stock'
import { DiagnosisModuleCard } from '@/components/stock/DiagnosisModuleCard'

const RING_KEYS = ['profit', 'operation', 'solvency', 'growth', 'cashflow'] as const

interface FundamentalModuleCardProps {
  module: DiagnosisModuleScore
  onDetail?: () => void
}

export function FundamentalModuleCard({ module, onDetail }: FundamentalModuleCardProps) {
  const { t } = useTranslation()
  const chartRef = useRef<HTMLDivElement | null>(null)
  const rings = useMemo(
    () => (module.detail?.rings as Record<string, number | null> | undefined) ?? {},
    [module.detail?.rings],
  )
  const highlights = useMemo(
    () => (module.detail?.highlights as Record<string, number | null> | undefined) ?? {},
    [module.detail?.highlights],
  )
  const ringsKey = useMemo(() => JSON.stringify(rings), [rings])

  useEffect(() => {
    if (!chartRef.current) return
    const chart = echarts.init(chartRef.current)
    const values = RING_KEYS.map((key) => rings[key] ?? 0)
    chart.setOption({
      radar: {
        indicator: RING_KEYS.map((key) => ({
          name: t(`stock.diagnosis.fundamental.rings.${key}`),
          max: 10,
        })),
        radius: '58%',
        center: ['50%', '52%'],
        axisName: { color: '#cbd5e1', fontSize: 11 },
        splitLine: { lineStyle: { color: 'rgba(148,163,184,0.2)' } },
        splitArea: { show: false },
      },
      series: [
        {
          type: 'radar',
          data: [
            {
              value: values,
              areaStyle: { color: 'rgba(168,85,247,0.2)' },
              lineStyle: { color: '#a855f7' },
            },
          ],
        },
      ],
    })
    const onResize = () => chart.resize()
    window.addEventListener('resize', onResize)
    return () => {
      window.removeEventListener('resize', onResize)
      chart.dispose()
    }
  }, [rings, ringsKey, t])

  return (
    <DiagnosisModuleCard module={module} onDetail={onDetail}>
      <div ref={chartRef} className="diagnosis-module-card__mini-chart diagnosis-module-card__mini-chart--ring" />
      <div className="diagnosis-module-card__meta diagnosis-module-card__meta--rings">
        {RING_KEYS.map((key) => (
          <span key={key}>
            {t(`stock.diagnosis.fundamental.rings.${key}`)}{' '}
            {rings[key] != null ? rings[key]!.toFixed(1) : '—'}
          </span>
        ))}
      </div>
      <div className="diagnosis-module-card__meta">
        <span>
          {t('stock.financials.roe')}{' '}
          {highlights.roe != null ? `${Number(highlights.roe).toFixed(2)}%` : '—'}
        </span>
        <span>
          {t('stock.financials.debtRatio')}{' '}
          {highlights.debt_to_assets != null ? `${Number(highlights.debt_to_assets).toFixed(2)}%` : '—'}
        </span>
      </div>
    </DiagnosisModuleCard>
  )
}
