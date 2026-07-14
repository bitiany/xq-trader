import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { App, Button, Empty, Select, Space, Table, Tag } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { Play, Search } from 'lucide-react'

import {
  fetchSelectionDates,
  fetchSelectionResults,
  fetchStrategies,
  type SelectionResult,
  type Strategy,
} from '@/api'
import { extractPageItems, isApiError } from '@/api/types'
import { AsyncSection } from '@/components/common/AsyncSection'
import { useRequest } from '@/hooks/useRequest'
import { useRequestErrorToast } from '@/hooks/useRequestErrorToast'

function getScoreColor(score: number, min: number, max: number): string {
  if (max <= min) return 'var(--text-secondary)'
  const ratio = (score - min) / (max - min)
  if (ratio >= 0.66) return 'var(--color-rise)'
  if (ratio <= 0.33) return 'var(--color-fall)'
  return 'var(--text-secondary)'
}

export function SelectionHistoryPage() {
  const { t } = useTranslation()
  const { message } = App.useApp()
  const navigate = useNavigate()
  const [strategyId, setStrategyId] = useState<string | undefined>(undefined)
  const [signalDate, setSignalDate] = useState<string | undefined>(undefined)
  const [results, setResults] = useState<SelectionResult[]>([])
  const [loading, setLoading] = useState(false)
  const [errorMsg, setErrorMsg] = useState<string | null>(null)
  const [dates, setDates] = useState<string[]>([])

  const { data: strategiesPage, error: strategiesError } = useRequest(() => fetchStrategies({ page_size: 200 }))
  useRequestErrorToast(strategiesError, t('strategy.selectStrategy'))
  const strategies = useMemo(() => extractPageItems<Strategy>(strategiesPage), [strategiesPage])

  useEffect(() => {
    if (!strategyId) {
      queueMicrotask(() => {
        setDates([])
        setSignalDate(undefined)
      })
      return
    }
    let cancelled = false
    fetchSelectionDates({ strategy_id: strategyId })
      .then((d) => {
        if (cancelled) return
        setDates(d)
        if (d.length > 0) {
          setSignalDate((cur) => cur ?? d[0])
        } else {
          setSignalDate(undefined)
        }
      })
      .catch((err) => {
        if (cancelled) return
        const msg = isApiError(err) ? err.message : err instanceof Error ? err.message : t('common.loadFailed')
        message.error(msg)
      })
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- message 为 antd 稳定引用
  }, [strategyId, t])

  const handleQuery = useCallback(async () => {
    if (!strategyId || !signalDate) {
      message.warning(t('strategy.emptyHistory'))
      return
    }
    setLoading(true)
    setErrorMsg(null)
    try {
      const page = await fetchSelectionResults({
        strategy_id: strategyId,
        signal_date: signalDate,
        page: 1,
        page_size: 500,
      })
      setResults(extractPageItems<SelectionResult>(page))
    } catch (err) {
      const msg = isApiError(err) ? err.message : err instanceof Error ? err.message : t('common.loadFailed')
      setErrorMsg(msg)
      message.error(msg)
    } finally {
      setLoading(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- message 为 antd 稳定引用
  }, [signalDate, strategyId, t])

  const scoreBounds = useMemo(() => {
    if (results.length === 0) return { min: 0, max: 1 }
    const scores = results.map((r) => r.score)
    return { min: Math.min(...scores), max: Math.max(...scores) }
  }, [results])

  const avgScore = useMemo(() => {
    if (results.length === 0) return null
    return results.reduce((acc, r) => acc + r.score, 0) / results.length
  }, [results])

  const strategyName = useMemo(
    () => strategies.find((s) => s.strategy_id === strategyId)?.name ?? strategyId ?? '—',
    [strategies, strategyId],
  )

  const factorKeys = useMemo(() => {
    const seen = new Set<string>()
    for (const r of results) {
      const fv = r.factor_values_flat ?? r.factor_values ?? {}
      for (const key of Object.keys(fv)) seen.add(key)
    }
    return Array.from(seen)
  }, [results])

  const columns: ColumnsType<SelectionResult> = useMemo(() => {
    const base: ColumnsType<SelectionResult> = [
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
      { title: t('strategy.name'), dataIndex: 'name', width: 100 },
      {
        title: t('strategy.score'),
        dataIndex: 'score',
        width: 100,
        sorter: (a, b) => a.score - b.score,
        defaultSortOrder: 'descend',
        render: (score: number) => (
          <span style={{ color: getScoreColor(score, scoreBounds.min, scoreBounds.max), fontFamily: 'var(--font-mono)' }}>
            {score.toFixed(4)}
          </span>
        ),
      },
      {
        title: t('strategy.direction'),
        dataIndex: 'direction',
        width: 90,
        render: (d: string | null) => (d ? <Tag color={d === 'long' ? 'red' : 'green'}>{d}</Tag> : '—'),
      },
      {
        title: t('strategy.confidence'),
        dataIndex: 'confidence',
        width: 96,
        render: (c: number | null) => (c == null ? '—' : c.toFixed(3)),
      },
    ]
    const factorCols: ColumnsType<SelectionResult> = factorKeys.map((key) => ({
      title: key,
      key: `factor_${key}`,
      width: 120,
      render: (_: unknown, record: SelectionResult) => {
        const fv = record.factor_values_flat ?? record.factor_values ?? {}
        const v = fv[key]
        return v == null ? '—' : Number(v).toFixed(4)
      },
    }))
    return [...base, ...factorCols]
  }, [factorKeys, scoreBounds, t])

  const handleRunAgain = useCallback(() => {
    if (!strategyId || !signalDate) return
    const sp = new URLSearchParams({ strategy_id: strategyId, signal_date: signalDate })
    navigate(`/strategy/workbench?${sp.toString()}`)
  }, [navigate, signalDate, strategyId])

  return (
    <div className="strategy-page">
      <div className="card">
        <div className="strategy-toolbar">
          <div className="strategy-toolbar__field" style={{ minWidth: 240 }}>
            <label>{t('strategy.selectStrategy')}</label>
            <Select
              value={strategyId}
              onChange={(v) => {
                setStrategyId(v)
                setSignalDate(undefined)
                setResults([])
              }}
              placeholder={t('strategy.selectStrategyPlaceholder')}
              options={strategies.map((s) => ({
                label: `${s.name} (${s.strategy_id})`,
                value: s.strategy_id,
              }))}
              showSearch
              optionFilterProp="label"
            />
          </div>
          <div className="strategy-toolbar__field" style={{ minWidth: 180 }}>
            <label>{t('strategy.signalDate')}</label>
            <Select
              value={signalDate}
              onChange={setSignalDate}
              placeholder={t('strategy.selectSignalDate')}
              options={dates.map((d) => ({ label: d, value: d }))}
              disabled={!strategyId}
            />
          </div>
          <div className="strategy-toolbar__actions">
            <Space>
              <Button icon={<Play size={14} />} onClick={handleRunAgain} disabled={!strategyId || !signalDate}>
                {t('strategy.runAgain')}
              </Button>
              <Button type="primary" icon={<Search size={14} />} onClick={() => void handleQuery()} loading={loading}>
                {t('strategy.queryAction')}
              </Button>
            </Space>
          </div>
        </div>

        {results.length > 0 && (
          <div className="strategy-stats" style={{ marginTop: 16 }}>
            <div className="strategy-stat">
              <span className="strategy-stat__label">{t('strategy.selectStrategy')}</span>
              <span className="strategy-stat__value" style={{ fontSize: 14 }}>{strategyName}</span>
            </div>
            <div className="strategy-stat">
              <span className="strategy-stat__label">{t('strategy.signalDate')}</span>
              <span className="strategy-stat__value" style={{ fontSize: 14 }}>{signalDate}</span>
            </div>
            <div className="strategy-stat">
              <span className="strategy-stat__label">{t('strategy.selectedCount')}</span>
              <span className="strategy-stat__value">{results.length}</span>
            </div>
            <div className="strategy-stat">
              <span className="strategy-stat__label">{t('strategy.avgScore')}</span>
              <span className="strategy-stat__value">{avgScore == null ? '—' : avgScore.toFixed(4)}</span>
            </div>
          </div>
        )}
      </div>

      <AsyncSection loading={loading} error={errorMsg}>
        {results.length > 0 ? (
          <div className="card">
            <Table<SelectionResult>
              size="small"
              dataSource={results}
              columns={columns}
              rowKey={(r) => `${r.symbol}_${r.rank}`}
              pagination={{ pageSize: 20, showTotal: (total) => `Total ${total}` }}
              scroll={{ x: 'max-content' }}
            />
          </div>
        ) : (
          <div className="card strategy-empty">
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t('strategy.emptyHistory')} />
          </div>
        )}
      </AsyncSection>
    </div>
  )
}
