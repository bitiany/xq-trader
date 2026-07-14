import { useEffect, useMemo, useState } from 'react'

import type { StockQuoteSnapshot } from '@/api/stock'
import { buildStockQuoteTopic } from '@/api/stock'
import { isAshareTradingSession } from '@/utils/tradingSession'
import { usePageWebSocket } from '@/ws/usePageWebSocket'

export function useStockQuote(symbol: string | undefined, enabled = true) {
  const [quote, setQuote] = useState<StockQuoteSnapshot | null>(null)
  const [inSession, setInSession] = useState(() => isAshareTradingSession())

  // 切换 symbol 时保留旧 quote，直到新 symbol 的 quote 到达
  // 避免 queueMicrotask 置 null 导致价格闪烁（显示 '-' 的一帧）
  // 新 symbol 的 WS 推送会自动覆盖旧 quote

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
