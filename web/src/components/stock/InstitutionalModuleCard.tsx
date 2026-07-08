import { useEffect, useRef } from 'react'
import * as echarts from 'echarts'

import type { DiagnosisModuleScore } from '@/api/stock'
import { DiagnosisModuleCard } from '@/components/stock/DiagnosisModuleCard'

interface InstitutionalModuleCardProps {
  module: DiagnosisModuleScore
  onDetail?: () => void
}

export function InstitutionalModuleCard({ module, onDetail }: InstitutionalModuleCardProps) {
  const chartRef = useRef<HTMLDivElement | null>(null)
  const detail = module.detail ?? {}
  const ratingDist = (detail.rating_dist as Record<string, number> | undefined) ?? {}

  useEffect(() => {
    if (!chartRef.current) return
    const entries = Object.entries(ratingDist)
    if (entries.length === 0) return
    const chart = echarts.init(chartRef.current)
    chart.setOption({
      tooltip: { trigger: 'item' },
      series: [
        {
          type: 'pie',
          radius: ['38%', '62%'],
          center: ['50%', '50%'],
          label: { color: '#cbd5e1', fontSize: 11 },
          data: entries.map(([name, value]) => ({ name, value })),
        },
      ],
    })
    const onResize = () => chart.resize()
    window.addEventListener('resize', onResize)
    return () => {
      window.removeEventListener('resize', onResize)
      chart.dispose()
    }
  }, [ratingDist])

  return (
    <DiagnosisModuleCard module={module} onDetail={onDetail}>
      <div className="diagnosis-module-card__meta">
        <span>研报 {detail.report_count ?? 0}</span>
        <span>
          持股 {detail.hold_pct != null ? `${Number(detail.hold_pct).toFixed(2)}%` : '—'}
          {detail.hold_source === 'fund' ? ' (基金)' : ''}
        </span>
      </div>
      <div ref={chartRef} className="diagnosis-module-card__mini-chart" />
    </DiagnosisModuleCard>
  )
}
