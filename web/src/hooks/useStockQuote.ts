import { useEffect, useMemo, useState } from 'react'

import type { StockQuoteSnapshot } from '@/api/stock'
import { buildStockQuoteTopic } from '@/api/stock'
import { isAshareTradingSession } from '@/utils/tradingSession'
import { usePageWebSocket } from '@/ws/usePageWebSocket'

export function useStockQuote(symbol: string | undefined, enabled = true) {
  const [quote, setQuote] = useState<StockQuoteSnapshot | null>(null)
  const [inSession, setInSession] = useState(() => isAshareTradingSession())

  useEffect(() => {
    queueMicrotask(() => {
      setQuote(null)
    })
  }, [symbol])

  useEffect(() => {
    const timer = window.setInterval(() => {
      setInSession(isAshareTradingSession())
    }, 30_000)
    return () => window.clearInterval(timer)
  }, [])

  const topics = useMemo(
    () => (symbol && enabled && inSession ? [buildStockQuoteTopic(symbol)] : []),
    [enabled, inSession, symbol],
  )

  const applyQuote = (data: StockQuoteSnapshot) => {
    setQuote(data)
  }

  usePageWebSocket<StockQuoteSnapshot>({
    topics,
    enabled: Boolean(symbol && enabled && inSession),
    onSnapshot: (_channel, data) => applyQuote(data),
    onUpdate: (_channel, data) => applyQuote(data),
  })

  return { quote, inSession }
}
