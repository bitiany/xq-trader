import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import {
  fetchStockChanlun,
  fetchStockKline,
  type ChanlunResponse,
  type MainIndicator,
  type SubIndicator,
  type KlineBarItem,
} from '@/api/stock'

export function useStockKline(symbol: string, mainIndicator: MainIndicator, _subIndicator: SubIndicator) {
  const [bars, setBars] = useState<KlineBarItem[]>([])
  const [apiOverlays, setApiOverlays] = useState<Record<string, Record<string, Array<number | null>>>>({})
  const [apiMaOverlays, setApiMaOverlays] = useState<Record<string, Array<number | null>>>({})
  const [chanlun, setChanlun] = useState<ChanlunResponse | null>(null)
  const [chanlunLoading, setChanlunLoading] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [chanlunError, setChanlunError] = useState<string | null>(null)

  const loadedSymbolRef = useRef<string>('')
  const chanlunLoadedRef = useRef<string>('')
  const loadingRef = useRef(false)

  const loadBars = useCallback(async (sym: string) => {
    if (!sym || loadingRef.current) {
      return
    }
    loadingRef.current = true
    setLoading(true)
    setError(null)
    try {
      const response = await fetchStockKline(sym)
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
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setBars([])
      setApiOverlays({})
      setApiMaOverlays({})
      setChanlun(null)
      setChanlunError(null)
      setLoading(false)
      return
    }
    if (loadedSymbolRef.current === symbol) {
      return
    }
    void loadBars(symbol)
  }, [symbol, loadBars])

  useEffect(() => {
    if (mainIndicator !== 'chanlun' || !symbol || chanlunLoadedRef.current === symbol) {
      setChanlunLoading(false)
      return
    }
    let cancelled = false
    setChanlunLoading(true)
    setChanlunError(null)
    fetchStockChanlun(symbol)
      .then((data) => {
        if (!cancelled) {
          setChanlun(data)
          chanlunLoadedRef.current = symbol
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setChanlun(null)
          setChanlunError(err instanceof Error ? err.message : '缠论数据加载失败')
        }
      })
      .finally(() => {
        if (!cancelled) {
          setChanlunLoading(false)
        }
      })
    return () => {
      cancelled = true
    }
  }, [mainIndicator, symbol])

  const maOverlays = useMemo(() => apiMaOverlays, [apiMaOverlays])
  const allOverlays = useMemo(() => {
    return Object.fromEntries(
      (['ma', 'macd', 'kdj', 'rsi', 'bias', 'adx', 'boll', 'td9'] as const).map((kind) => [
        kind,
        kind === 'ma' ? maOverlays : (apiOverlays[kind] ?? {}),
      ]),
    )
  }, [apiOverlays, maOverlays])

  return {
    bars,
    maOverlays,
    allOverlays,
    chanlun,
    chanlunLoading,
    loading,
    error,
    chanlunError,
    reload: () => void loadBars(symbol),
  }
}
