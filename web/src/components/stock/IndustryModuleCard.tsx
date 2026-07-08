import { useEffect, useRef } from 'react'
import * as echarts from 'echarts'

import type { DiagnosisModuleScore } from '@/api/stock'
import { DiagnosisModuleCard } from '@/components/stock/DiagnosisModuleCard'

interface IndustryModuleCardProps {
  module: DiagnosisModuleScore
  onDetail?: () => void
}

export function IndustryModuleCard({ module, onDetail }: IndustryModuleCardProps) {
  const chartRef = useRef<HTMLDivElement | null>(null)
  const detail = module.detail ?? {}
  const pePercentile = detail.pe_percentile != null ? Number(detail.pe_percentile) : null
  const rank = detail.industry_rank != null ? Number(detail.industry_rank) : null
  const total = detail.industry_total != null ? Number(detail.industry_total) : null

  useEffect(() => {
    if (!chartRef.current || pePercentile == null) return
    const chart = echarts.init(chartRef.current)
    chart.setOption({
      series: [
        {
          type: 'gauge',
          min: 0,
          max: 100,
          startAngle: 200,
          endAngle: -20,
          progress: { show: true, width: 10 },
          axisLine: { lineStyle: { width: 10, color: [[1, 'rgba(148,163,184,0.25)']] } },
          axisTick: { show: false },
          splitLine: { show: false },
          axisLabel: { show: false },
          pointer: { show: false },
          detail: {
            valueAnimation: true,
            formatter: '{value}%',
            color: '#e2e8f0',
            fontSize: 18,
            offsetCenter: [0, '10%'],
          },
          data: [{ value: Math.round(pePercentile) }],
        },
      ],
    })
    const onResize = () => chart.resize()
    window.addEventListener('resize', onResize)
    return () => {
      window.removeEventListener('resize', onResize)
      chart.dispose()
    }
  }, [pePercentile])

  const rankPct = rank != null && total ? Math.round((1 - (rank - 1) / total) * 100) : null

  return (
    <DiagnosisModuleCard module={module} onDetail={onDetail}>
      <div ref={chartRef} className="diagnosis-module-card__mini-chart diagnosis-module-card__mini-chart--gauge" />
      <p className="diagnosis-module-card__hint">
        {String(detail.valuation_label ?? '估值分位')}
        {detail.pe_ttm != null ? ` · PE ${Number(detail.pe_ttm).toFixed(2)}` : ''}
      </p>
      {rank != null && total != null ? (
        <div className="diagnosis-industry-bar">
          <div className="diagnosis-industry-bar__track">
            <div
              className="diagnosis-industry-bar__fill"
              style={{ width: `${rankPct ?? 0}%` }}
            />
          </div>
          <span className="diagnosis-industry-bar__label">
            行业排名 {rank} / {total}
          </span>
        </div>
      ) : null}
    </DiagnosisModuleCard>
  )
}
