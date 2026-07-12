import { useEffect, useRef, useMemo, useState, useCallback } from 'react'
import * as echarts from 'echarts'
import type { MainIndicator, SubIndicator, ChartPeriod } from '../stores/monitorStore'
import type { KlineBar, ChanlunData } from '../utils/klineHelpers'
import { calcTD9 } from '../utils/klineHelpers'

interface MiniKlineChartProps {
  symbol: string
  bars: KlineBar[]
  mainIndicator: MainIndicator
  subIndicator: SubIndicator
  isMaximized: boolean
  period: ChartPeriod
  chanlunData: ChanlunData | null
}

// 副图指标计算结果类型
interface SubIndicatorData {
  macd?: (number | null)[]
  dif?: (number | null)[]
  dea?: (number | null)[]
  rsi?: (number | null)[]
}

export function MiniKlineChart({
  symbol,
  bars,
  mainIndicator,
  subIndicator,
  isMaximized,
  period,
  chanlunData,
}: MiniKlineChartProps) {
  const chartRef = useRef<HTMLDivElement>(null)
  const chartInstance = useRef<echarts.ECharts | null>(null)
  const zoomStateRef = useRef<{ start: number; end: number } | null>(null)
  const [hoverIndex, setHoverIndex] = useState<number | null>(null)

  // ==================== 指标计算 ====================

  // 分时图模式标记：1m 渲染为分时图（价格线+均价线），其他周期为蜡烛图
  const isTimesharing = period === '1m'

  // 计算分时均线（VWAP）：使用真实成交额
  // amount 单位为元，volume 单位为手(1手=100股)，需将 volume 转为股
  // 分时图模式下始终计算；蜡烛图模式仅在选中 vwap 时计算
  const vwapData = useMemo(() => {
    if (bars.length === 0) return []
    if (!isTimesharing && mainIndicator !== 'vwap') return []
    let cumAmount = 0
    let cumVolume = 0
    return bars.map((bar) => {
      cumAmount += bar.amount
      cumVolume += bar.volume * 100
      return cumVolume > 0 ? cumAmount / cumVolume : bar.close
    })
  }, [bars, mainIndicator, isTimesharing])

  // 计算 MA5/MA20
  const ma5Data = useMemo(() => {
    if (mainIndicator !== 'ma') return []
    return calcMA(bars, 5)
  }, [bars, mainIndicator])

  const ma20Data = useMemo(() => {
    if (mainIndicator !== 'ma') return []
    return calcMA(bars, 20)
  }, [bars, mainIndicator])

  // 计算布林带
  const bollData = useMemo(() => {
    if (mainIndicator !== 'boll') return null
    return calcBoll(bars, 20, 2)
  }, [bars, mainIndicator])

  // 计算唐奇安通道
  const donchianData = useMemo(() => {
    if (mainIndicator !== 'donchian') return null
    return calcDonchian(bars, 20)
  }, [bars, mainIndicator])

  // 计算神奇九转
  const td9Data = useMemo(() => {
    if (mainIndicator !== 'td9' || bars.length === 0) return null
    return calcTD9(bars)
  }, [bars, mainIndicator])

  // 计算副图指标（MACD / RSI）
  const subIndicatorData = useMemo<SubIndicatorData>(() => {
    if (bars.length === 0) return {}
    if (subIndicator === 'macd') {
      return calcMACD(bars, 12, 26, 9)
    }
    if (subIndicator === 'rsi') {
      return { rsi: calcRSI(bars, 14) }
    }
    return {}
  }, [bars, subIndicator])

  // ==================== 当前 bar 信息（放大模式十字星） ====================

  const currentIndex = hoverIndex !== null && hoverIndex >= 0 && hoverIndex < bars.length
    ? hoverIndex
    : bars.length - 1
  const currentBar = bars.length > 0 ? bars[currentIndex] : null

  const formatBarValue = useCallback((v: number | null | undefined, digits = 2) => {
    if (v == null || Number.isNaN(v)) return '--'
    return v.toFixed(digits)
  }, [])

  const formatVolume = useCallback((v: number) => {
    if (v >= 1e8) return `${(v / 1e8).toFixed(1)}亿`
    if (v >= 1e4) return `${(v / 1e4).toFixed(0)}万`
    return v.toFixed(0)
  }, [])

  // ==================== ECharts 初始化与销毁 ====================

  useEffect(() => {
    if (!chartRef.current) return
    if (!chartInstance.current) {
      chartInstance.current = echarts.init(chartRef.current)
    }
    return () => {
      chartInstance.current?.dispose()
      chartInstance.current = null
    }
  }, [])

  // ==================== 图表配置 ====================

  useEffect(() => {
    if (!chartInstance.current) return
    const chart = chartInstance.current

    // 延迟到下一帧渲染，确保容器尺寸已更新（修复切换不显示问题）
    const rafId = requestAnimationFrame(() => {
      if (!chartInstance.current) return
      // 先 resize 确保容器尺寸正确
      chart.resize()
      renderChart()
    })

    function renderChart() {
      if (!chartInstance.current) return
      const chart = chartInstance.current

      const times = bars.map((b) => b.time)
      const ohlc = bars.map((b) => [b.open, b.close, b.low, b.high])
      const volumes = bars.map((b) => b.volume)
      const volColors = bars.map((b) => (b.close >= b.open ? '#e03e3e' : '#2eaa67'))

      // 判断是否有副图指标（MACD/RSI）；分时图模式不显示副图指标
      const hasSubIndicator = !isTimesharing && (subIndicator === 'macd' || subIndicator === 'rsi')

      // ── 三 grid 布局：主图 + 成交量 + 副图指标 ──
      const grids: echarts.GridComponentOption[] = hasSubIndicator
        ? isMaximized
          ? [
              { left: 60, right: 50, top: 32, height: '52%' },
              { left: 60, right: 50, top: '68%', height: '12%' },
              { left: 60, right: 50, top: '84%', height: '12%' },
            ]
          : [
              { left: '8%', right: '4%', top: '4%', height: '52%' },
              { left: '8%', right: '4%', top: '68%', height: '12%' },
              { left: '8%', right: '4%', top: '84%', height: '12%' },
            ]
        : isMaximized
          ? [
              { left: 60, right: 50, top: 32, height: '62%' },
              { left: 60, right: 50, top: '70%', height: '22%' },
            ]
          : [
              { left: '8%', right: '4%', top: '4%', height: '62%' },
              { left: '8%', right: '4%', top: '70%', height: '22%' },
            ]

      const gridCount = grids.length
      const xAxisIndexAll = Array.from({ length: gridCount }, (_, i) => i)

      // ── X 轴 ──
      const xAxes = grids.map((_, i) => ({
        type: 'category' as const,
        data: times,
        gridIndex: i,
        boundaryGap: i > 0,
        axisLine: { lineStyle: { color: 'rgba(255,255,255,0.07)' } },
        axisLabel: {
          show: i === gridCount - 1,
          fontSize: isMaximized ? 11 : 9,
          color: '#5f6f85',
          interval: Math.max(0, Math.floor(times.length / (isMaximized ? 8 : 4)) - 1),
        },
      }))

      // ── Y 轴 ──
      const yAxes = grids.map((_, i) => {
        const isVolAxis = i === 1
        return {
          scale: !isVolAxis,
          gridIndex: i,
          splitLine: {
            show: i === 0,
            lineStyle: { color: 'rgba(255,255,255,0.05)' },
          },
          axisLabel: {
            show: isMaximized || i === 0,
            fontSize: isMaximized ? 11 : 9,
            color: '#5f6f85',
            formatter: isVolAxis
              ? (v: number) => (v >= 1e4 ? `${(v / 1e4).toFixed(0)}万` : v.toFixed(0))
              : undefined,
          },
          splitNumber: isVolAxis ? 2 : undefined,
          min: isVolAxis ? 0 : undefined,
        }
      })

      // ── 系列 ──
      const series: echarts.SeriesOption[] = []

      if (isTimesharing) {
        // 分时图模式：价格折线 + 均价线 + 渐变面积（东财分时图风格）
        const closes = bars.map((b) => b.close)
        const refPrice = bars.length > 0 ? bars[0].open : 0
        series.push({
          name: '价格',
          type: 'line',
          data: closes,
          xAxisIndex: 0,
          yAxisIndex: 0,
          symbol: 'none',
          lineStyle: { color: '#60a5fa', width: 2 },
          areaStyle: { color: 'rgba(96,165,250,0.12)' },
          markLine: {
            symbol: 'none',
            silent: true,
            lineStyle: { color: 'rgba(154,170,190,0.4)', width: 1, type: 'dashed' },
            label: { show: false },
            data: [{ yAxis: refPrice }],
          },
        })
        // 均价线（VWAP）：始终显示
        if (vwapData.length > 0) {
          series.push({
            name: '均价',
            type: 'line',
            data: vwapData,
            xAxisIndex: 0,
            yAxisIndex: 0,
            symbol: 'none',
            lineStyle: { color: '#faad14', width: 1.2 },
          })
        }
      } else {
        // 蜡烛图模式
        series.push({
          name: symbol,
          type: 'candlestick',
          data: ohlc,
          xAxisIndex: 0,
          yAxisIndex: 0,
          itemStyle: {
            color: '#e03e3e',
            color0: '#2eaa67',
            borderColor: '#e03e3e',
            borderColor0: '#2eaa67',
          },
        })
      }

      // 主图指标：分时均线（VWAP）— 仅蜡烛图模式
      if (!isTimesharing && mainIndicator === 'vwap' && vwapData.length > 0) {
        series.push({
          name: '分时均线',
          type: 'line',
          data: vwapData,
          xAxisIndex: 0,
          yAxisIndex: 0,
          smooth: true,
          symbol: 'none',
          lineStyle: { color: '#faad14', width: 1.5 },
        })
      }

      // 以下主图指标仅蜡烛图模式生效（分时图模式固定为价格线+均价线）
      if (!isTimesharing) {
      // 主图指标：MA5/MA20
      if (mainIndicator === 'ma') {
        if (ma5Data.length > 0) {
          series.push({
            name: 'MA5',
            type: 'line',
            data: ma5Data,
            xAxisIndex: 0,
            yAxisIndex: 0,
            symbol: 'none',
            lineStyle: { color: '#1677ff', width: 1 },
          })
        }
        if (ma20Data.length > 0) {
          series.push({
            name: 'MA20',
            type: 'line',
            data: ma20Data,
            xAxisIndex: 0,
            yAxisIndex: 0,
            symbol: 'none',
            lineStyle: { color: '#9aaabe', width: 1 },
          })
        }
      }

      // 主图指标：布林带
      if (mainIndicator === 'boll' && bollData) {
        series.push(
          {
            name: 'BOLL Upper',
            type: 'line',
            data: bollData.upper,
            xAxisIndex: 0,
            yAxisIndex: 0,
            symbol: 'none',
            lineStyle: { color: 'rgba(22,119,255,0.3)', width: 1, type: 'dashed' },
          },
          {
            name: 'BOLL Mid',
            type: 'line',
            data: bollData.mid,
            xAxisIndex: 0,
            yAxisIndex: 0,
            symbol: 'none',
            lineStyle: { color: 'rgba(22,119,255,0.5)', width: 1 },
          },
          {
            name: 'BOLL Lower',
            type: 'line',
            data: bollData.lower,
            xAxisIndex: 0,
            yAxisIndex: 0,
            symbol: 'none',
            lineStyle: { color: 'rgba(22,119,255,0.3)', width: 1, type: 'dashed' },
          },
        )
      }

      // 主图指标：唐奇安通道
      if (mainIndicator === 'donchian' && donchianData) {
        series.push(
          {
            name: 'DC Upper',
            type: 'line',
            data: donchianData.upper,
            xAxisIndex: 0,
            yAxisIndex: 0,
            symbol: 'none',
            lineStyle: { color: 'rgba(250,173,20,0.5)', width: 1 },
          },
          {
            name: 'DC Lower',
            type: 'line',
            data: donchianData.lower,
            xAxisIndex: 0,
            yAxisIndex: 0,
            symbol: 'none',
            lineStyle: { color: 'rgba(250,173,20,0.5)', width: 1 },
          },
        )
      }

      // 主图指标：神奇九转（用 markPoint 标注 1-9 数字）
      if (mainIndicator === 'td9' && td9Data) {
        const td9MarkPoints: echarts.MarkPointComponentOption[] = []
        for (let i = 0; i < td9Data.buySetup.length; i++) {
          const buyVal = td9Data.buySetup[i]
          const sellVal = td9Data.sellSetup[i]
          if (buyVal !== null) {
            // 买入计数：在 low 下方显示数字
            td9MarkPoints.push({
              coord: [i, bars[i].low],
              symbol: 'circle',
              symbolSize: 0,
              label: {
                show: true,
                formatter: String(buyVal),
                color: buyVal === 9 ? '#ff4444' : '#2eaa67',
                fontSize: isMaximized ? 12 : 9,
                offset: [0, 14],
              },
            })
          }
          if (sellVal !== null) {
            // 卖出计数：在 high 上方显示数字
            td9MarkPoints.push({
              coord: [i, bars[i].high],
              symbol: 'circle',
              symbolSize: 0,
              label: {
                show: true,
                formatter: String(sellVal),
                color: sellVal === 9 ? '#ff4444' : '#e03e3e',
                fontSize: isMaximized ? 12 : 9,
                offset: [0, -14],
              },
            })
          }
        }
        // 将 markPoint 附加到 candlestick series
        if (td9MarkPoints.length > 0 && series[0]) {
          (series[0] as echarts.SeriesCandlestickOption).markPoint = {
            data: td9MarkPoints,
          }
        }
      }

      // 主图指标：缠论（笔用 markLine，中枢用矩形 markArea，分型用 markPoint）
      if (mainIndicator === 'chanlun' && chanlunData) {
        // 1. 笔：用 markLine 绘制分型连线
        if (chanlunData.strokes.length > 0 && series[0]) {
          const strokeLines = chanlunData.strokes.map((s) => ([
            { coord: [s.start_index, s.start_price] },
            { coord: [s.end_index, s.end_price] },
          ]))
          const candleSeries = series[0] as echarts.SeriesCandlestickOption
          candleSeries.markLine = {
            symbol: ['circle', 'arrow'],
            symbolSize: 5,
            lineStyle: {
              color: '#faad14',
              width: 1.5,
              type: 'solid',
            },
            label: { show: false },
            data: strokeLines,
          }
        }
        // 2. 中枢：用 markArea 绘制矩形区域
        if (chanlunData.pivots.length > 0 && series[0]) {
          const pivotAreas = chanlunData.pivots.map((p) => ([
            { coord: [p.start_index, p.zg], itemStyle: { color: 'rgba(250,173,20,0.12)' } },
            { coord: [p.end_index, p.zd] },
          ]))
          const candleSeries = series[0] as echarts.SeriesCandlestickOption
          // 若已有 markLine，追加 markArea；否则直接设置
          const existingMarkLine = candleSeries.markLine
          candleSeries.markArea = {
            silent: true,
            label: {
              show: isMaximized,
              position: 'insideTop',
              color: 'rgba(250,173,20,0.7)',
              fontSize: 9,
              formatter: () => '中枢',
            },
            data: pivotAreas,
          }
          // 保留已有 markLine
          if (existingMarkLine) {
            candleSeries.markLine = existingMarkLine
          }
        }
        // 3. 分型：用 markPoint 标注顶底分型
        if (chanlunData.fractals.length > 0 && series[0]) {
          const fractalPoints = chanlunData.fractals.map((f) => ({
            coord: [f.index, f.price],
            symbol: f.direction === 'top' ? 'triangle' : 'pin',
            symbolSize: isMaximized ? 10 : 7,
            symbolOffset: f.direction === 'top' ? [0, -12] : [0, 12],
            symbolRotate: f.direction === 'top' ? 180 : 0,
            itemStyle: {
              color: f.direction === 'top' ? '#e03e3e' : '#2eaa67',
            },
            label: { show: false },
          }))
          const candleSeries = series[0] as echarts.SeriesCandlestickOption
          candleSeries.markPoint = {
            data: fractalPoints,
          }
        }
        // 4. 买卖点：用 scatter 标注一买/二买/三买/一卖/二卖/三卖
        if (chanlunData.bs_points && chanlunData.bs_points.length > 0) {
          const recentBsps = chanlunData.bs_points.slice(-15)
          const bspData = recentBsps.map((bsp) => ({
            value: [bsp.index, bsp.price, bsp.is_buy ? `${bsp.types.join('/')}买` : `${bsp.types.join('/')}卖`],
            symbol: 'triangle',
            symbolRotate: bsp.is_buy ? 0 : 180,
            symbolSize: isMaximized ? 14 : 9,
            symbolOffset: bsp.is_buy ? [0, 16] : [0, -16],
            itemStyle: { color: bsp.is_buy ? '#22c55e' : '#ef4444' },
            label: {
              show: isMaximized,
              formatter: `${bsp.types.join('/')}${bsp.is_buy ? '买' : '卖'}`,
              color: bsp.is_buy ? '#22c55e' : '#ef4444',
              fontSize: 10,
              fontWeight: 700,
              position: bsp.is_buy ? 'bottom' : 'top',
              distance: 6,
            },
          }))
          series.push({
            name: '买卖点',
            type: 'scatter',
            xAxisIndex: 0,
            yAxisIndex: 0,
            data: bspData,
            z: 9,
          } as echarts.SeriesOption)
        }
      }
      } // end if (!isTimesharing)

      // 成交量（始终在 grid[1]）
      series.push({
        name: 'Volume',
        type: 'bar',
        data: volumes.map((v, i) => ({
          value: v,
          itemStyle: { color: volColors[i] },
        })),
        xAxisIndex: 1,
        yAxisIndex: 1,
        barMaxWidth: isMaximized ? 8 : 4,
      })

      // 副图指标：MACD（grid[2]）— 仅蜡烛图模式且有副图指标时
      if (hasSubIndicator && subIndicator === 'macd' && subIndicatorData.macd) {
        const subAxis = 2
        series.push({
          name: 'MACD',
          type: 'bar',
          data: subIndicatorData.macd.map((v) => v ?? 0),
          xAxisIndex: subAxis,
          yAxisIndex: subAxis,
          barMaxWidth: isMaximized ? 6 : 3,
          itemStyle: {
            color: (p: { data: number }) => (p.data >= 0 ? '#e03e3e' : '#2eaa67'),
          },
        })
        if (subIndicatorData.dif) {
          series.push({
            name: 'DIF',
            type: 'line',
            data: subIndicatorData.dif,
            xAxisIndex: subAxis,
            yAxisIndex: subAxis,
            symbol: 'none',
            lineStyle: { color: '#faad14', width: 1 },
          })
        }
        if (subIndicatorData.dea) {
          series.push({
            name: 'DEA',
            type: 'line',
            data: subIndicatorData.dea,
            xAxisIndex: subAxis,
            yAxisIndex: subAxis,
            symbol: 'none',
            lineStyle: { color: '#1677ff', width: 1 },
          })
        }
      }

      // 副图指标：RSI（grid[2]）— 仅蜡烛图模式且有副图指标时
      if (hasSubIndicator && subIndicator === 'rsi' && subIndicatorData.rsi) {
        const subAxis = 2
        series.push({
          name: 'RSI',
          type: 'line',
          data: subIndicatorData.rsi,
          xAxisIndex: subAxis,
          yAxisIndex: subAxis,
          symbol: 'none',
          lineStyle: { color: '#b37feb', width: 1.2 },
        })
      }

      // ── 保留用户缩放状态 ──
      const preservedZoom = zoomStateRef.current

      const option: echarts.EChartsCoreOption = {
        backgroundColor: 'transparent',
        animation: false,
        tooltip: {
          show: isMaximized,
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
        axisPointer: {
          link: [{ xAxisIndex: 'all' }],
        },
        legend: { show: false },
        grid: grids,
        xAxis: xAxes,
        yAxis: yAxes,
        series,
        dataZoom: isMaximized
          ? [
              {
                type: 'inside',
                xAxisIndex: xAxisIndexAll,
                ...(preservedZoom ?? { start: 0, end: 100 }),
              },
              {
                type: 'slider',
                xAxisIndex: xAxisIndexAll,
                bottom: 4,
                height: 20,
                ...(preservedZoom ?? { start: 0, end: 100 }),
              },
            ]
          : [],
      }

      chart.setOption(option, { replaceMerge: ['series', 'grid', 'xAxis', 'yAxis'] })
    }

    return () => {
      cancelAnimationFrame(rafId)
    }
  }, [bars, symbol, mainIndicator, subIndicator, isMaximized, isTimesharing, vwapData, ma5Data, ma20Data, bollData, donchianData, td9Data, chanlunData, subIndicatorData])

  // ==================== 事件绑定（放大模式十字星 + 缩放状态保留） ====================

  useEffect(() => {
    if (!chartInstance.current) return
    const chart = chartInstance.current

    const handleAxisPointer = (params: unknown) => {
      const event = params as { axesInfo?: Array<{ axisDim?: string; axisIndex?: number; value?: number | string }> }
      const axisInfo = event.axesInfo?.find((item) => item.axisDim === 'x' && item.axisIndex === 0)
      const index = Number(axisInfo?.value)
      if (Number.isInteger(index) && index >= 0 && index < bars.length) {
        setHoverIndex(index)
      }
    }

    const handleDataZoom = () => {
      const opt = chart.getOption()
      const dz = opt?.dataZoom as Array<{ start?: number; end?: number }> | undefined
      if (dz && dz.length > 0 && dz[0].start != null && dz[0].end != null) {
        zoomStateRef.current = { start: dz[0].start, end: dz[0].end }
      }
    }

    const handleGlobalOut = () => {
      setHoverIndex(null)
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
  }, [bars.length])

  // ==================== Resize 监听 ====================

  useEffect(() => {
    if (!chartInstance.current) return
    const handleResize = () => {
      chartInstance.current?.resize()
    }
    const ro = new ResizeObserver(handleResize)
    if (chartRef.current) ro.observe(chartRef.current)
    return () => ro.disconnect()
  }, [])

  return (
    <div className="monitor-cell__chart-wrapper" style={{ width: '100%', height: '100%', display: 'flex', flexDirection: 'column' }}>
      {isMaximized && currentBar && (
        <div className="monitor-cell__bar-info" style={{
          display: 'flex',
          gap: 12,
          padding: '4px 8px',
          fontSize: 11,
          color: '#9ca3af',
          flexShrink: 0,
        }}>
          <span style={{ color: '#e5e7eb' }}>{currentBar.time}</span>
          {isTimesharing ? (
            <>
              <span>价格 <span style={{ color: '#e5e7eb' }}>{formatBarValue(currentBar.close)}</span></span>
              <span>均价 <span style={{ color: '#faad14' }}>{formatBarValue(vwapData[currentIndex] ?? null)}</span></span>
              <span>量 {formatVolume(currentBar.volume)}</span>
            </>
          ) : (
            <>
              <span>开 {formatBarValue(currentBar.open)}</span>
              <span>高 <span style={{ color: '#e03e3e' }}>{formatBarValue(currentBar.high)}</span></span>
              <span>低 <span style={{ color: '#2eaa67' }}>{formatBarValue(currentBar.low)}</span></span>
              <span>收 {formatBarValue(currentBar.close)}</span>
              <span>量 {formatVolume(currentBar.volume)}</span>
              {subIndicator === 'macd' && subIndicatorData.macd && (
                <span>
                  MACD {formatBarValue(subIndicatorData.macd[currentIndex] ?? null)}
                  <span style={{ marginLeft: 8, color: '#faad14' }}>DIF {formatBarValue(subIndicatorData.dif?.[currentIndex] ?? null)}</span>
                  <span style={{ marginLeft: 8, color: '#1677ff' }}>DEA {formatBarValue(subIndicatorData.dea?.[currentIndex] ?? null)}</span>
                </span>
              )}
              {subIndicator === 'rsi' && subIndicatorData.rsi && (
                <span style={{ color: '#b37feb' }}>RSI {formatBarValue(subIndicatorData.rsi[currentIndex] ?? null)}</span>
              )}
            </>
          )}
        </div>
      )}
      <div ref={chartRef} className="monitor-cell__chart-inner" style={{ width: '100%', flex: 1 }} />
    </div>
  )
}

// ==================== 指标计算辅助函数 ====================

function calcMA(bars: KlineBar[], period: number): (number | null)[] {
  const result: (number | null)[] = []
  for (let i = 0; i < bars.length; i++) {
    if (i < period - 1) {
      result.push(null)
    } else {
      let sum = 0
      for (let j = 0; j < period; j++) {
        sum += bars[i - j].close
      }
      result.push(sum / period)
    }
  }
  return result
}

function calcBoll(
  bars: KlineBar[],
  period: number,
  multiplier: number,
): { upper: (number | null)[]; mid: (number | null)[]; lower: (number | null)[] } {
  const mid = calcMA(bars, period)
  const upper: (number | null)[] = []
  const lower: (number | null)[] = []
  for (let i = 0; i < bars.length; i++) {
    if (i < period - 1) {
      upper.push(null)
      lower.push(null)
    } else {
      const m = mid[i] as number
      let variance = 0
      for (let j = 0; j < period; j++) {
        const diff = bars[i - j].close - m
        variance += diff * diff
      }
      const std = Math.sqrt(variance / period)
      upper.push(m + multiplier * std)
      lower.push(m - multiplier * std)
    }
  }
  return { upper, mid, lower }
}

function calcDonchian(
  bars: KlineBar[],
  period: number,
): { upper: (number | null)[]; lower: (number | null)[] } {
  const upper: (number | null)[] = []
  const lower: (number | null)[] = []
  for (let i = 0; i < bars.length; i++) {
    if (i < period - 1) {
      upper.push(null)
      lower.push(null)
    } else {
      let hh = -Infinity
      let ll = Infinity
      for (let j = 0; j < period; j++) {
        hh = Math.max(hh, bars[i - j].high)
        ll = Math.min(ll, bars[i - j].low)
      }
      upper.push(hh)
      lower.push(ll)
    }
  }
  return { upper, lower }
}

function calcMACD(
  bars: KlineBar[],
  fastPeriod: number,
  slowPeriod: number,
  signalPeriod: number,
): SubIndicatorData {
  const closes = bars.map((b) => b.close)
  const emaFast = calcEMA(closes, fastPeriod)
  const emaSlow = calcEMA(closes, slowPeriod)

  const dif: (number | null)[] = []
  for (let i = 0; i < closes.length; i++) {
    if (emaFast[i] == null || emaSlow[i] == null) {
      dif.push(null)
    } else {
      dif.push((emaFast[i] as number) - (emaSlow[i] as number))
    }
  }

  const difValues = dif.map((v) => v ?? 0)
  const dea = calcEMA(difValues, signalPeriod)

  const macd: (number | null)[] = []
  for (let i = 0; i < closes.length; i++) {
    if (dif[i] == null || dea[i] == null) {
      macd.push(null)
    } else {
      macd.push(((dif[i] as number) - (dea[i] as number)) * 2)
    }
  }

  return { macd, dif, dea }
}

function calcEMA(values: number[], period: number): (number | null)[] {
  const result: (number | null)[] = []
  const multiplier = 2 / (period + 1)
  let prevEMA: number | null = null

  for (let i = 0; i < values.length; i++) {
    if (i < period - 1) {
      result.push(null)
    } else if (i === period - 1) {
      let sum = 0
      for (let j = 0; j < period; j++) {
        sum += values[i - j]
      }
      prevEMA = sum / period
      result.push(prevEMA)
    } else {
      prevEMA = values[i] * multiplier + (prevEMA as number) * (1 - multiplier)
      result.push(prevEMA)
    }
  }
  return result
}

function calcRSI(bars: KlineBar[], period: number): (number | null)[] {
  const result: (number | null)[] = []
  let avgGain = 0
  let avgLoss = 0

  for (let i = 0; i < bars.length; i++) {
    if (i === 0) {
      result.push(null)
      continue
    }
    const change = bars[i].close - bars[i - 1].close
    const gain = change > 0 ? change : 0
    const loss = change < 0 ? -change : 0

    if (i < period) {
      avgGain += gain
      avgLoss += loss
      if (i === period - 1) {
        avgGain /= period
        avgLoss /= period
        const rs = avgLoss === 0 ? 100 : avgGain / avgLoss
        result.push(100 - 100 / (1 + rs))
      } else {
        result.push(null)
      }
    } else {
      avgGain = (avgGain * (period - 1) + gain) / period
      avgLoss = (avgLoss * (period - 1) + loss) / period
      const rs = avgLoss === 0 ? 100 : avgGain / avgLoss
      result.push(100 - 100 / (1 + rs))
    }
  }
  return result
}
