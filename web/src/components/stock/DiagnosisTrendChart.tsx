import { useEffect, useRef } from 'react'
import * as echarts from 'echarts'
import { useTranslation } from 'react-i18next'

import type { StockDiagnosisHistoryItem } from '@/api/stock'

interface DiagnosisTrendChartProps {
  items: StockDiagnosisHistoryItem[]
  compact?: boolean
}

const MODULE_COLORS: Record<string, string> = {
  technical: '#3b82f6',
  capital_flow: '#06b6d4',
  fundamental: '#a855f7',
  sentiment: '#f59e0b',
  industry: '#22c55e',
  institutional: '#ef4444',
}

const MODULE_ORDER = [
  'technical',
  'capital_flow',
  'fundamental',
  'sentiment',
  'industry',
  'institutional',
] as const

export function DiagnosisTrendChart({ items, compact = false }: DiagnosisTrendChartProps) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const chartRef = useRef<echarts.ECharts | null>(null)
  const { t } = useTranslation()

  useEffect(() => {
    if (!containerRef.current || items.length === 0) return
    if (!chartRef.current) {
      chartRef.current = echarts.init(containerRef.current)
    }

    const dates = items.map((item) => item.as_of)
    const overall = items.map((item) => item.overall_score)

    const moduleSeries = MODULE_ORDER.map((key) => ({
      name: t(`stock.diagnosis.modules.${key}`),
      type: 'line' as const,
      smooth: true,
      showSymbol: items.length <= 30,
      lineStyle: { width: 1.5, type: 'dashed' as const },
      data: items.map((item) => item.modules[key] ?? null),
      color: MODULE_COLORS[key],
    }))

    chartRef.current.setOption({
      tooltip: { trigger: 'axis' },
      legend: compact
        ? undefined
        : {
            bottom: 0,
            textStyle: { color: '#94a3b8', fontSize: 11 },
          },
      grid: {
        left: 40,
        right: 16,
        top: compact ? 12 : 24,
        bottom: compact ? 24 : 48,
      },
      xAxis: {
        type: 'category',
        data: dates,
        axisLabel: { color: '#94a3b8', fontSize: 11 },
        axisLine: { lineStyle: { color: 'rgba(148,163,184,0.3)' } },
      },
      yAxis: {
        type: 'value',
        min: 0,
        max: 10,
        splitLine: { lineStyle: { color: 'rgba(148,163,184,0.15)' } },
        axisLabel: { color: '#94a3b8' },
      },
      series: [
        {
          name: t('stock.diagnosis.overallScore'),
          type: 'line',
          smooth: true,
          data: overall,
          lineStyle: { width: compact ? 2 : 3 },
          itemStyle: { color: '#60a5fa' },
          areaStyle: compact ? undefined : { color: 'rgba(96, 165, 250, 0.12)' },
        },
        ...(compact ? [] : moduleSeries),
      ],
    })

    const onResize = () => chartRef.current?.resize()
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [compact, items, t])

  useEffect(() => {
    return () => {
      chartRef.current?.dispose()
      chartRef.current = null
    }
  }, [])

  if (items.length === 0) {
    return null
  }

  return (
    <div
      ref={containerRef}
      className={compact ? 'diagnosis-hero__trend-chart' : 'stock-diagnosis__trend'}
    />
  )
}
