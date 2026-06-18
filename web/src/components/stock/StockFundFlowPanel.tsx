import { useEffect, useRef } from 'react'
import { Empty, Table } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import * as echarts from 'echarts'
import { useTranslation } from 'react-i18next'

import type { StockFundFlowItem, StockFundFlowResponse } from '@/api/stock'

interface StockFundFlowPanelProps {
  data?: StockFundFlowResponse
}

function formatNumber(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return '—'
  if (Math.abs(value) >= 1e8) return `${(value / 1e8).toFixed(2)}亿`
  if (Math.abs(value) >= 1e4) return `${(value / 1e4).toFixed(2)}万`
  return value.toFixed(2)
}

function formatPercent(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return '—'
  return `${value.toFixed(2)}%`
}

function TrendValue({ value, percent = false }: { value: number | null | undefined; percent?: boolean }) {
  const color = value == null ? undefined : value > 0 ? 'var(--color-rise)' : value < 0 ? 'var(--color-fall)' : undefined
  return <span style={{ color, fontFamily: 'var(--font-mono)' }}>{percent ? formatPercent(value) : formatNumber(value)}</span>
}

function FundFlowPieChart({ item }: { item: StockFundFlowItem }) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const chartRef = useRef<echarts.ECharts | null>(null)
  const { t } = useTranslation()

  useEffect(() => {
    if (!containerRef.current) return
    if (!chartRef.current) {
      chartRef.current = echarts.init(containerRef.current)
    }
    const categories = [
      { key: 'huge', value: item.huge_net_amt, label: t('stock.fundFlow.hugeNetAmt'), inflowColor: '#ef5350', outflowColor: '#26a69a' },
      { key: 'big', value: item.big_net_amt, label: t('stock.fundFlow.bigNetAmt'), inflowColor: '#ff9800', outflowColor: '#66bb6a' },
      { key: 'mid', value: item.mid_net_amt, label: t('stock.fundFlow.midNetAmt'), inflowColor: '#2196f3', outflowColor: '#90caf9' },
      { key: 'small', value: item.small_net_amt, label: t('stock.fundFlow.smallNetAmt'), inflowColor: '#9c27b0', outflowColor: '#ce93d8' },
    ]
    const data = categories
      .filter((c) => c.value != null && c.value !== 0)
      .map((c) => ({
        value: Math.abs(c.value!),
        name: `${c.label} ${c.value! > 0 ? '↑' : '↓'}`,
        itemStyle: { color: c.value! > 0 ? c.inflowColor : c.outflowColor },
      }))
    const total = data.reduce((s, d) => s + d.value, 0)
    chartRef.current.setOption({
      tooltip: {
        trigger: 'item',
        valueFormatter: (v: number) => formatNumber(v),
      },
      legend: {
        bottom: 0,
        textStyle: { color: '#cbd5e1', fontSize: 11 },
        itemWidth: 10,
        itemHeight: 10,
      },
      series: [
        {
          type: 'pie',
          radius: ['35%', '65%'],
          center: ['50%', '45%'],
          avoidLabelOverlap: true,
          label: {
            show: true,
            color: '#cbd5e1',
            fontSize: 11,
            formatter: (p: { name: string; percent: number }) => `${p.name} ${p.percent.toFixed(1)}%`,
          },
          data: total > 0 ? data : [],
        },
      ],
    })
  }, [item, t])

  useEffect(() => {
    const container = containerRef.current
    const handleResize = () => chartRef.current?.resize()
    window.addEventListener('resize', handleResize)
    const observer = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(handleResize) : null
    observer?.observe(container!)
    return () => {
      window.removeEventListener('resize', handleResize)
      observer?.disconnect()
    }
  }, [])

  useEffect(() => {
    return () => {
      chartRef.current?.dispose()
      chartRef.current = null
    }
  }, [])

  return <div ref={containerRef} style={{ width: '100%', height: 260 }} />
}

function FundFlowLineChart({ items }: { items: StockFundFlowItem[] }) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const chartRef = useRef<echarts.ECharts | null>(null)

  useEffect(() => {
    if (!containerRef.current) return
    if (!chartRef.current) {
      chartRef.current = echarts.init(containerRef.current)
    }
    const dates = items.map((i) => i.trade_date.slice(5))
    const mainNet = items.map((i) => i.main_net_amt ?? 0)
    const hugeNet = items.map((i) => i.huge_net_amt ?? 0)
    const bigNet = items.map((i) => i.big_net_amt ?? 0)
    const midNet = items.map((i) => i.mid_net_amt ?? 0)
    const smallNet = items.map((i) => i.small_net_amt ?? 0)
    chartRef.current.setOption({
      tooltip: {
        trigger: 'axis',
        valueFormatter: (v: unknown) => (typeof v === 'number' ? formatNumber(v) : '--'),
      },
      legend: {
        top: 0,
        textStyle: { color: '#cbd5e1', fontSize: 11 },
        itemWidth: 14,
        itemHeight: 2,
      },
      grid: { left: 56, right: 16, top: 32, bottom: 28 },
      xAxis: {
        type: 'category',
        data: dates,
        axisLabel: { color: '#9ca3af', fontSize: 10 },
        axisLine: { lineStyle: { color: '#4b5563' } },
      },
      yAxis: {
        type: 'value',
        axisLabel: {
          color: '#9ca3af',
          fontSize: 10,
          formatter: (v: number) => formatNumber(v),
        },
        splitLine: { lineStyle: { color: 'rgba(148,163,184,0.12)' } },
      },
      series: [
        {
          name: '主力净流入',
          type: 'line',
          data: mainNet,
          showSymbol: false,
          lineStyle: { width: 1.5, color: '#f5a623' },
          areaStyle: { color: 'rgba(245,166,35,0.15)' },
        },
        {
          name: '超大单',
          type: 'line',
          data: hugeNet,
          showSymbol: false,
          lineStyle: { width: 1, color: '#ef5350' },
        },
        {
          name: '大单',
          type: 'line',
          data: bigNet,
          showSymbol: false,
          lineStyle: { width: 1, color: '#ff9800' },
        },
        {
          name: '中单',
          type: 'line',
          data: midNet,
          showSymbol: false,
          lineStyle: { width: 1, color: '#2196f3' },
        },
        {
          name: '小单',
          type: 'line',
          data: smallNet,
          showSymbol: false,
          lineStyle: { width: 1, color: '#4caf50' },
        },
      ],
    })
  }, [items])

  useEffect(() => {
    const container = containerRef.current
    const handleResize = () => chartRef.current?.resize()
    window.addEventListener('resize', handleResize)
    const observer = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(handleResize) : null
    observer?.observe(container!)
    return () => {
      window.removeEventListener('resize', handleResize)
      observer?.disconnect()
    }
  }, [])

  useEffect(() => {
    return () => {
      chartRef.current?.dispose()
      chartRef.current = null
    }
  }, [])

  return <div ref={containerRef} style={{ width: '100%', height: 280 }} />
}

export function StockFundFlowPanel({ data }: StockFundFlowPanelProps) {
  const { t } = useTranslation()
  const rows = data?.items ?? []

  if (rows.length === 0) {
    return (
      <div className="stock-panel card">
        <Empty description={t('stock.fundFlow.empty')} />
      </div>
    )
  }

  const latestItem = rows[rows.length - 1]
  // 趋势图默认展示最新120条数据
  const chartItems = rows.slice(-120)

  const columns: ColumnsType<StockFundFlowItem> = [
    { title: t('stock.fundFlow.tradeDate'), dataIndex: 'trade_date', width: 110, fixed: 'left' },
    { title: t('stock.fundFlow.mainNetAmt'), dataIndex: 'main_net_amt', width: 120, render: (v) => <TrendValue value={v} /> },
    { title: t('stock.fundFlow.mainNetPct'), dataIndex: 'main_net_pct', width: 110, render: (v) => <TrendValue value={v} percent /> },
    { title: t('stock.fundFlow.hugeNetAmt'), dataIndex: 'huge_net_amt', width: 120, render: (v) => <TrendValue value={v} /> },
    { title: t('stock.fundFlow.bigNetAmt'), dataIndex: 'big_net_amt', width: 120, render: (v) => <TrendValue value={v} /> },
    { title: t('stock.fundFlow.midNetAmt'), dataIndex: 'mid_net_amt', width: 120, render: (v) => <TrendValue value={v} /> },
    { title: t('stock.fundFlow.smallNetAmt'), dataIndex: 'small_net_amt', width: 120, render: (v) => <TrendValue value={v} /> },
  ]

  return (
    <div className="stock-panel card">
      <div className="stock-fundflow-charts">
        <div className="stock-fundflow-pie">
          <div className="stock-fundflow-section-title">{t('stock.fundFlow.todayFlow')} ({latestItem.trade_date})</div>
          <FundFlowPieChart item={latestItem} />
        </div>
        <div className="stock-fundflow-line">
          <div className="stock-fundflow-section-title">{t('stock.fundFlow.flowTrend')}</div>
          <FundFlowLineChart items={chartItems} />
        </div>
      </div>
      <Table<StockFundFlowItem>
        size="small"
        rowKey="trade_date"
        dataSource={chartItems}
        columns={columns}
        pagination={{ pageSize: 20 }}
        scroll={{ x: 'max-content' }}
      />
    </div>
  )
}
