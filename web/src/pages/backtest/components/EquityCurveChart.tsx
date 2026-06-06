import { useEffect, useRef } from 'react'
import { TrendingUp } from 'lucide-react'
import * as echarts from 'echarts'
import type { BacktestEquityItem } from '@/api/backtest'

export interface EquityCurveChartProps {
  data: BacktestEquityItem[]
}

export function EquityCurveChart({ data }: EquityCurveChartProps) {
  const chartRef = useRef<HTMLDivElement>(null)
  const chartInstance = useRef<ReturnType<typeof echarts.init> | null>(null)

  useEffect(() => {
    if (!chartRef.current || data.length === 0) return
    const chart = echarts.init(chartRef.current, 'dark')
    chartInstance.current = chart

    const dates = data.map((d) => d.trade_date)
    const netValues = data.map((d) => d.net_value)
    const returns = data.map((d) => (d.cumulative_return ?? 0) * 100)

    chart.setOption({
      backgroundColor: 'transparent',
      tooltip: { trigger: 'axis' },
      legend: {
        data: ['净值', '累计收益率(%)'],
        top: 0,
        textStyle: { color: '#94a3b8', fontSize: 11 },
      },
      grid: { left: 50, right: 50, top: 30, bottom: 24 },
      xAxis: {
        type: 'category',
        data: dates,
        axisLabel: { fontSize: 10, color: '#94a3b8' },
        axisLine: { lineStyle: { color: '#2a3340' } },
      },
      yAxis: [
        {
          type: 'value',
          name: '净值',
          axisLabel: { fontSize: 10, color: '#94a3b8' },
          splitLine: { lineStyle: { color: '#2a3340' } },
        },
        {
          type: 'value',
          name: '收益率(%)',
          axisLabel: { fontSize: 10, color: '#94a3b8' },
          splitLine: { show: false },
        },
      ],
      series: [
        {
          name: '净值',
          type: 'line',
          data: netValues,
          smooth: true,
          lineStyle: { color: '#38bdf8', width: 2 },
          itemStyle: { color: '#38bdf8' },
          areaStyle: {
            color: {
              type: 'linear',
              x: 0, y: 0, x2: 0, y2: 1,
              colorStops: [
                { offset: 0, color: 'rgba(56,189,248,0.25)' },
                { offset: 1, color: 'rgba(56,189,248,0.02)' },
              ],
            },
          },
        },
        {
          name: '累计收益率(%)',
          type: 'line',
          yAxisIndex: 1,
          data: returns,
          smooth: true,
          lineStyle: { color: '#a78bfa', width: 1.5, type: 'dashed' },
          itemStyle: { color: '#a78bfa' },
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
        <TrendingUp size={32} style={{ color: 'var(--text-muted)' }} />
        <span>暂无净值数据</span>
      </div>
    )
  }

  return <div ref={chartRef} style={{ width: '100%', height: '100%' }} />
}
