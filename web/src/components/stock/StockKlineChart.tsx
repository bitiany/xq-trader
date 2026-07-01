import { useEffect, useMemo, useRef, useState } from 'react'
import * as echarts from 'echarts'
import { Segmented, Switch } from 'antd'
import { useTranslation } from 'react-i18next'

import type { ChanlunPivot, ChanlunResponse, ChanlunStroke, MainIndicator, SubIndicator, KlineBarItem, StockFundFlowItem } from '@/api/stock'

export interface StockKlineTradeMarker {
  date: string
  direction: 'buy' | 'sell'
  price: number
  quantity?: number
}

interface StockKlineChartProps {
  bars: KlineBarItem[]
  mainIndicator: MainIndicator
  subIndicator: SubIndicator
  mainIndicatorOptions: Array<{ label: string; value: string }>
  subIndicatorOptions: Array<{ label: string; value: string }>
  onMainIndicatorChange: (value: MainIndicator) => void
  onSubIndicatorChange: (value: SubIndicator) => void
  allOverlays: Record<string, Record<string, Array<number | null>>>
  maOverlays?: Record<string, Array<number | null>>
  chanlun?: ChanlunResponse
  fundFlowItems?: StockFundFlowItem[]
  tradeMarkers?: StockKlineTradeMarker[]
  loading?: boolean
}

const VISIBLE_WINDOW = 90
const LINE_COLORS = ['#f5a623', '#6ea8fe', '#b37feb', '#ff7875']

function formatDateLabel(value: string): string {
  return value.slice(5)
}

function formatVolumeLabel(value: number): string {
  if (value >= 1e8) return `${(value / 1e8).toFixed(1)}亿`
  if (value >= 1e4) return `${(value / 1e4).toFixed(0)}万`
  return value.toFixed(0)
}

function formatBarValue(value: number | null | undefined, digits = 2): string {
  if (value == null || Number.isNaN(value)) return '--'
  return value.toFixed(digits)
}

function calcInitialZoom(barCount: number): { start: number; end: number } {
  if (barCount <= VISIBLE_WINDOW) {
    return { start: 0, end: 100 }
  }
  return { start: ((barCount - VISIBLE_WINDOW) / barCount) * 100, end: 100 }
}

function calcTradeZoom(bars: KlineBarItem[], markers: StockKlineTradeMarker[]): { start: number; end: number } | null {
  if (bars.length === 0 || markers.length === 0) return null
  const dateIndexMap = new Map<string, number>()
  bars.forEach((bar, index) => dateIndexMap.set(bar.trade_date.slice(0, 10), index))
  const indexes = markers
    .map((marker) => dateIndexMap.get(marker.date.slice(0, 10)))
    .filter((index): index is number => index != null)
  if (indexes.length === 0) return null

  const first = Math.min(...indexes)
  const last = Math.max(...indexes)
  const halfWindow = Math.floor(VISIBLE_WINDOW / 2)
  const startIndex = Math.max(0, Math.min(first - halfWindow, bars.length - VISIBLE_WINDOW))
  const endIndex = Math.min(bars.length - 1, Math.max(last + halfWindow, startIndex + VISIBLE_WINDOW))
  return {
    start: (startIndex / bars.length) * 100,
    end: ((endIndex + 1) / bars.length) * 100,
  }
}

function buildStrokeSeries(
  bars: KlineBarItem[],
  strokes: ChanlunStroke[],
): echarts.SeriesOption {
  const dateMap = new Map<string, number>()
  bars.forEach((b, i) => dateMap.set(b.trade_date, i))

  const sureData: { xAxis: string | number; yAxis: number }[][] = []
  const virtualData: { xAxis: string | number; yAxis: number }[][] = []
  for (const s of strokes) {
    const si = dateMap.get(s.start_date)
    const ei = dateMap.get(s.end_date)
    if (si == null || ei == null) continue
    const line = [
      { xAxis: si, yAxis: s.start_price },
      { xAxis: ei, yAxis: s.end_price },
    ]
    if (s.is_sure) {
      sureData.push(line)
    } else {
      virtualData.push(line)
    }
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
      data: [
        ...sureData,
        ...virtualData.map((line) => [{ ...line[0], lineStyle: { type: 'dashed' } }, line[1]]),
      ],
    },
    z: 5,
  } as echarts.SeriesOption
}

function buildTradeMarkerSeries(
  bars: KlineBarItem[],
  markers: StockKlineTradeMarker[],
): echarts.SeriesOption | null {
  if (markers.length === 0) return null
  const dateIndexMap = new Map<string, number>()
  bars.forEach((bar, index) => dateIndexMap.set(bar.trade_date.slice(0, 10), index))
  const data = markers
    .map((marker) => {
      const index = dateIndexMap.get(marker.date.slice(0, 10))
      if (index == null) return null
      const bar = bars[index]
      return {
        name: marker.direction === 'buy' ? '买入' : '卖出',
        value: [bar.trade_date, marker.price, marker.direction === 'buy' ? '买' : '卖'],
        symbol: marker.direction === 'buy' ? 'triangle' : 'pin',
        symbolRotate: marker.direction === 'buy' ? 0 : 180,
        symbolSize: marker.direction === 'buy' ? 16 : 20,
        symbolOffset: marker.direction === 'buy' ? [0, 16] : [0, -18],
        itemStyle: { color: marker.direction === 'buy' ? '#ef5350' : '#26a69a' },
        label: {
          show: true,
          formatter: marker.direction === 'buy' ? '买' : '卖',
          color: '#ffffff',
          fontSize: 10,
          fontWeight: 700,
        },
        tooltip: {
          formatter: () => `${marker.direction === 'buy' ? '买入' : '卖出'}<br/>日期：${marker.date}<br/>价格：${marker.price.toFixed(2)}${marker.quantity != null ? `<br/>数量：${marker.quantity}` : ''}`,
        },
      }
    })
    .filter((item): item is NonNullable<typeof item> => item != null)
  if (data.length === 0) return null
  return {
    name: '交易信号',
    type: 'scatter',
    xAxisIndex: 0,
    yAxisIndex: 0,
    data,
    z: 8,
  } as echarts.SeriesOption
}

function buildTd9MarkSeries(
  bars: KlineBarItem[],
  overlays: Record<string, Array<number | null>>,
): echarts.SeriesOption | null {
  const buySetup = overlays.buy_setup ?? []
  const sellSetup = overlays.sell_setup ?? []
  const data: Array<{ value: [number, number, number]; symbolOffset: [number, number]; itemStyle: { color: string } }> = []

  bars.forEach((bar, index) => {
    const sellValue = sellSetup[index]
    if (typeof sellValue === 'number') {
      data.push({
        value: [index, bar.high, sellValue],
        symbolOffset: [0, -10],
        itemStyle: { color: 'rgba(239, 68, 68, 0.65)' },
      })
    }
    const buyValue = buySetup[index]
    if (typeof buyValue === 'number') {
      data.push({
        value: [index, bar.low, buyValue],
        symbolOffset: [0, 10],
        itemStyle: { color: 'rgba(34, 197, 94, 0.65)' },
      })
    }
  })

  if (data.length === 0) return null

  return {
    name: '神奇九转',
    type: 'scatter',
    xAxisIndex: 0,
    yAxisIndex: 0,
    data,
    symbol: 'circle',
    symbolSize: 11,
    label: {
      show: true,
      formatter: '{@[2]}',
      position: 'inside',
      color: '#ffffff',
      fontSize: 8,
      fontWeight: 600,
    },
    itemStyle: {
      borderWidth: 1,
      borderColor: 'rgba(255, 255, 255, 0.6)',
    },
    z: 4,
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

function appendMacdSeries(
  series: echarts.SeriesOption[],
  overlays: Record<string, Array<number | null>>,
  axisIndex: number,
  t: (key: string) => string,
): void {
  if (overlays.macd) {
    series.push({
      name: t('stock.chart.macdHist'),
      type: 'bar',
      data: overlays.macd,
      xAxisIndex: axisIndex,
      yAxisIndex: axisIndex,
      barMaxWidth: 10,
      large: true,
      largeThreshold: 600,
      itemStyle: {
        color: (p) => {
          const value = p.data
          if (typeof value !== 'number') return 'transparent'
          return value >= 0 ? '#ef5350' : '#26a69a'
        },
      },
    })
  }
  if (overlays.dif) {
    series.push({
      name: t('stock.chart.dif'),
      type: 'line',
      data: overlays.dif,
      xAxisIndex: axisIndex,
      yAxisIndex: axisIndex,
      showSymbol: false,
      lineStyle: { width: 1.2, color: '#f5a623' },
      sampling: 'lttb',
    })
  }
  if (overlays.dea) {
    series.push({
      name: t('stock.chart.dea'),
      type: 'line',
      data: overlays.dea,
      xAxisIndex: axisIndex,
      yAxisIndex: axisIndex,
      showSymbol: false,
      lineStyle: { width: 1.2, color: '#6ea8fe' },
      sampling: 'lttb',
    })
  }
}

function appendLineSeries(
  series: echarts.SeriesOption[],
  overlays: Record<string, Array<number | null>>,
  axisIndex: number,
): void {
  Object.entries(overlays).forEach(([key, data], idx) => {
    series.push({
      name: key.toUpperCase(),
      type: 'line',
      data,
      xAxisIndex: axisIndex,
      yAxisIndex: axisIndex,
      showSymbol: false,
      lineStyle: { width: 1.2, color: LINE_COLORS[idx % LINE_COLORS.length] },
      sampling: 'lttb',
    })
  })
}

export function StockKlineChart({
  bars,
  mainIndicator,
  subIndicator,
  mainIndicatorOptions,
  subIndicatorOptions,
  onMainIndicatorChange,
  onSubIndicatorChange,
  allOverlays = {},
  maOverlays = {},
  chanlun,
  fundFlowItems,
  tradeMarkers = [],
  loading = false,
}: StockKlineChartProps) {
  const { t } = useTranslation()
  const containerRef = useRef<HTMLDivElement | null>(null)
  const chartRef = useRef<echarts.ECharts | null>(null)
  const zoomStateRef = useRef<{ start: number; end: number } | null>(null)
  const [showTd9, setShowTd9] = useState(false)
  const hasBars = bars.length > 0
  const barsKey = `${bars[0]?.trade_date ?? ''}-${bars[bars.length - 1]?.trade_date ?? ''}-${bars.length}`
  const markersKey = tradeMarkers.map((marker) => `${marker.date}:${marker.direction}:${marker.price}`).join('|')
  const initialZoom = useMemo(() => calcTradeZoom(bars, tradeMarkers) ?? calcInitialZoom(bars.length), [bars, tradeMarkers])
  const zoomSourceKey = `${barsKey}-${markersKey}`
  const zoomSourceKeyRef = useRef('')
  const [currentPoint, setCurrentPoint] = useState<{ barsKey: string; index: number } | null>(null)
  const currentIndex = currentPoint?.barsKey === barsKey ? currentPoint.index : null
  const safeIndex = currentIndex != null && currentIndex >= 0 && currentIndex < bars.length ? currentIndex : bars.length - 1
  const currentBar = hasBars ? bars[safeIndex] : undefined

  const mainMa = maOverlays

  const currentSubValues = useMemo(() => {
    if (!hasBars) return null
    const idx = safeIndex

    if (subIndicator === 'fundflow' && fundFlowItems && fundFlowItems.length > 0) {
      const bar = bars[idx]
      if (!bar) return null
      const dateFundMap = new Map<string, StockFundFlowItem>()
      for (const item of fundFlowItems) {
        if (item.trade_date) dateFundMap.set(item.trade_date.slice(0, 10), item)
      }
      const item = dateFundMap.get(bar.trade_date.slice(0, 10))
      if (!item) return null
      return [
        { label: '超大单', value: item.huge_net_inflow_pct, color: '#ef5350' },
        { label: '大单', value: item.big_net_inflow_pct, color: '#ff9800' },
        { label: '中单', value: item.mid_net_inflow_pct, color: '#2196f3' },
        { label: '小单', value: item.small_net_inflow_pct, color: '#4caf50' },
      ]
    }

    const overlayData = allOverlays[subIndicator] ?? {}
    if (subIndicator === 'macd') {
      const macdVal = overlayData.macd?.[idx]
      return [
        { label: 'MACD', value: macdVal ?? null, color: macdVal != null && macdVal >= 0 ? '#ef5350' : '#26a69a' },
        { label: 'DIF', value: overlayData.dif?.[idx] ?? null, color: '#f5a623' },
        { label: 'DEA', value: overlayData.dea?.[idx] ?? null, color: '#6ea8fe' },
      ]
    }

    const entries = Object.entries(overlayData)
    if (entries.length === 0) return null
    return entries.map(([key, values], i) => ({
      label: key.toUpperCase(),
      value: values[idx] ?? null,
      color: LINE_COLORS[i % LINE_COLORS.length],
    }))
  }, [safeIndex, subIndicator, allOverlays, fundFlowItems, bars, hasBars])

  const strokeSeries = useMemo(
    () => (chanlun && chanlun.strokes.length > 0 ? buildStrokeSeries(bars, chanlun.strokes) : null),
    [bars, chanlun],
  )
  const pivotSeries = useMemo(
    () => (chanlun && chanlun.pivots.length > 0 ? buildPivotMarkAreas(bars, chanlun.pivots) : null),
    [bars, chanlun],
  )
  const tradeMarkerSeries = useMemo(
    () => buildTradeMarkerSeries(bars, tradeMarkers),
    [bars, tradeMarkers],
  )

  const option = useMemo(() => {
    if (!hasBars) {
      return null
    }

    const dates = bars.map((b) => b.trade_date)
    const ohlc = bars.map((b) => [b.open, b.close, b.low, b.high])
    const volumes = bars.map((b) => b.volume)
    const volColors = bars.map((b) => (b.close >= b.open ? '#ef5350' : '#26a69a'))
    const mainFullMode = mainIndicator === 'chanlun'
    const subHasFundFlow = subIndicator === 'fundflow'
    // 统一 3 个 grid：主图 + 成交量 + 副图指标，缠论模式主图更大
    const grids = mainFullMode
      ? [
        { left: 56, right: 48, top: 36, height: '56%' },
        { left: 56, right: 48, top: '66%', height: '10%' },
        { left: 56, right: 48, top: '80%', height: '14%' },
      ]
      : [
        { left: 56, right: 48, top: 36, height: '50%' },
        { left: 56, right: 48, top: '66%', height: '12%' },
        { left: 56, right: 48, top: '80%', height: '14%' },
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

    // 主图指标：均线（MA 始终显示）
    Object.entries(mainMa).forEach(([key, data], idx) => {
      series.push({
        name: key.toUpperCase(),
        type: 'line',
        data,
        xAxisIndex: 0,
        yAxisIndex: 0,
        showSymbol: false,
        lineStyle: { width: 1.2, color: LINE_COLORS[idx % LINE_COLORS.length] },
        sampling: 'lttb',
      })
    })

    // 主图指标：布林带
    if (mainIndicator === 'boll') {
      appendLineSeries(series, allOverlays.boll ?? {}, 0)
    }

    // 主图指标：TD9（开关控制，不受 mainIndicator 影响）
    const td9Overlays = allOverlays.td9
    const td9Series = showTd9 && td9Overlays ? buildTd9MarkSeries(bars, td9Overlays) : null
    if (td9Series) series.push(td9Series)

    // 主图指标：缠论（笔和中枢）
    if (pivotSeries && mainIndicator === 'chanlun') series.push(pivotSeries)
    if (strokeSeries && mainIndicator === 'chanlun') series.push(strokeSeries)
    if (tradeMarkerSeries) series.push(tradeMarkerSeries)

    // 成交量（始终在 grid[1]）
    series.push({
      name: t('stock.chart.volume'),
      type: 'bar',
      data: volumes,
      xAxisIndex: 1,
      yAxisIndex: 1,
      large: true,
      largeThreshold: 600,
      itemStyle: { color: (p: { dataIndex: number }) => volColors[p.dataIndex] },
    })

    // 副图指标（独立于主图）
    if (subHasFundFlow && fundFlowItems && fundFlowItems.length > 0) {
      const dateFundMap = new Map<string, StockFundFlowItem>()
      for (const item of fundFlowItems) {
        if (item.trade_date) dateFundMap.set(item.trade_date.slice(0, 10), item)
      }
      const fundData = bars.map((b) => {
        const item = dateFundMap.get(b.trade_date.slice(0, 10))
        return item
          ? { huge: item.huge_net_inflow_pct, big: item.big_net_inflow_pct, mid: item.mid_net_inflow_pct, small: item.small_net_inflow_pct }
          : { huge: null, big: null, mid: null, small: null }
      })
      const hugeData = fundData.map((d) => d.huge)
      const bigData = fundData.map((d) => d.big)
      const midData = fundData.map((d) => d.mid)
      const smallData = fundData.map((d) => d.small)
      series.push(
        {
          name: '超大单',
          type: 'line',
          data: hugeData,
          xAxisIndex: 2,
          yAxisIndex: 2,
          showSymbol: false,
          lineStyle: { width: 1.5, color: '#ef5350' },
          sampling: 'lttb',
        },
        {
          name: '大单',
          type: 'line',
          data: bigData,
          xAxisIndex: 2,
          yAxisIndex: 2,
          showSymbol: false,
          lineStyle: { width: 1.5, color: '#ff9800' },
          sampling: 'lttb',
        },
        {
          name: '中单',
          type: 'line',
          data: midData,
          xAxisIndex: 2,
          yAxisIndex: 2,
          showSymbol: false,
          lineStyle: { width: 1.5, color: '#2196f3' },
          sampling: 'lttb',
        },
        {
          name: '小单',
          type: 'line',
          data: smallData,
          xAxisIndex: 2,
          yAxisIndex: 2,
          showSymbol: false,
          lineStyle: { width: 1.5, color: '#4caf50' },
          sampling: 'lttb',
        },
      )
    } else {
      // 副图指标：MACD / RSI / KDJ / BIAS / ADX — 使用 allOverlays 中对应指标的数据
      const subIndex = 2
      const subOverlayData = allOverlays[subIndicator] ?? {}
      if (subIndicator === 'macd') {
        appendMacdSeries(series, subOverlayData, subIndex, t)
      } else {
        appendLineSeries(series, subOverlayData, subIndex)
      }
    }

    const xAxisIndex = Array.from({ length: grids.length }, (_, i) => i)
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
          if (typeof value === 'number') return value.toFixed(2)
          return String(value)
        },
      },
      legend: { top: 4, textStyle: { color: '#cbd5e1' } },
      grid: grids,
      xAxis,
      yAxis,
      dataZoom: [
        { type: 'inside', xAxisIndex, ...initialZoom },
        { type: 'slider', bottom: 4, height: 20, xAxisIndex, ...initialZoom },
      ],
      series,
    }
  }, [allOverlays, bars, fundFlowItems, hasBars, mainIndicator, subIndicator, initialZoom, mainMa, pivotSeries, showTd9, strokeSeries, t, tradeMarkerSeries])

  const resizeCleanupRef = useRef<(() => void) | null>(null)

  useEffect(() => {
    const container = containerRef.current
    if (!container || !hasBars) {
      if (chartRef.current) {
        chartRef.current.dispose()
        chartRef.current = null
        resizeCleanupRef.current?.()
        resizeCleanupRef.current = null
      }
      return
    }

    // Init chart if needed
    if (!chartRef.current) {
      chartRef.current = echarts.init(container)
      // Set up resize observer (only on init)
      const onResize = () => chartRef.current?.resize()
      window.addEventListener('resize', onResize)
      const observer = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(() => chartRef.current?.resize()) : null
      observer?.observe(container)
      resizeCleanupRef.current = () => {
        window.removeEventListener('resize', onResize)
        observer?.disconnect()
      }
    }
    const chart = chartRef.current

    // Apply option if available
    if (option) {
      if (zoomSourceKeyRef.current !== zoomSourceKey) {
        zoomSourceKeyRef.current = zoomSourceKey
        zoomStateRef.current = null
      }
      // Preserve dataZoom state
      const currentOption = chart.getOption()
      const dz = currentOption?.dataZoom as Array<{ start?: number; end?: number }> | undefined
      const preservedZoom = zoomStateRef.current
      const nextOption = preservedZoom
        ? {
          ...option,
          dataZoom: [
            { type: 'inside', xAxisIndex: [0, 1, 2], ...preservedZoom },
            { type: 'slider', bottom: 4, height: 20, xAxisIndex: [0, 1, 2], ...preservedZoom },
          ],
        }
        : option
      if (dz && dz.length > 0 && dz[0].start != null && dz[0].end != null) {
        zoomStateRef.current = { start: dz[0].start, end: dz[0].end }
      }
      // 使用 replaceMerge 仅替换 series，保留 tooltip/axisPointer 状态，
      // 避免盘中实时行情推送时 setOption 全量替换导致十字星面板闪烁消失
      chart.setOption(nextOption, { replaceMerge: ['series'] })
      chart.resize()
    }

    // Axis pointer event handler
    const handleAxisPointer = (params: unknown) => {
      const event = params as { axesInfo?: Array<{ axisDim?: string; axisIndex?: number; value?: number | string }> }
      const axisInfo = event.axesInfo?.find((item) => item.axisDim === 'x' && item.axisIndex === 0)
      const index = Number(axisInfo?.value)
      if (Number.isInteger(index) && index >= 0 && index < bars.length) {
        setCurrentPoint({ barsKey, index })
      }
    }
    // DataZoom state handler
    const handleDataZoom = () => {
      const opt = chart.getOption()
      const dz = opt?.dataZoom as Array<{ start?: number; end?: number }> | undefined
      if (dz && dz.length > 0 && dz[0].start != null && dz[0].end != null) {
        zoomStateRef.current = { start: dz[0].start, end: dz[0].end }
      }
    }
    // 鼠标离开图表时重置 currentIndex，恢复显示最新数据
    const handleGlobalOut = () => {
      setCurrentPoint(null)
    }
    chart.off('updateAxisPointer')
    chart.on('updateAxisPointer', handleAxisPointer)
    chart.off('globalout')
    chart.on('globalout', handleGlobalOut)
    chart.off('datazoom')
    chart.on('datazoom', handleDataZoom)

    return () => {
      chart.off('updateAxisPointer')
      chart.off('globalout')
      chart.off('datazoom')
    }
  }, [bars, barsKey, hasBars, option, zoomSourceKey])

  // Unmount cleanup: dispose chart and resize observer
  useEffect(() => {
    return () => {
      resizeCleanupRef.current?.()
      resizeCleanupRef.current = null
      chartRef.current?.dispose()
      chartRef.current = null
    }
  }, [])

  return (
    <div className="stock-chart-wrap">
      {currentBar ? (
        <div className="stock-chart__bar-info">
          <span>{currentBar.trade_date}</span>
          <span>开 {formatBarValue(currentBar.open)}</span>
          <span>高 {formatBarValue(currentBar.high)}</span>
          <span>低 {formatBarValue(currentBar.low)}</span>
          <span>收 {formatBarValue(currentBar.close)}</span>
          <span>涨跌 {formatBarValue(currentBar.pct_chg)}%</span>
          <span>量 {formatVolumeLabel(currentBar.volume)}</span>
        </div>
      ) : null}
      <div className="stock-chart__indicator-toggle">
        <Segmented
          size="small"
          value={mainIndicator}
          options={mainIndicatorOptions}
          onChange={(value) => onMainIndicatorChange(value as MainIndicator)}
        />
        <Segmented
          size="small"
          value={subIndicator}
          options={subIndicatorOptions}
          onChange={(value) => onSubIndicatorChange(value as SubIndicator)}
        />
        <span className="stock-chart__td9-toggle">
          <Switch size="small" checked={showTd9} onChange={setShowTd9} />
          <span className="stock-chart__td9-label">{t('stock.indicators.td9')}</span>
        </span>
      </div>
      {!hasBars ? (
        <div className="stock-chart stock-chart--empty">
          {loading ? t('common.loading') : t('stock.chart.empty')}
        </div>
      ) : null}
      <div className="stock-chart__chart-area">
        <div
          ref={containerRef}
          className="stock-chart"
          style={{ display: hasBars ? 'block' : 'none' }}
          aria-hidden={!hasBars}
        />
        {hasBars && currentSubValues && currentSubValues.length > 0 && (
          <div className="stock-chart__sub-info">
            <span className="stock-chart__sub-label">{subIndicator.toUpperCase()}</span>
            {currentSubValues.map(({ label, value, color }) => (
              <span key={label} style={{ color }}>
                {label}:{value != null ? value.toFixed(2) : '--'}
              </span>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
