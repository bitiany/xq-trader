import { useEffect, useRef } from 'react'
import * as echarts from 'echarts'
import { useTranslation } from 'react-i18next'

import type { DiagnosisModuleScore } from '@/api/stock'

const MODULE_ORDER = [
  'technical',
  'capital_flow',
  'fundamental',
  'sentiment',
  'industry',
  'institutional',
] as const

interface DiagnosisRadarChartProps {
  modules: DiagnosisModuleScore[]
  onModuleClick?: (key: string) => void
}

function formatAxisScore(score: number | null | undefined): string {
  if (score == null || Number.isNaN(score)) return '—'
  return String(Math.round(score))
}

export function DiagnosisRadarChart({ modules, onModuleClick }: DiagnosisRadarChartProps) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const chartRef = useRef<echarts.ECharts | null>(null)
  const { t } = useTranslation()
  const modulesKey = useMemo(() => JSON.stringify(modules.map((item) => ({
    key: item.key,
    score: item.score,
    prev_score: item.prev_score,
    label: item.label,
  }))), [modules])

  useEffect(() => {
    if (!containerRef.current) return
    if (!chartRef.current) {
      chartRef.current = echarts.init(containerRef.current)
    }

    const moduleMap = Object.fromEntries(modules.map((module) => [module.key, module]))
    const indicators = MODULE_ORDER.map((key) => {
      const module = moduleMap[key]
      const label = module?.label ?? t(`stock.diagnosis.modules.${key}`)
      const scoreText = formatAxisScore(module?.score)
      return {
        name: `${label}\n${scoreText}`,
        max: 10,
        key,
      }
    })
    const currentValues = MODULE_ORDER.map((key) => moduleMap[key]?.score ?? 0)
    const prevValues = MODULE_ORDER.map(
      (key) => moduleMap[key]?.prev_score ?? moduleMap[key]?.score ?? 0,
    )
    const hasPrev = modules.some((module) => module.prev_score != null)

    const series: echarts.SeriesOption[] = [
      {
        type: 'radar',
        data: [
          {
            value: currentValues,
            name: t('stock.diagnosis.currentPeriod'),
            areaStyle: { color: 'rgba(59, 130, 246, 0.25)' },
            lineStyle: { color: '#3b82f6', width: 2 },
            itemStyle: { color: '#3b82f6' },
          },
        ],
      },
    ]

    if (hasPrev) {
      series[0] = {
        type: 'radar',
        data: [
          {
            value: currentValues,
            name: t('stock.diagnosis.currentPeriod'),
            areaStyle: { color: 'rgba(59, 130, 246, 0.25)' },
            lineStyle: { color: '#3b82f6', width: 2 },
            itemStyle: { color: '#3b82f6' },
          },
          {
            value: prevValues,
            name: t('stock.diagnosis.prevPeriod'),
            areaStyle: { color: 'transparent' },
            lineStyle: { color: '#94a3b8', width: 1.5, type: 'dashed' },
            itemStyle: { color: '#94a3b8' },
          },
        ],
      }
    }

    chartRef.current.setOption({
      tooltip: { trigger: 'item' },
      legend: hasPrev
        ? {
            bottom: 0,
            textStyle: { color: '#94a3b8', fontSize: 11 },
            data: [t('stock.diagnosis.currentPeriod'), t('stock.diagnosis.prevPeriod')],
          }
        : undefined,
      radar: {
        indicator: indicators,
        center: ['50%', hasPrev ? '45%' : '50%'],
        radius: '62%',
        triggerEvent: Boolean(onModuleClick),
        axisName: {
          color: '#cbd5e1',
          fontSize: 11,
          lineHeight: 16,
        },
        splitLine: { lineStyle: { color: 'rgba(148, 163, 184, 0.2)' } },
        splitArea: { show: false },
        axisLine: { lineStyle: { color: 'rgba(148, 163, 184, 0.3)' } },
      },
      series,
    })

    const chart = chartRef.current
    const handleClick = (params: { targetType?: string; name?: string }) => {
      if (!onModuleClick || params.targetType !== 'axisName' || !params.name) return
      const matched = indicators.find((item) => params.name?.startsWith(item.name.split('\n')[0]))
      if (matched?.key) {
        onModuleClick(matched.key)
      }
    }
    chart.off('click')
    if (onModuleClick) {
      chart.on('click', handleClick)
    }

    const onResize = () => chart.resize()
    window.addEventListener('resize', onResize)
    return () => {
      window.removeEventListener('resize', onResize)
      chart.off('click', handleClick)
    }
  }, [modules, modulesKey, onModuleClick, t])

  useEffect(() => {
    return () => {
      chartRef.current?.dispose()
      chartRef.current = null
    }
  }, [])

  return <div ref={containerRef} className="stock-diagnosis__radar" />
}
