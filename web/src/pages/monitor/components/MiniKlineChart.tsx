import { useEffect, useRef, useMemo, useState, useCallback } from 'react'
import * as echarts from 'echarts'
import type { MainIndicator, ChartPeriod, SignalItem } from '../stores/monitorStore'
import type { KlineBar, ChanlunData, Td9Data } from '../utils/klineHelpers'
import type { IndicatorData } from '../utils/indicators'

interface MiniKlineChartProps {
  symbol: string
  bars: KlineBar[]
  mainIndicators: MainIndicator[]
  isMaximized: boolean
  period: ChartPeriod
  chanlunData: ChanlunData | null
  td9Data: Td9Data | null
  /** 后端统一计算的技术指标数据 */
  indicatorData: IndicatorData | null
  signals: SignalItem[]
}

// 副图指标类型
interface SubIndicatorData {
  macd?: (number | null)[]
  dif?: (number | null)[]
  dea?: (number | null)[]
  rsi?: (number | null)[]
}

// 信号类型 -> 颜色 + 标签映射
const SIGNAL_STYLE_MAP: Record<string, { color: string; label: string }> = {
  vwap_breakthrough: { color: '#faad14', label: 'VWAP突破' },
  twap_deviation: { color: '#b37feb', label: 'TWAP偏离' },
  macd_cross: { color: '#1677ff', label: 'MACD叉' },
  rsi_extreme: { color: '#ff4d4f', label: 'RSI' },
  volume_price_divergence: { color: '#13c2c2', label: '量价' },
}

export function MiniKlineChart({
  symbol,
  bars,
  mainIndicators,
  isMaximized,
  period,
  chanlunData,
  td9Data,
  indicatorData,
  signals,
}: MiniKlineChartProps) {
  const chartRef = useRef<HTMLDivElement>(null)
  const chartInstance = useRef<echarts.ECharts | null>(null)
  const zoomStateRef = useRef<{ start: number; end: number } | null>(null)
  const [hoverIndex, setHoverIndex] = useState<number | null>(null)

  // ==================== 指标数据（后端统一计算） ====================

  const isTimesharing = period === '1m'

  // 分时图完整交易时段时间点（9:30-11:30 + 13:00-15:00，共 240 分钟）
  // 固定不变，用 useMemo 缓存避免每次 renderChart 重复生成
  const fullTimesharingTimes = useMemo(() => {
    if (!isTimesharing) return []
    const times: string[] = []
    for (let h = 9, m = 30; h < 15; ) {
      // 跳过 11:30-13:00 午休时段
      if (h === 11 && m >= 30) {
        h = 13; m = 0
        continue
      }
      times.push(`${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`)
      m += 1
      if (m >= 60) { h += 1; m = 0 }
    }
    return times
  }, [isTimesharing])

  // 指标数组对齐：后端返回的指标数组可能短于前端实时增长的 bars 数组
  // （WS minute_bar 推送新 bar 后，bars 立即增长，但 indicatorData 60s 节流重拉）
  // 不足部分用 null 填充，保证 ECharts 按 category 索引对齐时指标线不会错位
  const alignToBars = useCallback(<T,>(arr: T[] | undefined): (T | null)[] => {
    if (!arr || arr.length === 0) return []
    if (arr.length >= bars.length) return arr.slice(0, bars.length)
    const padding: (T | null)[] = new Array(bars.length - arr.length).fill(null)
    return [...arr, ...padding]
  }, [bars.length])

  // 所有指标从后端 props 获取，前端不再实现 calcXXX
  // 使用 alignToBars 确保长度与 bars 一致，避免 ECharts 索引错位
  const vwapData = useMemo(() => alignToBars(indicatorData?.vwap), [indicatorData, alignToBars])
  const twapData = useMemo(() => alignToBars(indicatorData?.twap), [indicatorData, alignToBars])
  const ma5Data = useMemo(() => mainIndicators.includes('ma') ? alignToBars(indicatorData?.ma5) : [], [mainIndicators, indicatorData, alignToBars])
  const ma20Data = useMemo(() => mainIndicators.includes('ma') ? alignToBars(indicatorData?.ma20) : [], [mainIndicators, indicatorData, alignToBars])
  const bollData = useMemo(() => {
    if (!mainIndicators.includes('boll') || !indicatorData?.boll) return null
    return {
      upper: alignToBars(indicatorData.boll.upper),
      mid: alignToBars(indicatorData.boll.mid),
      lower: alignToBars(indicatorData.boll.lower),
    }
  }, [mainIndicators, indicatorData, alignToBars])
  const donchianData = useMemo(() => {
    if (!mainIndicators.includes('donchian') || !indicatorData?.donchian) return null
    return {
      upper: alignToBars(indicatorData.donchian.upper),
      lower: alignToBars(indicatorData.donchian.lower),
    }
  }, [mainIndicators, indicatorData, alignToBars])
  const subIndicatorData = useMemo<SubIndicatorData>(() => ({
    macd: alignToBars(indicatorData?.macd?.macd),
    dif: alignToBars(indicatorData?.macd?.dif),
    dea: alignToBars(indicatorData?.macd?.dea),
    rsi: alignToBars(indicatorData?.rsi),
  }), [indicatorData, alignToBars])

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

      // 统一收集所有主图 markPoint data（信号+TD9+缠论分型），最后一次性设置到 series[0]
      // 避免多处分别设置 markPoint 导致后者覆盖前者
      type MarkPointItem = NonNullable<echarts.MarkPointComponentOption['data']>[number]
      const mainMarkPoints: MarkPointItem[] = []

      // 分时图模式：x 轴扩展为完整 9:30-15:00 交易时段（240 分钟）
      // 未产生的数据点用 null 填充，参考东方财富分时图交互：始终展示完整交易日窗口
      // fullTimesharingTimes 已用 useMemo 缓存（组件级）
      const xAxisTimes = isTimesharing ? fullTimesharingTimes : times
      const padCount = isTimesharing ? Math.max(0, fullTimesharingTimes.length - bars.length) : 0
      const padNulls = new Array(padCount).fill(null)
      const padZeros = new Array(padCount).fill(0)

      // ── 四 grid 布局：主图 + 成交量 + MACD + RSI（始终全部展示） ──
      const legendTop = isTimesharing ? (isMaximized ? 28 : 18) : (isMaximized ? 32 : 4)
      const legendTopPct = isTimesharing ? '6%' : '4%'
      const grids: echarts.GridComponentOption[] = isMaximized
        ? [
            { left: 60, right: 50, top: legendTop, height: '46%' },
            { left: 60, right: 50, top: '58%', height: '12%' },
            { left: 60, right: 50, top: '74%', height: '12%' },
            { left: 60, right: 50, top: '90%', height: '8%' },
          ]
        : [
            { left: '8%', right: '4%', top: legendTopPct, height: '46%' },
            { left: '8%', right: '4%', top: '58%', height: '12%' },
            { left: '8%', right: '4%', top: '74%', height: '12%' },
            { left: '8%', right: '4%', top: '90%', height: '8%' },
          ]

      const gridCount = grids.length
      const xAxisIndexAll = Array.from({ length: gridCount }, (_, i) => i)

      // ── X 轴 ──
      const xAxes = grids.map((_, i) => ({
        type: 'category' as const,
        data: xAxisTimes,
        gridIndex: i,
        boundaryGap: i > 0,
        axisLine: { lineStyle: { color: 'rgba(255,255,255,0.07)' } },
        axisLabel: {
          show: i === gridCount - 1,
          fontSize: isMaximized ? 11 : 9,
          color: '#5f6f85',
          // 分时图模式下显示关键时间点（9:30/11:30/13:00/15:00 等）
          // 蜡烛图模式按数据量自适应
          interval: isTimesharing
            ? (idx: number) => {
                const t = xAxisTimes[idx]
                // 显示整点、半点、9:30 和 15:00
                return t.endsWith(':00') || t.endsWith(':30')
              }
            : Math.max(0, Math.floor(times.length / (isMaximized ? 8 : 4)) - 1),
        },
      }))

      // ── Y 轴（4 个：主图 + 成交量 + MACD + RSI） ──
      const yAxes = grids.map((_, i) => {
        const isVolAxis = i === 1
        const isRsiAxis = i === 3
        const isMainAxis = i === 0
        return {
          scale: isMainAxis,
          gridIndex: i,
          splitLine: {
            show: isMainAxis,
            lineStyle: { color: 'rgba(255,255,255,0.12)' },
          },
          axisLabel: {
            show: isMaximized || isMainAxis,
            fontSize: isMaximized ? 11 : 9,
            color: '#5f6f85',
            formatter: isVolAxis
              ? (v: number) => (v >= 1e4 ? `${(v / 1e4).toFixed(0)}万` : v.toFixed(0))
              : isRsiAxis
                ? '{value}'
                : undefined,
          },
          splitNumber: isVolAxis ? 2 : undefined,
          min: isVolAxis ? 0 : isRsiAxis ? 0 : undefined,
          max: isRsiAxis ? 100 : undefined,
        }
      })

      // ── 系列 ──
      const series: echarts.SeriesOption[] = []

      if (isTimesharing) {
        // 分时图模式：价格折线 + VWAP + TWAP + 昨收虚线 + 渐变面积
        // 数据末尾补 null 对齐到完整 9:30-15:00 时间窗口
        const closes = [...bars.map((b) => b.close), ...padNulls]
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
            lineStyle: { color: 'rgba(154,170,190,0.5)', width: 1, type: 'dotted' },
            label: {
              show: isMaximized,
              position: 'end',
              formatter: '昨收',
              color: 'rgba(154,170,190,0.8)',
              fontSize: 9,
            },
            data: [{ yAxis: refPrice }],
          },
        })
        // VWAP 均价线（橙色实线）- 末尾补 null
        if (vwapData.length > 0) {
          series.push({
            name: 'VWAP',
            type: 'line',
            data: [...vwapData, ...padNulls],
            xAxisIndex: 0,
            yAxisIndex: 0,
            symbol: 'none',
            lineStyle: { color: '#faad14', width: 1.5 },
          })
        }
        // TWAP 线（紫色长虚线）- 末尾补 null
        if (twapData.length > 0) {
          series.push({
            name: 'TWAP',
            type: 'line',
            data: [...twapData, ...padNulls],
            xAxisIndex: 0,
            yAxisIndex: 0,
            symbol: 'none',
            lineStyle: { color: '#b37feb', width: 1.2, type: [6, 4] },
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

      // 信号 markPoint：5 类核心信号触发位置标记在主图上
      // trade_time 为后端 signal_engine 推送的 ISO 字符串（Shanghai 时区，如 "2026-07-13T10:32:00+08:00"）
      // 1m 周期：精确匹配 bar.time === HH:MM
      // 5m/15m 周期：信号触发于 1m bar，但图表 bar 为聚合后的 N 分钟 bar，
      //   需将信号时间映射到包含该时刻的 N 分钟 bar（bar.time <= 信号时间 < bar.time + N 分钟）
      if (signals.length > 0 && series.length > 0) {
        const periodMinutes = period === '1m' ? 1 : period === '5m' ? 5 : period === '15m' ? 15 : 0
        // MarkPointDataItemOption 未在 echarts 命名空间导出，使用类型推导
        const signalMarks: NonNullable<echarts.MarkPointComponentOption['data']>[number][] = []
        for (const sig of signals) {
          // 从 ISO 字符串提取 HH:MM（无论 REST 还是 WS 来源）
          const isoTime = sig.trade_time ?? null
          if (!isoTime) continue
          const m = isoTime.match(/T(\d{2}):(\d{2})/)
          if (!m) continue
          const sigMinutes = parseInt(m[1], 10) * 60 + parseInt(m[2], 10)

          // 查找匹配的 bar 索引
          let idx = -1
          if (periodMinutes === 1) {
            // 1m：精确匹配 HH:MM
            const hhmm = `${m[1]}:${m[2]}`
            idx = bars.findIndex((b) => b.time === hhmm)
          } else if (periodMinutes > 0) {
            // 5m/15m：时间范围匹配
            idx = bars.findIndex((b) => {
              const [bh, bm] = b.time.split(':').map((x) => parseInt(x, 10))
              if (Number.isNaN(bh) || Number.isNaN(bm)) return false
              const barMinutes = bh * 60 + bm
              return sigMinutes >= barMinutes && sigMinutes < barMinutes + periodMinutes
            })
          }
          if (idx === -1) continue

          const style = SIGNAL_STYLE_MAP[sig.signal_type ?? '']
          const color = style?.color ?? '#999'
          const label = style?.label ?? sig.signal_type ?? '信号'
          const isLong = sig.direction === 'long'
          signalMarks.push({
            name: label,
            coord: [idx, bars[idx].close],
            symbol: isLong ? 'triangle' : 'pin',
            symbolSize: isMaximized ? 14 : 10,
            itemStyle: { color },
            label: {
              show: isMaximized,
              formatter: label,
              color: '#fff',
              fontSize: 9,
              position: isLong ? 'bottom' : 'top',
            },
          })
        }
        if (signalMarks.length > 0) {
          mainMarkPoints.push(...signalMarks)
        }
      }

      // 主图指标：分时均线（VWAP）- 仅蜡烛图模式
      if (!isTimesharing && mainIndicators.includes('vwap') && vwapData.length > 0) {
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
      if (mainIndicators.includes('ma')) {
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
      if (mainIndicators.includes('boll') && bollData) {
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
      if (mainIndicators.includes('donchian') && donchianData) {
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
      if (mainIndicators.includes('td9') && td9Data) {
        const td9MarkPoints: MarkPointItem[] = []
        for (let i = 0; i < td9Data.buy_setup.length; i++) {
          const buyVal = td9Data.buy_setup[i]
          const sellVal = td9Data.sell_setup[i]
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
        // 收集到 mainMarkPoints，统一设置避免覆盖信号 markPoint
        if (td9MarkPoints.length > 0) {
          mainMarkPoints.push(...td9MarkPoints)
        }
      }

      // 主图指标：缠论（笔用 markLine，中枢用矩形 markArea，分型用 markPoint）
      if (mainIndicators.includes('chanlun') && chanlunData) {
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
        // 3. 分型：用 markPoint 标注顶底分型（收集到 mainMarkPoints，最后统一设置避免覆盖信号/TD9）
        if (chanlunData.fractals.length > 0) {
          const fractalPoints: MarkPointItem[] = chanlunData.fractals.map((f) => ({
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
          mainMarkPoints.push(...fractalPoints)
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

      // 统一设置主图 markPoint：将信号 + TD9 + 缠论分型的 markPoint 合并到 series[0]
      // 避免各部分分别设置 markPoint 导致后者覆盖前者
      if (mainMarkPoints.length > 0 && series[0]) {
        const mainSeries = series[0] as { markPoint?: echarts.MarkPointComponentOption }
        mainSeries.markPoint = {
          data: mainMarkPoints,
          animation: false,
        }
      }

      // 成交量（始终在 grid[1]）
      // 分时图模式下末尾补 0 对齐到完整时间窗口
      series.push({
        name: 'Volume',
        type: 'bar',
        data: [...volumes.map((v, i) => ({
          value: v,
          itemStyle: { color: volColors[i] },
        })), ...(isTimesharing ? padZeros.map(() => ({ value: 0, itemStyle: { color: '#2eaa67' } })) : [])],
        xAxisIndex: 1,
        yAxisIndex: 1,
        barMaxWidth: isMaximized ? 8 : 4,
      })

      // 副图指标：MACD（grid[2]）— 仅蜡烛图模式且有副图指标时
      // 副图指标：MACD（grid[2]，始终展示）
      if (subIndicatorData.macd) {
        const macdAxis = 2
        series.push({
          name: 'MACD',
          type: 'bar',
          data: [...subIndicatorData.macd.map((v) => v ?? 0), ...(isTimesharing ? padZeros : [])],
          xAxisIndex: macdAxis,
          yAxisIndex: macdAxis,
          barMaxWidth: isMaximized ? 6 : 3,
          itemStyle: {
            color: (p: { data: number }) => (p.data >= 0 ? '#e03e3e' : '#2eaa67'),
          },
        })
        if (subIndicatorData.dif) {
          series.push({
            name: 'DIF',
            type: 'line',
            data: [...subIndicatorData.dif, ...padNulls],
            xAxisIndex: macdAxis,
            yAxisIndex: macdAxis,
            symbol: 'none',
            lineStyle: { color: '#faad14', width: 1 },
          })
        }
        if (subIndicatorData.dea) {
          series.push({
            name: 'DEA',
            type: 'line',
            data: [...subIndicatorData.dea, ...padNulls],
            xAxisIndex: macdAxis,
            yAxisIndex: macdAxis,
            symbol: 'none',
            lineStyle: { color: '#1677ff', width: 1 },
          })
        }
      }

      // 副图指标：RSI（grid[2]）— 仅蜡烛图模式且有副图指标时
      if (subIndicatorData.rsi) {
        const rsiAxis = 3
        series.push({
          name: 'RSI',
          type: 'line',
          data: [...subIndicatorData.rsi, ...padNulls],
          xAxisIndex: rsiAxis,
          yAxisIndex: rsiAxis,
          symbol: 'none',
          lineStyle: { color: '#b37feb', width: 1.2 },
        })
        // RSI 超买超卖参考线（70/30）- 分时图模式下补齐到完整时间窗口
        const refLinePadding = isTimesharing ? padNulls : []
        series.push({
          name: 'RSI_Overbought',
          type: 'line',
          data: [...bars.map(() => 70), ...refLinePadding],
          xAxisIndex: rsiAxis,
          yAxisIndex: rsiAxis,
          symbol: 'none',
          lineStyle: { color: 'rgba(224,62,62,0.3)', width: 1, type: 'dashed' },
          silent: true,
        } as echarts.SeriesOption)
        series.push({
          name: 'RSI_Oversold',
          type: 'line',
          data: [...bars.map(() => 30), ...refLinePadding],
          xAxisIndex: rsiAxis,
          yAxisIndex: rsiAxis,
          symbol: 'none',
          lineStyle: { color: 'rgba(46,170,103,0.3)', width: 1, type: 'dashed' },
          silent: true,
        } as echarts.SeriesOption)
      }

      // ── 保留用户缩放状态 ──
      const preservedZoom = zoomStateRef.current

      const option: echarts.EChartsCoreOption = {
        backgroundColor: 'transparent',
        animation: false,
        tooltip: {
          show: true,
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
        legend: {
          show: isTimesharing,
          top: isMaximized ? 8 : 2,
          right: isMaximized ? 60 : '4%',
          textStyle: { color: '#9ca3af', fontSize: isMaximized ? 11 : 9 },
          itemWidth: isMaximized ? 16 : 12,
          itemHeight: isMaximized ? 8 : 6,
          itemGap: 12,
          data: ['价格', 'VWAP', 'TWAP'],
        },
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
  }, [bars, symbol, mainIndicators, isMaximized, isTimesharing, period, vwapData, twapData, ma5Data, ma20Data, bollData, donchianData, td9Data, chanlunData, subIndicatorData, signals, indicatorData, fullTimesharingTimes])

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

  // ── 副图指标数值（业界主流机构配色） ──
  const macdVal = subIndicatorData.macd?.[currentIndex] ?? null
  const difVal = subIndicatorData.dif?.[currentIndex] ?? null
  const deaVal = subIndicatorData.dea?.[currentIndex] ?? null
  const rsiVal = subIndicatorData.rsi?.[currentIndex] ?? null
  const macdColor = macdVal != null && macdVal >= 0 ? '#e03e3e' : '#2eaa67'

  const subLabelFontSize = isMaximized ? 11 : 9
  const subLabelLeft = isMaximized ? 64 : '9%'

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
              <span>价格 <span style={{ color: '#60a5fa' }}>{formatBarValue(currentBar.close)}</span></span>
              <span>VWAP <span style={{ color: '#faad14' }}>{formatBarValue(vwapData[currentIndex] ?? null)}</span></span>
              <span>TWAP <span style={{ color: '#b37feb' }}>{formatBarValue(twapData[currentIndex] ?? null)}</span></span>
              <span>量 {formatVolume(currentBar.volume)}</span>
            </>
          ) : (
            <>
              <span>开 {formatBarValue(currentBar.open)}</span>
              <span>高 <span style={{ color: '#e03e3e' }}>{formatBarValue(currentBar.high)}</span></span>
              <span>低 <span style={{ color: '#2eaa67' }}>{formatBarValue(currentBar.low)}</span></span>
              <span>收 {formatBarValue(currentBar.close)}</span>
              <span>量 {formatVolume(currentBar.volume)}</span>
            </>
          )}
        </div>
      )}
      <div style={{ position: 'relative', width: '100%', flex: 1 }}>
        <div ref={chartRef} className="monitor-cell__chart-inner" style={{ width: '100%', height: '100%' }} />
        {subIndicatorData.macd && (
          <div style={{
            position: 'absolute',
            left: subLabelLeft,
            top: '74.5%',
            fontSize: subLabelFontSize,
            fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
            pointerEvents: 'none',
            lineHeight: 1.2,
            whiteSpace: 'nowrap',
          }}>
            <span style={{ color: macdColor }}>MACD {formatBarValue(macdVal, 3)}</span>
            <span style={{ marginLeft: 8, color: '#faad14' }}>DIF {formatBarValue(difVal, 3)}</span>
            <span style={{ marginLeft: 8, color: '#1677ff' }}>DEA {formatBarValue(deaVal, 3)}</span>
          </div>
        )}
        {subIndicatorData.rsi && (
          <div style={{
            position: 'absolute',
            left: subLabelLeft,
            top: '90.5%',
            fontSize: subLabelFontSize,
            fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
            pointerEvents: 'none',
            lineHeight: 1.2,
            whiteSpace: 'nowrap',
          }}>
            <span style={{ color: '#b37feb' }}>RSI(14) {formatBarValue(rsiVal, 2)}</span>
          </div>
        )}
      </div>
    </div>
  )
}
