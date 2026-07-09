import { Alert, Button, Empty, Tag } from 'antd'
import { RefreshCw } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import type { StockNewsItem, StockNewsResponse } from '@/api/stock'
import { StockPanelState } from '@/components/stock/StockPanelState'
import { formatDateTime } from '@/utils/format'

interface StockNewsListProps {
  data?: StockNewsResponse
  emptyKey: string
  keywordLabelKey?: string
  collectLabelKey?: string
  collecting?: boolean
  loading?: boolean
  error?: string | null
  onCollect?: () => void | Promise<void>
  onReload?: () => void
}

export function StockNewsList({
  data,
  emptyKey,
  keywordLabelKey,
  collectLabelKey = 'stock.news.collect',
  collecting,
  loading,
  error,
  onCollect,
  onReload,
}: StockNewsListProps) {
  const { t } = useTranslation()
  const [expanded, setExpanded] = useState<Record<string, boolean>>({})

  if (loading && !data) {
    return <StockPanelState loading />
  }

  if (error && !data) {
    return <StockPanelState error={error} onRetry={onReload} />
  }

  if (!data || data.items.length === 0) {
    return (
      <div className="stock-panel card">
        {error ? (
          <Alert
            type="error"
            showIcon
            title={t('common.loadFailed')}
            description={error}
            action={
              onReload ? (
                <Button size="small" onClick={onReload}>
                  {t('common.retry')}
                </Button>
              ) : undefined
            }
            style={{ marginBottom: 12 }}
          />
        ) : null}
        <Empty description={t(emptyKey)} />
        <div className="stock-news__empty-actions">
          {onCollect ? (
            <Button loading={collecting} onClick={() => void onCollect()}>
              {t(collectLabelKey)}
            </Button>
          ) : null}
          {onReload ? (
            <Button icon={<RefreshCw size={14} />} onClick={onReload}>
              {t('common.refresh')}
            </Button>
          ) : null}
        </div>
      </div>
    )
  }

  return (
    <div className="stock-panel card">
      {error ? (
        <Alert
          type="error"
          showIcon
          title={t('common.loadFailed')}
          description={error}
          action={
            onReload ? (
              <Button size="small" onClick={onReload}>
                {t('common.retry')}
              </Button>
            ) : undefined
          }
          style={{ marginBottom: 12 }}
        />
      ) : null}
      {onReload ? (
        <div className="stock-news__toolbar">
          <Button size="small" icon={<RefreshCw size={14} />} onClick={onReload} loading={loading}>
            {t('common.refresh')}
          </Button>
        </div>
      ) : null}
      <ul className="stock-news">
        {data.items.map((item) => (
          <StockNewsListItem
            key={item.id}
            item={item}
            expanded={expanded[item.id] ?? false}
            keywordLabel={keywordLabelKey ? t(keywordLabelKey) : undefined}
            onToggle={() => setExpanded((prev) => ({ ...prev, [item.id]: !prev[item.id] }))}
          />
        ))}
      </ul>
    </div>
  )
}

function StockNewsListItem({
  item,
  expanded,
  keywordLabel,
  onToggle,
}: {
  item: StockNewsItem
  expanded: boolean
  keywordLabel?: string
  onToggle: () => void
}) {
  const { t } = useTranslation()
  const summary = item.summary?.trim()
  const hasSummary = Boolean(summary && summary.length > 0)
  const preview = summary && summary.length > 120 && !expanded ? `${summary.slice(0, 120)}…` : summary

  return (
    <li className="stock-news__item">
      <div className="stock-news__title">
        {item.url ? (
          <a href={item.url} target="_blank" rel="noreferrer noopener">
            {item.title}
          </a>
        ) : (
          item.title
        )}
      </div>
      <div className="stock-news__meta">
        {[item.source, item.published_at ? formatDateTime(item.published_at) : null].filter(Boolean).join(' · ')}
      </div>
      {hasSummary ? (
        <div className="stock-news__summary">
          {preview}
          {summary && summary.length > 120 ? (
            <button type="button" className="stock-news__expand" onClick={onToggle}>
              {expanded ? t('stock.news.collapse') : t('stock.news.expand')}
            </button>
          ) : null}
        </div>
      ) : null}
      {item.keywords.length > 0 ? (
        <div className="stock-news__keywords">
          {keywordLabel ? <span className="stock-news__keywords-label">{keywordLabel}</span> : null}
          {item.keywords.map((kw) => (
            <Tag key={kw}>{kw}</Tag>
          ))}
        </div>
      ) : null}
    </li>
  )
}
