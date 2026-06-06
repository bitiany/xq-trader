import { useCallback, useEffect, useRef, useState } from 'react'

import {
  fetchStockKline,
  type IndicatorKind,
  type KlineBarItem,
  type StockKlineResponse,
} from '@/api/stock'
import { resolveMaOverlays, resolveOverlays, type OverlaySeries } from '@/utils/klineIndicators'

export function useStockKline(symbol: string, indicator: IndicatorKind) {
  const [bars, setBars] = useState<KlineBarItem[]>([])
  const [apiOverlays, setApiOverlays] = useState<Record<string, OverlaySeries>>({})
  const [apiMaOverlays, setApiMaOverlays] = useState<OverlaySeries>({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const loadedSymbolRef = useRef<string>('')
  const loadingRef = useRef(false)

  const loadBars = useCallback(async (sym: string) => {
    if (!sym || loadingRef.current) {
      return
    }
    loadingRef.current = true
    setLoading(true)
    setError(null)
    try {
      const response = await fetchStockKline(sym, 'ma')
      setBars(response.bars)
      setApiOverlays(response.overlays ?? {})
      setApiMaOverlays(response.ma_overlays ?? {})
      loadedSymbolRef.current = sym
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载失败')
    } finally {
      setLoading(false)
      loadingRef.current = false
    }
  }, [])

  useEffect(() => {
    if (!symbol) {
      setBars([])
      setApiOverlays({})
      setApiMaOverlays({})
      setLoading(false)
      return
    }
    if (loadedSymbolRef.current === symbol) {
      return
    }
    void loadBars(symbol)
  }, [symbol, loadBars])

  const indicatorOverlays = apiOverlays[indicator] ?? {}
  const overlays = resolveOverlays(bars, indicator, indicatorOverlays)
  const maOverlays = resolveMaOverlays(bars, apiMaOverlays)

  return { bars, overlays, maOverlays, loading, error, reload: () => void loadBars(symbol) }
}
