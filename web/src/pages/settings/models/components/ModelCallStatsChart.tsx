import { useEffect, useRef, useCallback, useState } from 'react'
import * as echarts from 'echarts'
import { DatePicker } from 'antd'
import { useTranslation } from 'react-i18next'
import dayjs from 'dayjs'
import { useRequest } from '@/hooks/useRequest'
import { callLogsApi, type CallLogsStats } from '@/api/ai/callLogs'
import { AsyncSection } from '@/components/common/AsyncSection'

const PROVIDER_COLORS: Record<string, string> = {
  openai: '#10a37f',
  anthropic: '#d97706',
  modelscope: '#624aff',
  dashscope: '#ff6a00',
  doubao: '#3370ff',
  deepseek: '#4d6bfe',
  google: '#4285f4',
  azure_openai: '#0078d4',
  ernie: '#e53935',
  zhipu: '#1677ff',
  siliconcloud: '#6366f1',
  ollama: '#64748b',
  lmstudio: '#64748b',
  custom_openai: '#94a3b8',
}

const FALLBACK_COLORS = [
  '#58a6ff', '#3fb950', '#d29922', '#f778ba',
  '#bc8cff', '#79c0ff', '#56d364', '#e3b341',
]

function getProviderColor(code: string, idx: number): string {
  return PROVIDER_COLORS[code] ?? FALLBACK_COLORS[idx % FALLBACK_COLORS.length]
}

interface ProviderSeries {
  seriesKey: string
  providerCode: string
  keyId: number
  legendLabel: string
  color: string
  data: (number | null)[]
  durationData: (number | null)[]
}

function buildSeries(stats: CallLogsStats, _t: (k: string) => string) {
  const modelNames: string[] = []
  const seriesMap = new Map<string, ProviderSeries>()
  let colorIdx = 0

  for (const [model, entries] of Object.entries(stats.models)) {
    const shortName = model.split('/').pop() ?? model
    modelNames.push(shortName)

    for (const entry of entries) {
      const seriesKey = `${entry.provider_code}#${entry.key_id}`
      if (!seriesMap.has(seriesKey)) {
        const color = getProviderColor(entry.provider_code, colorIdx)
        colorIdx++
        seriesMap.set(seriesKey, {
          seriesKey,
          providerCode: entry.provider_code,
          keyId: entry.key_id,
          legendLabel: `${entry.provider_code}#${entry.key_id}`,
          color,
          data: new Array(modelNames.length - 1).fill(null) as (number | null)[],
          durationData: new Array(modelNames.length - 1).fill(null) as (number | null)[],
        })
      }

      const s = seriesMap.get(seriesKey)!
      s.data.push(entry.success_count)
      s.durationData.push(entry.avg_duration_ms)
    }

    for (const s of seriesMap.values()) {
      if (s.data.length < modelNames.length) {
        s.data.push(null)
        s.durationData.push(null)
      }
    }
  }

  const seriesList = Array.from(seriesMap.values())

  return { modelNames, seriesList }
}

function buildChartOption(
  stats: CallLogsStats | null,
  t: (k: string) => string,
) {
  if (!stats || !stats.models) return {}

  const { modelNames, seriesList } = buildSeries(stats, t)
  if (modelNames.length === 0) return {}

  const series = seriesList.map((s) => ({
    name: s.legendLabel,
    type: 'bar' as const,
    data: s.data.map((v, i) => ({
      value: v ?? '-',
      itemStyle: v != null
        ? {
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: s.color },
              { offset: 1, color: s.color + '88' },
            ]),
            borderRadius: [3, 3, 0, 0],
          }
        : { color: 'transparent' },
      avgDuration: s.durationData[i],
    })),
    barMaxWidth: 36,
  }))

  return {
    backgroundColor: 'transparent',
    grid: { left: 60, right: 24, top: 40, bottom: 36 },
    tooltip: {
      trigger: 'axis' as const,
      axisPointer: { type: 'shadow' as const },
      formatter(params: unknown) {
        const items = Array.isArray(params) ? params : [params]
        const lines = items
          .filter((p: { value?: unknown }) => p.value !== '-' && p.value != null)
          .map((p: { seriesName?: string; value?: unknown; data?: { avgDuration?: number | null } }) => {
            const calls = p.value
            const dur = p.data?.avgDuration
            const durText = dur != null ? ` | ${t('settings.models.callStats.avgDuration')}: ${dur}ms` : ''
            return `${p.seriesName ?? ''}: ${t('settings.models.callStats.calls')} ${calls}${durText}`
          })
        return lines.length > 0 ? lines.join('<br/>') : ''
      },
    },
    legend: {
      data: seriesList.map((s) => s.legendLabel),
      textStyle: { color: '#8b949e', fontSize: 10 },
      top: 4,
      type: 'scroll' as const,
    },
    xAxis: {
      type: 'category' as const,
      data: modelNames,
      axisLine: { lineStyle: { color: '#30363d' } },
      axisLabel: { color: '#8b949e', fontSize: 10, rotate: modelNames.length > 6 ? 25 : 0 },
    },
    yAxis: [
      {
        type: 'value' as const,
        name: t('settings.models.callStats.calls'),
        axisLine: { show: false },
        splitLine: { lineStyle: { color: '#21262d' } },
        axisLabel: { color: '#8b949e', fontSize: 10 },
      },
    ],
    series,
  }
}

export function ModelCallStatsChart({ height = 280 }: { height?: number }) {
  const { t } = useTranslation()
  const containerRef = useRef<HTMLDivElement | null>(null)
  const chartRef = useRef<echarts.ECharts | null>(null)

  const [selectedDate, setSelectedDate] = useState<dayjs.Dayjs | null>(dayjs())

  const fetcher = useCallback(() => {
    const dateStr = selectedDate?.format('YYYY-MM-DD')
    return callLogsApi.stats(dateStr ? { date: dateStr } : undefined)
  }, [selectedDate])

  const { data, loading, error, reload } = useRequest(fetcher)

  useEffect(() => {
    void reload()
  }, [reload])

  const updateChart = useCallback(() => {
    const container = containerRef.current
    if (!container) return

    if (!chartRef.current) {
      chartRef.current = echarts.init(container)
    }

    const option = buildChartOption(data ?? null, t)
    if (Object.keys(option).length > 0) {
      chartRef.current.setOption(option, true)
    }
  }, [data, t])

  useEffect(() => {
    updateChart()
  }, [updateChart])

  useEffect(() => {
    const onResize = () => chartRef.current?.resize()
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])

  useEffect(() => {
    return () => {
      chartRef.current?.dispose()
      chartRef.current = null
    }
  }, [])

  return (
    <AsyncSection loading={loading} error={error} onRetry={() => void reload()} minHeight={height}>
      <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 8 }}>
        <DatePicker
          size="small"
          value={selectedDate}
          onChange={(d) => setSelectedDate(d)}
          allowClear
          placeholder={t('settings.models.callStats.selectDate')}
        />
      </div>
      <div ref={containerRef} style={{ width: '100%', height }} />
    </AsyncSection>
  )
}
