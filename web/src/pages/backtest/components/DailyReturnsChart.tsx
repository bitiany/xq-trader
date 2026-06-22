import { useEffect, useRef } from 'react'
import { BarChart3 } from 'lucide-react'
import * as echarts from 'echarts'

export interface DailyReturnsChartProps {
  data: { date: string; value: number }[]
}

export function DailyReturnsChart({ data }: DailyReturnsChartProps) {
  const chartRef = useRef<HTMLDivElement>(null)
  const chartInstance = useRef<ReturnType<typeof echarts.init> | null>(null)

  useEffect(() => {
    if (!chartRef.current || data.length === 0) return
    const chart = echarts.init(chartRef.current, 'dark')
    chartInstance.current = chart

    const dates = data.map((d) => d.date)
    const values = data.map((d) => d.value)

    chart.setOption({
      backgroundColor: 'transparent',
      tooltip: {
        trigger: 'axis',
        formatter: (params: unknown) => {
          const p = Array.isArray(params) ? params[0] : params
          const d = (p as { name?: string; value?: number }).name ?? ''
          const v = (p as { name?: string; value?: number }).value
          if (v == null) return d
          const pct = (v * 100).toFixed(2)
          return `${d}<br/>日收益率: ${pct}%`
        },
      },
      grid: { left: 50, right: 20, top: 10, bottom: 24 },
      xAxis: {
        type: 'category',
        data: dates,
        axisLabel: { fontSize: 10, color: '#94a3b8' },
        axisLine: { lineStyle: { color: '#2a3340' } },
      },
      yAxis: {
        type: 'value',
        axisLabel: {
          fontSize: 10,
          color: '#94a3b8',
          formatter: (v: number) => `${(v * 100).toFixed(1)}%`,
        },
        splitLine: { lineStyle: { color: '#2a3340' } },
      },
      series: [
        {
          type: 'bar',
          data: values.map((v) => ({
            value: v,
            itemStyle: {
              color: v >= 0 ? '#ef4444' : '#22c55e',
            },
          })),
          barMaxWidth: 4,
        },
      ],
    })

    const handleResize = () => chart.resize()
    window.addEventListener('resize', handleResize)
    return () => {
      window.removeEventListener('resize', handleResize)
      chart.dispose()
    }
  }, [data])

  if (data.length === 0) {
    return (
      <div className="backtest-page__chart-empty">
        <BarChart3 size={32} style={{ color: 'var(--text-muted)' }} />
        <span>暂无收益率数据</span>
      </div>
    )
  }
  return <div ref={chartRef} style={{ width: '100%', height: '100%' }} />
}
