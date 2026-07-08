interface StockQuoteCellProps {
  symbol: string
  name?: string | null
  price?: string | number | null
  costPrice?: string | number | null
  pnl?: string | number | null
}

function num(value: string | number | null | undefined): number {
  return Number(value ?? 0)
}

function resolveTone(pnl: number | undefined, cost: number, price: number): 'rise' | 'fall' | 'neutral' {
  if (pnl !== undefined && pnl !== 0) return pnl > 0 ? 'rise' : 'fall'
  if (cost > 0 && price > 0) {
    const delta = price - cost
    if (delta > 0) return 'rise'
    if (delta < 0) return 'fall'
  }
  return 'neutral'
}

function formatChangePct(cost: number, price: number): string | null {
  if (cost <= 0 || price <= 0) return null
  const pct = ((price - cost) / cost) * 100
  const sign = pct > 0 ? '+' : ''
  return `${sign}${pct.toFixed(2)}%`
}

export function StockQuoteCell({ symbol, name, price, costPrice, pnl }: StockQuoteCellProps) {
  const displayName = name && name !== symbol ? name : symbol
  const priceValue = num(price)
  const costValue = num(costPrice)
  const pnlValue = pnl === undefined || pnl === null ? undefined : num(pnl)
  const tone = resolveTone(pnlValue, costValue, priceValue)
  const toneColor = tone === 'rise' ? 'var(--color-rise)' : tone === 'fall' ? 'var(--color-fall)' : 'var(--text-secondary)'
  const changePct = formatChangePct(costValue, priceValue)

  return (
    <div className="stock-quote-cell" data-component="Stock Quote Cell">
      <div className="stock-quote-cell__name" title={displayName}>{displayName}</div>
      <div className="stock-quote-cell__bottom">
        <span className="stock-quote-cell__symbol">{symbol}</span>
        {price !== undefined && price !== null && (
          <span className="stock-quote-cell__price" style={{ color: toneColor }}>
            {priceValue.toFixed(2)}
            {changePct && (
              <span className="stock-quote-cell__change" style={{ color: toneColor }}>
                {changePct}
              </span>
            )}
          </span>
        )}
      </div>
    </div>
  )
}

interface StockSymbolCellProps {
  symbol: string
  name?: string | null
}

export function StockSymbolCell({ symbol, name }: StockSymbolCellProps) {
  const displayName = name && name !== symbol ? name : symbol
  return (
    <div className="stock-quote-cell stock-quote-cell--compact" data-component="Stock Symbol Cell">
      <div className="stock-quote-cell__name" title={displayName}>{displayName}</div>
      {displayName !== symbol && <div className="stock-quote-cell__symbol">{symbol}</div>}
    </div>
  )
}
