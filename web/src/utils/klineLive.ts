import type { KlineBarItem, StockQuoteSnapshot } from '@/api/stock'

export function mergeLiveQuoteIntoBars(
  bars: KlineBarItem[],
  quote: StockQuoteSnapshot | null | undefined,
  referenceTradeDate: string | null | undefined,
): KlineBarItem[] {
  if (!quote || quote.last == null || !referenceTradeDate) {
    return bars
  }

  const next = bars.map((bar) => ({ ...bar }))
  const lastIndex = next.length - 1
  const lastBar = lastIndex >= 0 ? next[lastIndex] : null

  if (lastBar && lastBar.trade_date === referenceTradeDate) {
    const last = quote.last
    next[lastIndex] = {
      ...lastBar,
      close: last,
      high: quote.high != null ? Math.max(lastBar.high, quote.high, last) : Math.max(lastBar.high, last),
      low: quote.low != null ? Math.min(lastBar.low, quote.low, last) : Math.min(lastBar.low, last),
      open: quote.open ?? lastBar.open,
      volume: quote.volume != null ? Math.round(quote.volume) : lastBar.volume,
      amount: quote.amount ?? lastBar.amount,
      pct_chg:
        quote.change_pct ??
        (quote.prev_close != null && quote.prev_close !== 0
          ? ((last - quote.prev_close) / quote.prev_close) * 100
          : lastBar.pct_chg),
    }
    return next
  }

  if (lastBar && referenceTradeDate > lastBar.trade_date && quote.open != null) {
    next.push({
      trade_date: referenceTradeDate,
      open: quote.open,
      close: quote.last,
      high: quote.high ?? Math.max(quote.open, quote.last),
      low: quote.low ?? Math.min(quote.open, quote.last),
      volume: quote.volume != null ? Math.round(quote.volume) : 0,
      amount: quote.amount ?? 0,
      pct_chg:
        quote.change_pct ??
        (quote.prev_close != null && quote.prev_close !== 0
          ? ((quote.last - quote.prev_close) / quote.prev_close) * 100
          : null),
    })
  }

  return next
}

export function prependUniqueBars(existing: KlineBarItem[], older: KlineBarItem[]): KlineBarItem[] {
  if (older.length === 0) {
    return existing
  }
  const existingDates = new Set(existing.map((bar) => bar.trade_date))
  const filtered = older.filter((bar) => !existingDates.has(bar.trade_date))
  return [...filtered, ...existing]
}
