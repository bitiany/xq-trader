import { useEffect, useMemo, useRef } from 'react'
import { BarChart3 } from 'lucide-react'
import * as echarts from 'echarts'
import { type KlineBarItem, type ChanlunResponse } from '@/api/stock'
import { computeMA, computeMACD } from '../utils'

interface BuyPoint {
  date: string
  price: number
  low: number
}

interface SellPoint {
  date: string
  price: number
  high: number
}

export interface KLineChartProps {
  bars: KlineBarItem[]
  buyPoints: BuyPoint[]
  sellPoints: SellPoint[]
  startDate: string
  endDate: string
  chanlun?: ChanlunResponse
}

export function KLineChart({
  bars,
  buyPoints,
  sellPoints,
  startDate,
  endDate,
  chanlun,
}: KLineChartProps) {
  const chartRef = useRef<HTMLDivElement>(null)
  const chartInstance = useRef<ReturnType<typeof echarts.init> | null>(null)

  const filteredBars = useMemo(() => {
    if (!startDate && !endDate) return bars
    return bars.filter((b) => {
      if (startDate && b.trade_date < startDate) return false
      if (endDate && b.trade_date > endDate) return false
      return true
    })
  }, [bars, startDate, endDate])

  useEffect(() => {
    if (!chartRef.current || filteredBars.length === 0) return
    const chart = echarts.init(chartRef.current, 'dark')
    chartInstance.current = chart

    const dates = filteredBars.map((b) => b.trade_date)
    const ohlc = filteredBars.map((b) => [b.open, b.close, b.low, b.high])
    const volumes = filteredBars.map((b) => b.volume)
    const closes = filteredBars.map((b) => b.close)

    const ma5 = computeMA(closes, 5)
    const ma10 = computeMA(closes, 10)
    const ma20 = computeMA(closes, 20)
    const { dif, dea, macdBar } = computeMACD(closes)

    const dateIndexMap = new Map<string, number>()
    dates.forEach((d, i) => dateIndexMap.set(d, i))

    const buyMarkData = buyPoints
      .filter((p) => dateIndexMap.has(p.date))
      .map((p) => ({
        coord: [dateIndexMap.get(p.date)!, p.low * 0.97] as [number, number],
        value: p.price.toFixed(2),
        symbol: 'triangle' as const,
        symbolSize: 16,
        itemStyle: { color: '#e03e3e' },
        label: {
          show: true,
          formatter: (params: { value: string }) => params.value,
          position: 'bottom' as const,
          fontSize: 11,
          fontWeight: 'bold',
          color: '#e03e3e',
          distance: 6,
          backgroundColor: 'rgba(15,18,24,0.7)',
          padding: [2, 4],
          borderRadius: 2,
        },
      }))

    const sellMarkData = sellPoints
      .filter((p) => dateIndexMap.has(p.date))
      .map((p) => ({
        coord: [dateIndexMap.get(p.date)!, p.high * 1.03] as [number, number],
        value: p.price.toFixed(2),
        symbol: 'triangle' as const,
        symbolSize: 16,
        symbolRotate: 180,
        itemStyle: { color: '#2eaa67' },
        label: {
          show: true,
          formatter: (params: { value: string }) => params.value,
          position: 'top' as const,
          fontSize: 11,
          fontWeight: 'bold',
          color: '#2eaa67',
          distance: 6,
          backgroundColor: 'rgba(15,18,24,0.7)',
          padding: [2, 4],
          borderRadius: 2,
        },
      }))

    const buyMarkLines = buyPoints
      .filter((p) => dateIndexMap.has(p.date))
      .map((p) => ({
        xAxis: dateIndexMap.get(p.date)!,
        label: { show: false },
        lineStyle: { color: '#e03e3e', type: 'dashed' as const, width: 1, opacity: 0.6 },
      }))

    const sellMarkLines = sellPoints
      .filter((p) => dateIndexMap.has(p.date))
      .map((p) => ({
        xAxis: dateIndexMap.get(p.date)!,
        label: { show: false },
        lineStyle: { color: '#2eaa67', type: 'dashed' as const, width: 1, opacity: 0.6 },
      }))

    const macdBarData = macdBar.map((v) => ({
      value: v,
      itemStyle: { color: (v ?? 0) >= 0 ? '#e03e3e' : '#2eaa67' },
    }))

    const chanlunSeries: echarts.SeriesOption[] = []
    if (chanlun) {
      if (chanlun.pivots && chanlun.pivots.length > 0) {
        const pivotAreas: { xAxis: number; yAxis: number }[][] = []
        for (const p of chanlun.pivots) {
          const si = dateIndexMap.get(p.start_date)
          const ei = dateIndexMap.get(p.end_date)
          if (si != null && ei != null) {
            pivotAreas.push([
              { xAxis: si, yAxis: p.zd },
              { xAxis: ei, yAxis: p.zg },
            ])
          }
        }
        if (pivotAreas.length > 0) {
          chanlunSeries.push({
            name: '中枢',
            type: 'line',
            xAxisIndex: 0,
            yAxisIndex: 0,
            data: [],
            markArea: {
              silent: true,
              itemStyle: {
                color: 'rgba(250, 204, 21, 0.10)',
                borderColor: 'rgba(250, 204, 21, 0.35)',
                borderWidth: 1,
              },
              data: pivotAreas,
            },
            z: 1,
          } as echarts.SeriesOption)
        }
      }
      if (chanlun.strokes && chanlun.strokes.length > 0) {
        const strokeLines: { xAxis: string | number; yAxis: number }[][] = []
        for (const s of chanlun.strokes) {
          const si = dateIndexMap.get(s.start_date)
          const ei = dateIndexMap.get(s.end_date)
          if (si != null && ei != null) {
            strokeLines.push([
              { xAxis: si, yAxis: s.start_price },
              { xAxis: ei, yAxis: s.end_price },
            ])
          }
        }
        if (strokeLines.length > 0) {
          chanlunSeries.push({
            name: '笔',
            type: 'line',
            xAxisIndex: 0,
            yAxisIndex: 0,
            data: [],
            showSymbol: false,
            markLine: {
              silent: true,
              symbol: 'none',
              lineStyle: { width: 1.5, color: '#facc15', type: 'solid' },
              data: strokeLines,
            },
            z: 5,
          } as echarts.SeriesOption)
        }
      }
    }

    chart.setOption({
      backgroundColor: 'transparent',
      animation: false,
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'cross' },
        backgroundColor: 'rgba(15,18,24,0.92)',
        borderColor: '#2a3340',
        textStyle: { color: '#eef2f8', fontSize: 12 },
      },
      legend: {
        data: ['K线', 'MA5', 'MA10', 'MA20', 'DIF', 'DEA', 'MACD', ...(chanlunSeries.length > 0 ? ['中枢', '笔'] : [])],
        top: 0,
        textStyle: { color: '#94a3b8', fontSize: 11 },
      },
      grid: [
        { left: 60, right: 20, top: 30, height: '38%' },
        { left: 60, right: 20, top: '52%', height: '10%' },
        { left: 60, right: 20, top: '66%', height: '18%' },
      ],
      xAxis: [
        {
          type: 'category',
          data: dates,
          gridIndex: 0,
          axisLabel: { show: false },
          axisLine: { lineStyle: { color: '#2a3340' } },
          axisTick: { show: false },
        },
        {
          type: 'category',
          data: dates,
          gridIndex: 1,
          axisLabel: { show: false },
          axisLine: { lineStyle: { color: '#2a3340' } },
          axisTick: { show: false },
        },
        {
          type: 'category',
          data: dates,
          gridIndex: 2,
          axisLabel: { fontSize: 10, color: '#94a3b8' },
          axisLine: { lineStyle: { color: '#2a3340' } },
        },
      ],
      yAxis: [
        {
          type: 'value',
          gridIndex: 0,
          scale: true,
          axisLabel: { fontSize: 10, color: '#94a3b8' },
          splitLine: { lineStyle: { color: '#2a3340' } },
        },
        {
          type: 'value',
          gridIndex: 1,
          scale: true,
          axisLabel: { show: false },
          splitLine: { show: false },
        },
        {
          type: 'value',
          gridIndex: 2,
          scale: true,
          axisLabel: { fontSize: 10, color: '#94a3b8' },
          splitLine: { lineStyle: { color: '#2a3340', opacity: 0.3 } },
        },
      ],
      dataZoom: [
        { type: 'inside', xAxisIndex: [0, 1, 2], start: 0, end: 100 },
        { type: 'slider', xAxisIndex: [0, 1, 2], bottom: 4, height: 20, borderColor: '#2a3340', fillerColor: 'rgba(22,119,255,0.15)', handleStyle: { color: '#1677ff' } },
      ],
      series: [
        {
          name: 'K线',
          type: 'candlestick',
          xAxisIndex: 0,
          yAxisIndex: 0,
          data: ohlc,
          itemStyle: {
            color: '#e03e3e',
            color0: '#2eaa67',
            borderColor: '#e03e3e',
            borderColor0: '#2eaa67',
          },
          markPoint: {
            data: [...buyMarkData, ...sellMarkData],
          },
          markLine: {
            symbol: 'none',
            data: [...buyMarkLines, ...sellMarkLines],
          },
        },
        {
          name: 'MA5',
          type: 'line',
          xAxisIndex: 0,
          yAxisIndex: 0,
          data: ma5,
          smooth: true,
          showSymbol: false,
          lineStyle: { width: 1, color: '#f59e0b' },
        },
        {
          name: 'MA10',
          type: 'line',
          xAxisIndex: 0,
          yAxisIndex: 0,
          data: ma10,
          smooth: true,
          showSymbol: false,
          lineStyle: { width: 1, color: '#38bdf8' },
        },
        {
          name: 'MA20',
          type: 'line',
          xAxisIndex: 0,
          yAxisIndex: 0,
          data: ma20,
          smooth: true,
          showSymbol: false,
          lineStyle: { width: 1, color: '#a78bfa' },
        },
        {
          name: '成交量',
          type: 'bar',
          xAxisIndex: 1,
          yAxisIndex: 1,
          data: volumes,
          itemStyle: {
            color: (params: { dataIndex: number }) => {
              const bar = filteredBars[params.dataIndex]
              return bar && bar.close >= bar.open ? '#e03e3e' : '#2eaa67'
            },
          },
          markLine: {
            symbol: 'none',
            data: [...buyMarkLines, ...sellMarkLines],
          },
        },
        {
          name: 'DIF',
          type: 'line',
          xAxisIndex: 2,
          yAxisIndex: 2,
          data: dif,
          smooth: true,
          showSymbol: false,
          lineStyle: { width: 1.5, color: '#f59e0b' },
          markLine: {
            symbol: 'none',
            data: [...buyMarkLines, ...sellMarkLines],
          },
        },
        {
          name: 'DEA',
          type: 'line',
          xAxisIndex: 2,
          yAxisIndex: 2,
          data: dea,
          smooth: true,
          showSymbol: false,
          lineStyle: { width: 1.5, color: '#38bdf8' },
        },
        {
          name: 'MACD',
          type: 'bar',
          xAxisIndex: 2,
          yAxisIndex: 2,
          data: macdBarData,
        },
        ...chanlunSeries,
      ],
    })

    const handleResize = () => chart.resize()
    window.addEventListener('resize', handleResize)
    return () => {
      window.removeEventListener('resize', handleResize)
      chart.dispose()
    }
  }, [filteredBars, buyPoints, sellPoints, chanlun])

  if (filteredBars.length === 0) {
    return (
      <div className="backtest-page__chart-empty">
        <BarChart3 size={32} style={{ color: 'var(--text-muted)' }} />
        <span>暂无K线数据</span>
      </div>
    )
  }

  return <div ref={chartRef} style={{ width: '100%', height: '100%', minHeight: 560 }} />
}
