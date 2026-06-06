import { useTranslation } from 'react-i18next'

import type { StockOverviewResponse, StockQuoteSnapshot, StockValuationPanel } from '@/api/stock'
import { StockTagList } from '@/components/stock/StockTagBadge'

interface StockQuoteHeaderProps {
  overview: StockOverviewResponse
  quote: StockQuoteSnapshot
  valuation: StockValuationPanel
}

function formatPrice(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) {
    return '--'
  }
  return value.toFixed(2)
}

function formatPercent(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) {
    return '--'
  }
  return `${value >= 0 ? '+' : ''}${value.toFixed(2)}%`
}

function formatMetric(value: number | null | undefined, digits = 2): string {
  if (value == null || Number.isNaN(value)) {
    return '--'
  }
  return value.toFixed(digits)
}

function formatMarketCap(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) {
    return '--'
  }
  if (value >= 100000000) {
    return `${(value / 100000000).toFixed(2)}亿`
  }
  if (value >= 10000) {
    return `${(value / 10000).toFixed(2)}万`
  }
  return value.toFixed(0)
}

export function StockQuoteHeader({ overview, quote, valuation }: StockQuoteHeaderProps) {
  const { t } = useTranslation()
  const trend =
    quote.change_pct == null ? '' : quote.change_pct > 0 ? 'up' : quote.change_pct < 0 ? 'down' : 'flat'

  const metrics = [
    { label: t('stock.quote.open'), value: formatPrice(quote.open) },
    { label: t('stock.quote.high'), value: formatPrice(quote.high) },
    { label: t('stock.quote.low'), value: formatPrice(quote.low) },
    { label: t('stock.quote.prevClose'), value: formatPrice(quote.prev_close) },
    { label: t('stock.valuation.peTtm'), value: formatMetric(valuation.pe_ttm) },
    { label: t('stock.valuation.pb'), value: formatMetric(valuation.pb) },
    { label: t('stock.valuation.psTtm'), value: formatMetric(valuation.ps_ttm) },
    { label: t('stock.valuation.dvRatio'), value: formatMetric(valuation.dv_ratio) },
    { label: t('stock.valuation.totalMv'), value: formatMarketCap(valuation.total_mv) },
    { label: t('stock.valuation.circMv'), value: formatMarketCap(valuation.circ_mv) },
    { label: t('stock.valuation.turnover'), value: formatMetric(valuation.turnover_rate) },
    { label: t('stock.valuation.tradeDate'), value: valuation.trade_date ?? '--' },
  ]

  return (
    <section className="stock-header">
      <div className="stock-header__identity">
        <h1 className="stock-header__name">{overview.name}</h1>
        <div className="stock-header__meta">
          <span className="stock-header__symbol">{overview.symbol}</span>
          <span className="stock-header__sep">·</span>
          <span>{overview.industry}</span>
          <span className="stock-header__sep">·</span>
          <span>{overview.market}</span>
          {overview.tags && overview.tags.length > 0 ? (
            <>
              <span className="stock-header__sep">·</span>
              <StockTagList tags={overview.tags} size="small" max={5} />
            </>
          ) : null}
        </div>
      </div>

      <div className={`stock-header__quote stock-header__quote--${trend}`}>
        <div className="stock-header__price">{formatPrice(quote.last)}</div>
        <div className="stock-header__change">
          <span>{quote.change != null ? `${quote.change >= 0 ? '+' : ''}${quote.change.toFixed(2)}` : '--'}</span>
          <span>{formatPercent(quote.change_pct)}</span>
        </div>
      </div>

      <div className="stock-header__metrics">
        {metrics.map((item) => (
          <div key={item.label} className="stock-header__metric">
            <span className="stock-header__metric-label">{item.label}</span>
            <strong className="stock-header__metric-value">{item.value}</strong>
          </div>
        ))}
      </div>
    </section>
  )
}
