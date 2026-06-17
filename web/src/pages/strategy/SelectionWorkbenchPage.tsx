import { useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import {
  Alert,
  Button,
  DatePicker,
  Empty,
  Input,
  InputNumber,
  Radio,
  Select,
  Spin,
  Table,
  Tabs,
  Tag,
  message,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import dayjs, { type Dayjs } from 'dayjs'
import * as echarts from 'echarts'
import { Download, Play } from 'lucide-react'

import {
  fetchFactors,
  fetchLatestTradeDate,
  fetchPools,
  fetchStrategies,
  runSelection,
  type Factor,
  type Pool,
  type SelectionFilterStep,
  type SelectionItem,
  type SelectionRunResponse,
  type Strategy,
  type UniverseType,
} from '@/api'
import { extractPageItems, isApiError } from '@/api/types'
import { AsyncSection } from '@/components/common/AsyncSection'
import { useRequest } from '@/hooks/useRequest'

const DEFAULT_TOP_N = 50

interface IndustryAggItem {
  industry: string
  count: number
}

function getScoreColor(score: number, min: number, max: number): string {
  if (max <= min) return 'var(--text-secondary)'
  const ratio = (score - min) / (max - min)
  if (ratio >= 0.66) return 'var(--color-rise)'
  if (ratio <= 0.33) return 'var(--color-fall)'
  return 'var(--text-secondary)'
}

function getFactorLabel(key: string, factorNameMap: Record<string, string>): string {
  const name = factorNameMap[key]
  return name ? `${name}(${key})` : key
}

function getDirectionLabel(direction: string | null | undefined, t: (key: string) => string): string {
  if (!direction) return '—'
  const key = `strategy.direction_${direction}`
  const label = t(key)
  return label === key ? direction : label
}

function exportCsv(
  items: SelectionItem[],
  factorKeys: string[],
  factorNameMap: Record<string, string>,
  filename: string,
  t: (key: string) => string,
): void {
  const header = [
    '排名',
    '代码',
    '名称',
    '收盘价',
    '涨跌幅(%)',
    '得分',
    '方向',
    '置信度',
    ...factorKeys.map((key) => getFactorLabel(key, factorNameMap)),
  ]
  const rows = items.map((item) => [
    item.rank,
    item.symbol,
    item.name,
    item.close ?? '',
    item.pct_chg ?? '',
    item.score,
    getDirectionLabel(item.direction, t),
    item.confidence ?? '',
    ...factorKeys.map((key) => item.factor_values[key] ?? ''),
  ])
  const csv = [header, ...rows]
    .map((row) =>
      row
        .map((cell) => {
          const text = String(cell)
          if (text.includes(',') || text.includes('"') || text.includes('\n')) {
            return `"${text.replace(/"/g, '""')}"`
          }
          return text
        })
        .join(','),
    )
    .join('\n')
  const blob = new Blob([`\uFEFF${csv}`], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(url)
}

interface FactorScatterChartProps {
  items: SelectionItem[]
  factorKeys: string[]
  factorNameMap: Record<string, string>
}

function FactorScatterChart({ items, factorKeys, factorNameMap }: FactorScatterChartProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<ReturnType<typeof echarts.init> | null>(null)
  const [xKey, setXKey] = useState<string | undefined>(factorKeys[0])
  const [yKey, setYKey] = useState<string | undefined>(factorKeys[1] ?? factorKeys[0])
  const { t } = useTranslation()

  useEffect(() => {
    if (factorKeys.length === 0) return
    queueMicrotask(() => {
      setXKey((cur) => (cur && factorKeys.includes(cur) ? cur : factorKeys[0]))
      setYKey((cur) => {
        if (cur && factorKeys.includes(cur)) return cur
        return factorKeys[1] ?? factorKeys[0]
      })
    })
  }, [factorKeys])

  useEffect(() => {
    if (!containerRef.current) return
    const chart = echarts.init(containerRef.current)
    chartRef.current = chart
    const observer = new ResizeObserver(() => chart.resize())
    observer.observe(containerRef.current)
    return () => {
      observer.disconnect()
      chart.dispose()
      chartRef.current = null
    }
  }, [])

  useEffect(() => {
    const chart = chartRef.current
    if (!chart) return
    if (!xKey || !yKey) {
      chart.clear()
      return
    }
    const xLabel = getFactorLabel(xKey, factorNameMap)
    const yLabel = getFactorLabel(yKey, factorNameMap)
    const scores = items.map((it) => it.score)
    const minScore = Math.min(...scores)
    const maxScore = Math.max(...scores)
    const scoreRange = Math.max(maxScore - minScore, 1e-9)
    const seriesData = items
      .map((item) => {
        const x = item.factor_values[xKey]
        const y = item.factor_values[yKey]
        if (x == null || y == null || !Number.isFinite(x) || !Number.isFinite(y)) return null
        return {
          value: [x, y, item.score],
          name: `${item.symbol} ${item.name}`,
          symbol: item.symbol,
          score: item.score,
        }
      })
      .filter((entry): entry is NonNullable<typeof entry> => entry !== null)

    chart.setOption({
      backgroundColor: 'transparent',
      tooltip: {
        trigger: 'item',
        formatter: (params: unknown) => {
          const p = params as {
            data: { name: string; value: [number, number, number]; symbol: string }
          }
          return `${p.data.name}<br/>${xLabel}: ${p.data.value[0].toFixed(4)}<br/>${yLabel}: ${p.data.value[1].toFixed(4)}<br/>score: ${p.data.value[2].toFixed(4)}`
        },
      },
      grid: { left: 50, right: 30, top: 30, bottom: 40 },
      xAxis: {
        type: 'value',
        name: xLabel,
        axisLabel: { color: '#94a3b8', fontSize: 10 },
        splitLine: { lineStyle: { color: 'rgba(148,163,184,0.15)' } },
      },
      yAxis: {
        type: 'value',
        name: yLabel,
        axisLabel: { color: '#94a3b8', fontSize: 10 },
        splitLine: { lineStyle: { color: 'rgba(148,163,184,0.15)' } },
      },
      series: [
        {
          type: 'scatter',
          data: seriesData,
          symbolSize: (value: number[]) => {
            const score = value[2]
            const normalized = (score - minScore) / scoreRange
            return 8 + normalized * 22
          },
          itemStyle: {
            color: '#1677ff',
            opacity: 0.7,
            borderColor: '#0958d9',
            borderWidth: 1,
          },
        },
      ],
    })
  }, [factorNameMap, items, xKey, yKey])

  if (factorKeys.length === 0) {
    return <Empty description={t('strategy.noFactorValues')} image={Empty.PRESENTED_IMAGE_SIMPLE} />
  }

  return (
    <div>
      <div style={{ display: 'flex', gap: 8, marginBottom: 8 }}>
        <Select
          size="small"
          style={{ width: 180 }}
          value={xKey}
          onChange={setXKey}
          options={factorKeys.map((k) => ({ label: `${t('strategy.scatterXAxis')}: ${getFactorLabel(k, factorNameMap)}`, value: k }))}
        />
        <Select
          size="small"
          style={{ width: 180 }}
          value={yKey}
          onChange={setYKey}
          options={factorKeys.map((k) => ({ label: `${t('strategy.scatterYAxis')}: ${getFactorLabel(k, factorNameMap)}`, value: k }))}
        />
      </div>
      <div ref={containerRef} className="strategy-chart" />
    </div>
  )
}

interface IndustryDistributionChartProps {
  data: IndustryAggItem[]
  loading: boolean
}

function formatFilterStepLabel(step: SelectionFilterStep, factorNameMap: Record<string, string>): string {
  if (step.step_type !== 'rule') return step.label
  const factorLabels = (step.factors ?? []).map((fid) => getFactorLabel(fid, factorNameMap)).join(', ')
  return factorLabels ? `${step.label} · ${factorLabels}` : step.label
}

interface RuleHitAnalysisChartProps {
  data: SelectionFilterStep[]
  factorNameMap: Record<string, string>
}

function RuleHitAnalysisChart({ data, factorNameMap }: RuleHitAnalysisChartProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<ReturnType<typeof echarts.init> | null>(null)
  const { t } = useTranslation()

  useEffect(() => {
    if (!containerRef.current) return
    const chart = echarts.init(containerRef.current)
    chartRef.current = chart
    const observer = new ResizeObserver(() => chart.resize())
    observer.observe(containerRef.current)
    return () => {
      observer.disconnect()
      chart.dispose()
      chartRef.current = null
    }
  }, [])

  useEffect(() => {
    const chart = chartRef.current
    if (!chart) return
    if (data.length === 0) {
      chart.clear()
      return
    }
    const chartData = data.map((step) => ({
      label: formatFilterStepLabel(step, factorNameMap),
      count: step.count,
      step,
    }))
    const sorted = [...chartData].reverse()
    chart.setOption({
      backgroundColor: 'transparent',
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'shadow' },
        formatter: (params: unknown) => {
          const list = params as Array<{ data: { step: SelectionFilterStep; count: number }; name: string }>
          const item = list[0]
          const step = item.data.step
          const desc = step.expression || step.spi_class || ''
          const meta = [
            step.weight == null ? null : `${t('strategy.weight')}: ${step.weight}`,
            step.threshold == null ? null : `${t('strategy.threshold')}: ${step.threshold}`,
            step.group_method ? `${t('strategy.combinationMethod')}: ${step.group_method}` : null,
          ].filter(Boolean).join('<br/>')
          return `${item.name}<br/>${t('strategy.filterCount')}: ${item.data.count}<br/>${t('strategy.filterPassRate')}: ${(step.pass_rate * 100).toFixed(2)}%${meta ? `<br/>${meta}` : ''}${desc ? `<br/>${desc}` : ''}`
        },
      },
      grid: { left: 150, right: 50, top: 16, bottom: 30 },
      xAxis: {
        type: 'value',
        axisLabel: { color: '#94a3b8', fontSize: 10 },
        splitLine: { lineStyle: { color: 'rgba(148,163,184,0.15)' } },
      },
      yAxis: {
        type: 'category',
        data: sorted.map((item) => item.label),
        axisLabel: {
          color: '#94a3b8',
          fontSize: 10,
          width: 140,
          overflow: 'truncate',
        },
      },
      series: [
        {
          type: 'bar',
          data: sorted.map((item) => ({ value: item.count, count: item.count, step: item.step })),
          itemStyle: {
            color: (params: unknown) => {
              const p = params as { data: { step: SelectionFilterStep } }
              if (p.data.step.step_type === 'final') return '#16a34a'
              if (p.data.step.step_type === 'group') return '#f59e0b'
              if (p.data.step.step_type === 'universe') return '#64748b'
              return '#1677ff'
            },
          },
          barMaxWidth: 18,
          label: { show: true, position: 'right', color: '#9aaabe', fontSize: 11 },
        },
      ],
    })
  }, [data, factorNameMap, t])

  if (data.length === 0) {
    return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t('strategy.noFilterStats')} />
  }

  return <div ref={containerRef} className="strategy-chart" />
}

function IndustryDistributionChart({ data, loading }: IndustryDistributionChartProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<ReturnType<typeof echarts.init> | null>(null)

  useEffect(() => {
    if (!containerRef.current) return
    const chart = echarts.init(containerRef.current)
    chartRef.current = chart
    const observer = new ResizeObserver(() => chart.resize())
    observer.observe(containerRef.current)
    return () => {
      observer.disconnect()
      chart.dispose()
      chartRef.current = null
    }
  }, [])

  useEffect(() => {
    const chart = chartRef.current
    if (!chart) return
    if (data.length === 0) {
      chart.clear()
      return
    }
    const sorted = [...data].sort((a, b) => a.count - b.count)
    chart.setOption({
      backgroundColor: 'transparent',
      tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
      grid: { left: 100, right: 30, top: 16, bottom: 30 },
      xAxis: {
        type: 'value',
        axisLabel: { color: '#94a3b8', fontSize: 10 },
        splitLine: { lineStyle: { color: 'rgba(148,163,184,0.15)' } },
      },
      yAxis: {
        type: 'category',
        data: sorted.map((d) => d.industry),
        axisLabel: { color: '#94a3b8', fontSize: 11 },
      },
      series: [
        {
          type: 'bar',
          data: sorted.map((d) => d.count),
          itemStyle: { color: '#e03e3e' },
          barMaxWidth: 18,
          label: { show: true, position: 'right', color: '#9aaabe', fontSize: 11 },
        },
      ],
    })
  }, [data])

  if (loading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', padding: 40 }}>
        <Spin />
      </div>
    )
  }

  if (data.length === 0) {
    return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} />
  }

  return <div ref={containerRef} className="strategy-chart" />
}

export function SelectionWorkbenchPage() {
  const { t } = useTranslation()
  const [strategyId, setStrategyId] = useState<string | undefined>(undefined)
  const [signalDate, setSignalDate] = useState<Dayjs>(dayjs())
  const [universeType, setUniverseType] = useState<UniverseType>('index')
  const [universeParam, setUniverseParam] = useState<string | undefined>('idx_300')
  const [customSymbols, setCustomSymbols] = useState('')
  const [topN, setTopN] = useState<number>(DEFAULT_TOP_N)
  const [result, setResult] = useState<SelectionRunResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [errorMsg, setErrorMsg] = useState<string | null>(null)
  const hasInitializedSignalDateRef = useRef(false)

  const { data: latestTradeDate } = useRequest(() => fetchLatestTradeDate())
  const { data: factorsPage } = useRequest(() => fetchFactors({ page_size: 200 }))
  const { data: strategiesPage } = useRequest(() => fetchStrategies({ status: 'active', page_size: 200 }))
  const { data: poolsData } = useRequest(() => fetchPools(true))

  const strategies = useMemo(
    () => extractPageItems<Strategy>(strategiesPage),
    [strategiesPage],
  )
  const indexPools = useMemo(
    () => (poolsData ?? []).filter((p: Pool) => p.pool_type === 'index'),
    [poolsData],
  )

  useEffect(() => {
    if (!strategyId && strategies.length > 0) {
      const firstId = strategies[0].strategy_id
      queueMicrotask(() => setStrategyId(firstId))
    }
  }, [strategies, strategyId])

  useEffect(() => {
    if (!latestTradeDate?.latest_trade_date || hasInitializedSignalDateRef.current) return
    hasInitializedSignalDateRef.current = true
    queueMicrotask(() => setSignalDate(dayjs(latestTradeDate.latest_trade_date)))
  }, [latestTradeDate])

  const factorNameMap = useMemo(() => {
    const map: Record<string, string> = { ...(result?.factor_labels ?? {}) }
    for (const factor of extractPageItems<Factor>(factorsPage)) {
      map[factor.factor_id] = map[factor.factor_id] || factor.display_name || factor.factor_id
    }
    return map
  }, [factorsPage, result])

  const items = useMemo<SelectionItem[]>(() => result?.items ?? [], [result])
  const factorKeys = useMemo(() => {
    if (items.length === 0) return []
    const seen = new Set<string>()
    for (const item of items) {
      for (const key of Object.keys(item.factor_values ?? {})) {
        seen.add(key)
      }
    }
    return Array.from(seen)
  }, [items])

  const scoreBounds = useMemo(() => {
    if (items.length === 0) return { min: 0, max: 1 }
    const scores = items.map((it) => it.score)
    return { min: Math.min(...scores), max: Math.max(...scores) }
  }, [items])

  // 行业信息已由后端在 selection/run 响应的 item.industry 字段批量返回（基于 Security.symbol__in），
  // 前端直接本地聚合，避免 N 次 /stocks/{symbol} 请求。
  const industryData = useMemo<IndustryAggItem[]>(() => {
    if (items.length === 0) return []
    const counter = new Map<string, number>()
    for (const item of items) {
      const ind = item.industry || '未知'
      counter.set(ind, (counter.get(ind) ?? 0) + 1)
    }
    return Array.from(counter.entries())
      .map(([industry, count]) => ({ industry, count }))
      .sort((a, b) => b.count - a.count)
      .slice(0, 10)
  }, [items])
  const industryLoading = false

  const handleRun = async () => {
    if (!strategyId) {
      message.warning(t('strategy.selectStrategyPlaceholder'))
      return
    }
    const payloadCustomSymbols =
      universeType === 'custom'
        ? customSymbols.split(/[\s,;]+/).map((s) => s.trim()).filter(Boolean)
        : null
    if (universeType === 'custom' && (!payloadCustomSymbols || payloadCustomSymbols.length === 0)) {
      message.warning(t('strategy.customSymbolsPlaceholder'))
      return
    }
    if (universeType === 'index' && !universeParam) {
      message.warning(t('strategy.indexPoolPlaceholder'))
      return
    }
    setLoading(true)
    setErrorMsg(null)
    try {
      const resp = await runSelection({
        strategy_id: strategyId,
        signal_date: signalDate.format('YYYY-MM-DD'),
        universe_type: universeType,
        universe_param: universeType === 'index' ? universeParam : null,
        custom_symbols: payloadCustomSymbols,
        top_n: topN,
      })
      setResult(resp)
      message.success(`${t('strategy.selectedCount')}: ${resp.selected_count}`)
    } catch (err) {
      const msg = isApiError(err)
        ? err.message
        : err instanceof Error
          ? err.message
          : t('common.loadFailed')
      setErrorMsg(msg)
      message.error(msg)
    } finally {
      setLoading(false)
    }
  }

  const columns: ColumnsType<SelectionItem> = useMemo(() => {
    const baseColumns: ColumnsType<SelectionItem> = [
      { title: t('strategy.rank'), dataIndex: 'rank', width: 64, fixed: 'left' },
      {
        title: t('strategy.symbol'),
        dataIndex: 'symbol',
        width: 110,
        fixed: 'left',
        render: (symbol: string) => (
          <Link to={`/stock/${encodeURIComponent(symbol)}`} className="strategy-table__symbol">
            {symbol}
          </Link>
        ),
      },
      { title: t('strategy.name'), dataIndex: 'name', width: 100, fixed: 'left' },
      {
        title: t('strategy.close'),
        dataIndex: 'close',
        width: 96,
        render: (value: number | null) => (value == null ? '—' : value.toFixed(2)),
        sorter: (a, b) => (a.close ?? 0) - (b.close ?? 0),
      },
      {
        title: t('strategy.pctChg'),
        dataIndex: 'pct_chg',
        width: 96,
        render: (value: number | null) => {
          if (value == null) return '—'
          const color = value > 0 ? 'var(--color-rise)' : value < 0 ? 'var(--color-fall)' : 'var(--text-secondary)'
          return <span style={{ color, fontFamily: 'var(--font-mono)' }}>{value.toFixed(2)}%</span>
        },
        sorter: (a, b) => (a.pct_chg ?? 0) - (b.pct_chg ?? 0),
      },
      {
        title: t('strategy.score'),
        dataIndex: 'score',
        width: 100,
        render: (score: number) => (
          <span style={{ color: getScoreColor(score, scoreBounds.min, scoreBounds.max), fontFamily: 'var(--font-mono)' }}>
            {score.toFixed(4)}
          </span>
        ),
        sorter: (a, b) => a.score - b.score,
        defaultSortOrder: 'descend',
      },
      {
        title: t('strategy.direction'),
        dataIndex: 'direction',
        width: 90,
        render: (dir: string | null) => (dir ? <Tag color={dir === 'long' ? 'red' : 'green'}>{getDirectionLabel(dir, t)}</Tag> : '—'),
      },
      {
        title: t('strategy.confidence'),
        dataIndex: 'confidence',
        width: 96,
        render: (c: number | null) => (c == null ? '—' : c.toFixed(3)),
      },
    ]
    const factorColumns: ColumnsType<SelectionItem> = factorKeys.map((key) => ({
      title: getFactorLabel(key, factorNameMap),
      dataIndex: ['factor_values', key],
      key: `factor_${key}`,
      width: 120,
      render: (value: number | null | undefined) =>
        value == null ? '—' : Number(value).toFixed(4),
    }))
    return [...baseColumns, ...factorColumns]
  }, [factorKeys, factorNameMap, scoreBounds, t])

  const handleExport = () => {
    if (items.length === 0) return
    const filename = `selection_${strategyId ?? 'all'}_${signalDate.format('YYYYMMDD')}.csv`
    exportCsv(items, factorKeys, factorNameMap, filename, t)
  }

  return (
    <div className="strategy-page">
      <div className="card">
        <div className="strategy-toolbar">
          <div className="strategy-toolbar__field" style={{ minWidth: 220 }}>
            <label>{t('strategy.selectStrategy')}</label>
            <Select
              value={strategyId}
              onChange={setStrategyId}
              placeholder={t('strategy.selectStrategyPlaceholder')}
              options={strategies.map((s) => ({
                label: `${s.name} (${s.strategy_id})`,
                value: s.strategy_id,
              }))}
              showSearch
              optionFilterProp="label"
            />
          </div>
          <div className="strategy-toolbar__field">
            <label>{t('strategy.signalDate')}</label>
            <DatePicker
              value={signalDate}
              onChange={(d) => {
                if (!d) return
                hasInitializedSignalDateRef.current = true
                setSignalDate(d)
              }}
              allowClear={false}
            />
          </div>
          <div className="strategy-toolbar__field" style={{ minWidth: 240 }}>
            <label>{t('strategy.universe')}</label>
            <Radio.Group
              value={universeType}
              onChange={(e) => setUniverseType(e.target.value as UniverseType)}
              optionType="button"
              buttonStyle="solid"
              size="small"
              options={[
                { label: t('strategy.universeFullMarket'), value: 'full_market' },
                { label: t('strategy.universeIndex'), value: 'index' },
                { label: t('strategy.universeCustom'), value: 'custom' },
              ]}
            />
          </div>
          {universeType === 'index' && (
            <div className="strategy-toolbar__field" style={{ minWidth: 200 }}>
              <label>&nbsp;</label>
              <Select
                value={universeParam}
                onChange={setUniverseParam}
                placeholder={t('strategy.indexPoolPlaceholder')}
                options={indexPools.map((p) => ({
                  label: `${p.pool_name} (${p.pool_id})`,
                  value: p.pool_id,
                }))}
              />
            </div>
          )}
          <div className="strategy-toolbar__field">
            <label>{t('strategy.topN')}</label>
            <InputNumber
              value={topN}
              onChange={(v) => setTopN(Math.max(1, Math.min(500, Number(v ?? DEFAULT_TOP_N))))}
              min={1}
              max={500}
              style={{ width: 100 }}
            />
          </div>
          <div className="strategy-toolbar__actions">
            <Button
              type="primary"
              icon={<Play size={14} />}
              loading={loading}
              onClick={handleRun}
            >
              {loading ? t('strategy.running') : t('strategy.run')}
            </Button>
          </div>
        </div>

        {universeType === 'custom' && (
          <div style={{ marginTop: 12 }}>
            <Input.TextArea
              rows={3}
              placeholder={t('strategy.customSymbolsPlaceholder')}
              value={customSymbols}
              onChange={(e) => setCustomSymbols(e.target.value)}
            />
          </div>
        )}

        {result && (
          <div className="strategy-stats" style={{ marginTop: 16 }}>
            <div className="strategy-stat">
              <span className="strategy-stat__label">{t('strategy.universeSize')}</span>
              <span className="strategy-stat__value">{result.universe_size}</span>
            </div>
            <div className="strategy-stat">
              <span className="strategy-stat__label">{t('strategy.selectedCount')}</span>
              <span className="strategy-stat__value">{result.selected_count}</span>
            </div>
            <div className="strategy-stat">
              <span className="strategy-stat__label">{t('strategy.elapsedMs')}</span>
              <span className="strategy-stat__value">{result.elapsed_ms}</span>
            </div>
            <div className="strategy-stat">
              <span className="strategy-stat__label">{t('strategy.avgScore')}</span>
              <span className="strategy-stat__value">
                {result.items.length === 0
                  ? '—'
                  : (
                      result.items.reduce((acc, it) => acc + it.score, 0) / result.items.length
                    ).toFixed(4)}
              </span>
            </div>
          </div>
        )}
      </div>

      {errorMsg && <Alert type="error" showIcon message={errorMsg} closable onClose={() => setErrorMsg(null)} />}

      <AsyncSection loading={loading && !result}>
        {result ? (
          <div className="strategy-workbench__main">
            <div className="card">
              <div className="card__header">
                <h3 className="card__title">{t('strategy.selectedCount')} ({items.length})</h3>
                <Button
                  size="small"
                  icon={<Download size={14} />}
                  onClick={handleExport}
                  disabled={items.length === 0}
                >
                  {t('strategy.exportCsv')}
                </Button>
              </div>
              <Table<SelectionItem>
                size="small"
                dataSource={items}
                columns={columns}
                rowKey="symbol"
                pagination={{ pageSize: 20, showTotal: (total) => `Total ${total}` }}
                scroll={{ x: 'max-content' }}
              />
            </div>
            <div className="card">
              <div className="card__header">
                <h3 className="card__title">{t('strategy.factorValues')}</h3>
              </div>
              <Tabs
                items={[
                  {
                    key: 'ruleHits',
                    label: t('strategy.ruleHitAnalysis'),
                    children: <RuleHitAnalysisChart data={result.filter_steps ?? []} factorNameMap={factorNameMap} />,
                  },
                  {
                    key: 'industry',
                    label: t('strategy.industryDistribution'),
                    children: <IndustryDistributionChart data={industryData} loading={industryLoading} />,
                  },
                  {
                    key: 'scatter',
                    label: t('strategy.factorScatter'),
                    children: <FactorScatterChart items={items} factorKeys={factorKeys} factorNameMap={factorNameMap} />,
                  },
                ]}
              />
            </div>
          </div>
        ) : (
          <div className="card strategy-empty">
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t('strategy.emptyResult')} />
          </div>
        )}
      </AsyncSection>
    </div>
  )
}
