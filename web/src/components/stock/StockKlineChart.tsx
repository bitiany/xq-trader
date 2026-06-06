import { useEffect, useMemo, useRef } from 'react'
import * as echarts from 'echarts'
import { useTranslation } from 'react-i18next'

import type { ChanlunPivot, ChanlunResponse, ChanlunStroke, IndicatorKind, KlineBarItem } from '@/api/stock'
import { resolveMaOverlays } from '@/utils/klineIndicators'

interface StockKlineChartProps {
  bars: KlineBarItem[]
  indicator: IndicatorKind
  overlays: Record<string, Array<number | null>>
  maOverlays?: Record<string, Array<number | null>>
  chanlun?: ChanlunResponse
  loading?: boolean
}

const VISIBLE_WINDOW = 120
const MA_COLORS = ['#f5a623', '#6ea8fe', '#b37feb', '#ff7875']
const LINE_COLORS = ['#f5a623', '#6ea8fe', '#b37feb', '#ff7875']

function formatDateLabel(value: string): string {
  return value.slice(5)
}

function formatVolumeLabel(value: number): string {
  if (value >= 1e8) return `${(value / 1e8).toFixed(1)}亿`
  if (value >= 1e4) return `${(value / 1e4).toFixed(0)}万`
  return value.toFixed(0)
}

function calcInitialZoom(barCount: number): { start: number; end: number } {
  if (barCount <= VISIBLE_WINDOW) {
    return { start: 0, end: 100 }
  }
  return { start: ((barCount - VISIBLE_WINDOW) / barCount) * 100, end: 100 }
}

function buildStrokeSeries(
  bars: KlineBarItem[],
  strokes: ChanlunStroke[],
): echarts.SeriesOption {
  const dateMap = new Map<string, number>()
  bars.forEach((b, i) => dateMap.set(b.trade_date, i))

  const markLineData: { xAxis: string | number; yAxis: number }[][] = []
  for (const s of strokes) {
    const si = dateMap.get(s.start_date)
    const ei = dateMap.get(s.end_date)
    if (si == null || ei == null) continue
    markLineData.push([
      { xAxis: si, yAxis: s.start_price },
      { xAxis: ei, yAxis: s.end_price },
    ])
  }

  return {
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
      data: markLineData,
    },
    z: 5,
  } as echarts.SeriesOption
}

function buildPivotMarkAreas(
  bars: KlineBarItem[],
  pivots: ChanlunPivot[],
): echarts.SeriesOption {
  const dateMap = new Map<string, number>()
  bars.forEach((b, i) => dateMap.set(b.trade_date, i))

  const areas: { xAxis: number; yAxis: number }[][] = []
  for (const p of pivots) {
    const si = dateMap.get(p.start_date)
    const ei = dateMap.get(p.end_date)
    if (si != null && ei != null) {
      areas.push([
        { xAxis: si, yAxis: p.zd },
        { xAxis: ei, yAxis: p.zg },
      ])
    }
  }

  return {
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
      data: areas,
    },
    z: 1,
  } as echarts.SeriesOption
}

export function StockKlineChart({
  bars,
  indicator,
  overlays,
  maOverlays = {},
  chanlun,
  loading = false,
}: StockKlineChartProps) {
  const { t } = useTranslation()
  const containerRef = useRef<HTMLDivElement | null>(null)
  const chartRef = useRef<echarts.ECharts | null>(null)
  const hasBars = bars.length > 0
  const initialZoom = useMemo(() => calcInitialZoom(bars.length), [bars.length])

  const chartOverlays = overlays
  const mainMa = useMemo(
    () => (indicator === 'ma' ? chartOverlays : resolveMaOverlays(bars, maOverlays)),
    [bars, chartOverlays, indicator, maOverlays],
  )

  const strokeSeries = useMemo(
    () => (chanlun && chanlun.strokes.length > 0 ? buildStrokeSeries(bars, chanlun.strokes) : null),
    [bars, chanlun],
  )
  const pivotSeries = useMemo(
    () => (chanlun && chanlun.pivots.length > 0 ? buildPivotMarkAreas(bars, chanlun.pivots) : null),
    [bars, chanlun],
  )

  const option = useMemo(() => {
    if (!hasBars) {
      return null
    }

    const dates = bars.map((b) => b.trade_date)
    const ohlc = bars.map((b) => [b.open, b.close, b.low, b.high])
    const volumes = bars.map((b) => b.volume)
    const volColors = bars.map((b) => (b.close >= b.open ? '#ef5350' : '#26a69a'))

    const hasSub = indicator !== 'ma'
    const grids = hasSub
      ? [
        { left: 56, right: 48, top: 36, height: '50%' },
        { left: 56, right: 48, top: '66%', height: '12%' },
        { left: 56, right: 48, top: '80%', height: '14%' },
      ]
      : [
        { left: 56, right: 48, top: 36, height: '58%' },
        { left: 56, right: 48, top: '74%', height: '16%' },
      ]

    const xAxis = grids.map((_, i) => ({
      type: 'category' as const,
      data: dates,
      gridIndex: i,
      boundaryGap: i > 0,
      axisLine: { lineStyle: { color: '#4b5563' } },
      axisLabel: {
        show: i === grids.length - 1,
        color: '#9ca3af',
        fontSize: 11,
        formatter: (v: string) => formatDateLabel(v),
      },
    }))

    const yAxis = grids.map((_, i) => {
      const isVolAxis = i === 1
      return {
        scale: true,
        gridIndex: i,
        splitLine: { lineStyle: { color: 'rgba(148,163,184,0.12)' } },
        axisLabel: {
          color: '#9ca3af',
          fontSize: 11,
          show: i === 0 || isVolAxis,
          formatter: isVolAxis ? (v: number) => formatVolumeLabel(v) : undefined,
        },
        splitNumber: isVolAxis ? 2 : undefined,
        min: isVolAxis ? 0 : undefined,
      }
    })

    const series: echarts.SeriesOption[] = [
      {
        name: t('stock.chart.candle'),
        type: 'candlestick',
        data: ohlc,
        xAxisIndex: 0,
        yAxisIndex: 0,
        large: true,
        largeThreshold: 600,
        itemStyle: {
          color: '#ef5350',
          color0: '#26a69a',
          borderColor: '#ef5350',
          borderColor0: '#26a69a',
        },
      },
    ]

    Object.entries(mainMa).forEach(([key, data], idx) => {
      series.push({
        name: key.toUpperCase(),
        type: 'line',
        data,
        xAxisIndex: 0,
        yAxisIndex: 0,
        showSymbol: false,
        lineStyle: { width: 1.2, color: MA_COLORS[idx % MA_COLORS.length] },
        sampling: 'lttb',
      })
    })

    if (pivotSeries) {
      series.push(pivotSeries)
    }

    if (strokeSeries) {
      series.push(strokeSeries)
    }

    series.push({
      name: t('stock.chart.volume'),
      type: 'bar',
      data: volumes,
      xAxisIndex: 1,
      yAxisIndex: 1,
      large: true,
      largeThreshold: 600,
      itemStyle: {
        color: (p: { dataIndex: number }) => volColors[p.dataIndex],
      },
    })

    if (hasSub) {
      const subIndex = 2
      if (indicator === 'macd') {
        if (chartOverlays.macd) {
          series.push({
            name: t('stock.chart.macdHist'),
            type: 'bar',
            data: chartOverlays.macd,
            xAxisIndex: subIndex,
            yAxisIndex: subIndex,
            barMaxWidth: 10,
            large: true,
            largeThreshold: 600,
            itemStyle: {
              color: (p) => {
                const v = p.data
                if (typeof v !== 'number') {
                  return 'transparent'
                }
                return v >= 0 ? '#ef5350' : '#26a69a'
              },
            },
          })
        }
        if (chartOverlays.dif) {
          series.push({
            name: t('stock.chart.dif'),
            type: 'line',
            data: chartOverlays.dif,
            xAxisIndex: subIndex,
            yAxisIndex: subIndex,
            showSymbol: false,
            lineStyle: { width: 1.2, color: '#f5a623' },
            sampling: 'lttb',
          })
        }
        if (chartOverlays.dea) {
          series.push({
            name: t('stock.chart.dea'),
            type: 'line',
            data: chartOverlays.dea,
            xAxisIndex: subIndex,
            yAxisIndex: subIndex,
            showSymbol: false,
            lineStyle: { width: 1.2, color: '#6ea8fe' },
            sampling: 'lttb',
          })
        }
      } else {
        Object.entries(chartOverlays).forEach(([key, data], idx) => {
          series.push({
            name: key.toUpperCase(),
            type: 'line',
            data,
            xAxisIndex: subIndex,
            yAxisIndex: subIndex,
            showSymbol: false,
            lineStyle: { width: 1.2, color: LINE_COLORS[idx % LINE_COLORS.length] },
            sampling: 'lttb',
          })
        })
      }
    }

    return {
      animation: false,
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'cross' },
        confine: true,
        transitionDuration: 0,
        valueFormatter: (value: unknown) => {
          if (value == null) return '--'
          if (Array.isArray(value)) {
            return value.map((v) => (typeof v === 'number' ? v.toFixed(2) : '--')).join(' / ')
          }
          if (typeof value === 'number') {
            return value.toFixed(2)
          }
          return String(value)
        },
      },
      legend: { top: 4, textStyle: { color: '#cbd5e1' } },
      grid: grids,
      xAxis,
      yAxis,
      dataZoom: [
        { type: 'inside', xAxisIndex: [0, 1, 2].slice(0, grids.length), ...initialZoom },
        {
          type: 'slider',
          bottom: 4,
          height: 20,
          xAxisIndex: [0, 1, 2].slice(0, grids.length),
          ...initialZoom,
        },
      ],
      series,
    }
  }, [bars, chartOverlays, hasBars, indicator, mainMa, strokeSeries, pivotSeries, t, initialZoom])

  useEffect(() => {
    const container = containerRef.current
    if (!container || !hasBars) {
      if (chartRef.current) {
        chartRef.current.dispose()
        chartRef.current = null
      }
      return
    }

    if (!chartRef.current) {
      chartRef.current = echarts.init(container)
    }

    const chart = chartRef.current
    const onResize = () => chart.resize()
    window.addEventListener('resize', onResize)
    const ro =
      typeof ResizeObserver !== 'undefined' ? new ResizeObserver(() => chart.resize()) : null
    ro?.observe(container)

    return () => {
      window.removeEventListener('resize', onResize)
      ro?.disconnect()
      chart.dispose()
      chartRef.current = null
    }
  }, [hasBars])

  useEffect(() => {
    if (!hasBars || !option) {
      return
    }
    const container = containerRef.current
    if (!chartRef.current && container) {
      chartRef.current = echarts.init(container)
    }
    chartRef.current?.setOption(option, true)
    chartRef.current?.resize()
  }, [hasBars, option])

  useEffect(() => {
    if (hasBars) {
      chartRef.current?.resize()
    }
  }, [hasBars, loading, bars.length])

  return (
    <div className="stock-chart-wrap">
      {!hasBars ? (
        <div className="stock-chart stock-chart--empty">
          {loading ? t('common.loading') : t('stock.chart.empty')}
        </div>
      ) : null}
      <div
        ref={containerRef}
        className="stock-chart"
        style={{ display: hasBars ? 'block' : 'none' }}
        aria-hidden={!hasBars}
      />
    </div>
  )
}
