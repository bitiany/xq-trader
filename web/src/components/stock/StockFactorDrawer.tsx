import { useEffect, useMemo, useRef, useState } from 'react'
import { Drawer, Empty, Spin, Table, Tabs, Tag } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import * as echarts from 'echarts'

import { fetchStockFactorSeries, type FactorMeta, type FactorSeriesResponse } from '@/api/stock'

interface StockFactorDrawerProps {
  open: boolean
  symbol: string
  stockName?: string
  onClose: () => void
}

// category 中文映射
const CATEGORY_LABELS: Record<string, string> = {
  value: '价值',
  momentum: '动量',
  volatility: '波动率',
  tech_volatility: '波动率',
  liquidity: '流动性',
  risk: '风险',
  fund_flow: '资金流',
  technical: '技术',
  tech_oscillator: '技术',
  tech_trend: '技术',
  tech_ma: '技术',
  fundamental: '基本面',
  fundamental_quality: '基本面',
  fundamental_profitability: '基本面',
  fundamental_leverage: '基本面',
  fundamental_growth: '基本面',
  candle_pattern: 'K线形态',
  chanlun: '缠论',
  alpha101: 'Alpha量价',
  alpha158: 'Alpha量价',
  composite_group: '组内合成',
  composite_cross: '跨组合成',
  interaction: '交互因子',
  return: '收益率',
}

function getCategoryLabel(category: string): string {
  return CATEGORY_LABELS[category] ?? category
}

function formatFactorValue(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return '—'
  return value.toFixed(3)
}

function formatStats(value: number | null | undefined, digits = 3): string {
  if (value == null || Number.isNaN(value)) return '—'
  return value.toFixed(digits)
}

interface FactorRow {
  key: string
  factor: FactorMeta
  values: Array<{ date: string; value: number | null }>
}

function FactorHeatmap({ rows }: { rows: FactorRow[] }) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const chartRef = useRef<echarts.ECharts | null>(null)

  useEffect(() => {
    if (!containerRef.current || rows.length === 0) return
    if (!chartRef.current) {
      chartRef.current = echarts.init(containerRef.current)
    }
    const chart = chartRef.current

    const dates = rows[0]?.values.map((v) => v.date) ?? []
    const heatmapData: Array<[number, number, number | null]> = []
    rows.forEach((row, yIdx) => {
      row.values.forEach((cell, xIdx) => {
        heatmapData.push([xIdx, yIdx, cell.value])
      })
    })

    const yLabels = rows.map((r) => r.factor.display_name || r.factor.factor_id)

    chart.setOption({
      tooltip: {
        position: 'top',
        formatter: (params: { value: [number, number, number | null]; data: [number, number, number | null] }) => {
          const [x, y, val] = params.data
          return `${yLabels[y]}<br/>${dates[x]}: ${val == null ? '—' : val.toFixed(3)}`
        },
      },
      grid: { left: 120, right: 20, top: 10, bottom: 30 },
      xAxis: {
        type: 'category',
        data: dates,
        splitArea: { show: true },
        axisLabel: { color: '#9ca3af', fontSize: 11, formatter: (v: string) => v.slice(5) },
      },
      yAxis: {
        type: 'category',
        data: yLabels,
        splitArea: { show: true },
        axisLabel: { color: '#cbd5e1', fontSize: 11 },
        inverse: true,
      },
      visualMap: {
        min: -2,
        max: 2,
        calculable: false,
        orient: 'horizontal',
        left: 'center',
        bottom: 0,
        // 柔和色调：深青→深灰→深红，避免刺眼
        inRange: { color: ['#1a4d4a', '#1e293b', '#4d1a1a'] },
        textStyle: { color: '#9ca3af' },
        show: false,
      },
      series: [
        {
          type: 'heatmap',
          data: heatmapData,
          // 每个单元格增加边框，区分不同指标值
          itemStyle: {
            borderWidth: 1,
            borderColor: 'rgba(30, 41, 59, 0.6)',
          },
          label: {
            show: rows.length <= 15,
            color: '#e2e8f0',
            fontSize: 9,
            // 文字阴影确保在任意背景色上可读
            textShadow: '0 0 3px rgba(0,0,0,0.8)',
            formatter: (p: { data: [number, number, number | null] }) => {
              const val = p.data[2]
              return val == null ? '' : val.toFixed(2)
            },
          },
          emphasis: { itemStyle: { borderColor: '#fff', borderWidth: 1.5 } },
        },
      ],
    })
    chart.resize()
  }, [rows])

  useEffect(() => {
    return () => {
      chartRef.current?.dispose()
      chartRef.current = null
    }
  }, [])

  if (rows.length === 0) return null
  return <div ref={containerRef} style={{ width: '100%', height: Math.max(200, rows.length * 28 + 40) }} />
}

function FactorTable({ rows }: { rows: FactorRow[] }) {
  const dateColumns: ColumnsType<FactorRow> = useMemo(() => {
    const dates = rows[0]?.values.map((v) => v.date) ?? []
    return dates.map((date) => ({
      title: date.slice(5),
      key: date,
      width: 80,
      align: 'right' as const,
      render: (_, record) => {
        const cell = record.values.find((v) => v.date === date)
        const val = cell?.value
        // 只用文字色区分正负，不加背景色，确保数字清晰可读
        return (
          <span
            style={{
              fontFamily: 'var(--font-mono)',
              color: val == null ? 'var(--text-tertiary)' : val > 0 ? 'var(--color-rise)' : val < 0 ? 'var(--color-fall)' : 'var(--text-secondary)',
            }}
          >
            {formatFactorValue(val)}
          </span>
        )
      },
    }))
  }, [rows])

  const columns: ColumnsType<FactorRow> = useMemo(
    () => [
      {
        title: '因子',
        key: 'factor_name',
        width: 160,
        fixed: 'left',
        render: (_, record) => (
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <span>{record.factor.display_name || record.factor.factor_id}</span>
            {record.factor.is_composite && <Tag color="purple" style={{ margin: 0, fontSize: 10 }}>合成</Tag>}
            {record.factor.factor_grade && (
              <Tag
                color={record.factor.factor_grade === 'A' ? 'green' : record.factor.factor_grade === 'B' ? 'blue' : 'default'}
                style={{ margin: 0, fontSize: 10 }}
              >
                {record.factor.factor_grade}
              </Tag>
            )}
          </div>
        ),
      },
      ...dateColumns,
      {
        title: 'IC',
        key: 'ic_mean',
        width: 70,
        align: 'right' as const,
        render: (_, record) => {
          const ic = record.factor.latest_stats?.ic_mean
          return <span style={{ fontFamily: 'var(--font-mono)' }}>{formatStats(ic, 4)}</span>
        },
      },
      {
        title: 'ICIR',
        key: 'icir',
        width: 70,
        align: 'right' as const,
        render: (_, record) => {
          const icir = record.factor.latest_stats?.icir
          return (
            <span
              style={{
                fontFamily: 'var(--font-mono)',
                color: icir == null ? undefined : icir > 0.5 ? 'var(--color-rise)' : icir < -0.5 ? 'var(--color-fall)' : undefined,
              }}
            >
              {formatStats(icir, 2)}
            </span>
          )
        },
      },
      {
        title: '胜率',
        key: 'ic_win_rate',
        width: 70,
        align: 'right' as const,
        render: (_, record) => {
          const winRate = record.factor.latest_stats?.ic_win_rate
          return <span style={{ fontFamily: 'var(--font-mono)' }}>{formatStats(winRate != null ? winRate * 100 : null, 1)}%</span>
        },
      },
      {
        title: '换手',
        key: 'turnover',
        width: 70,
        align: 'right' as const,
        render: (_, record) => {
          const turnover = record.factor.latest_stats?.turnover
          return <span style={{ fontFamily: 'var(--font-mono)' }}>{formatStats(turnover, 2)}</span>
        },
      },
    ],
    [dateColumns],
  )

  return (
    <Table<FactorRow>
      columns={columns}
      dataSource={rows}
      pagination={false}
      size="small"
      scroll={{ x: 'max-content', y: 400 }}
      rowKey="key"
    />
  )
}

export function StockFactorDrawer({ open, symbol, stockName, onClose }: StockFactorDrawerProps) {
  const [loading, setLoading] = useState(false)
  const [data, setData] = useState<FactorSeriesResponse | null>(null)
  const [activeCategory, setActiveCategory] = useState<string>('')

  useEffect(() => {
    if (!open || !symbol) return
    let cancelled = false
    setLoading(true)
    setData(null)
    fetchStockFactorSeries(symbol, 10)
      .then((resp) => {
        if (cancelled) return
        setData(resp)
        // 默认选中第一个 category
        const categories = groupByCategory(resp.factors)
        if (categories.length > 0) {
          setActiveCategory(categories[0].category)
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [open, symbol])

  // 按 category 分组
  const categoryGroups = useMemo(() => {
    if (!data) return []
    return groupByCategory(data.factors)
  }, [data])

  // 当前 category 的因子行（含日期值）
  const currentRows: FactorRow[] = useMemo(() => {
    if (!data) return []
    const dates = data.rows.map((r) => r.trade_date as string).sort().reverse()
    const factorsInCategory = data.factors.filter((f) => f.category === activeCategory)
    return factorsInCategory.map((factor) => ({
      key: factor.factor_id,
      factor,
      values: dates.map((date) => {
        const row = data.rows.find((r) => r.trade_date === date)
        const value = row?.[factor.factor_id]
        return { date, value: typeof value === 'number' ? value : null }
      }),
    }))
  }, [data, activeCategory])

  return (
    <Drawer
      title={`截面因子 — ${symbol}${stockName ? `（${stockName}）` : ''}`}
      open={open}
      onClose={onClose}
      width="80%"
      styles={{ body: { padding: 16 } }}
    >
      {loading ? (
        <div style={{ textAlign: 'center', padding: 60 }}>
          <Spin size="large" />
        </div>
      ) : !data || data.rows.length === 0 ? (
        <Empty description="暂无因子数据" />
      ) : (
        <>
          <div style={{ marginBottom: 8, color: 'var(--text-secondary)', fontSize: 13 }}>
            共 {data.factor_count} 个因子，{data.rows.length} 个交易日（{data.start_date} ~ {data.end_date}）
          </div>
          <Tabs
            activeKey={activeCategory}
            onChange={setActiveCategory}
            items={categoryGroups.map((group) => ({
              key: group.category,
              label: `${getCategoryLabel(group.category)} (${group.count})`,
              children:
                currentRows.length === 0 ? (
                  <Empty description="该分类暂无因子" />
                ) : (
                  <div>
                    <div style={{ marginBottom: 12 }}>
                      <div style={{ color: 'var(--text-secondary)', fontSize: 12, marginBottom: 4 }}>因子值热力图（Z-score，红高绿低）</div>
                      <FactorHeatmap rows={currentRows} />
                    </div>
                    <div style={{ marginTop: 16 }}>
                      <div style={{ color: 'var(--text-secondary)', fontSize: 12, marginBottom: 8 }}>因子明细表</div>
                      <FactorTable rows={currentRows} />
                    </div>
                  </div>
                ),
            }))}
          />
        </>
      )}
    </Drawer>
  )
}

interface CategoryGroup {
  category: string
  count: number
}

function groupByCategory(factors: FactorMeta[]): CategoryGroup[] {
  const bucket: Record<string, number> = {}
  for (const f of factors) {
    bucket[f.category] = (bucket[f.category] ?? 0) + 1
  }
  return Object.entries(bucket)
    .map(([category, count]) => ({ category, count }))
    .sort((a, b) => b.count - a.count)
}
