import { useCallback, useEffect, useRef, useState } from 'react'
import { isApiError } from '@/api'

export interface UseRequestOptions<T> {
  immediate?: boolean
  initialData?: T
  /** 依赖变化时重新请求（如路由 symbol） */
  deps?: readonly unknown[]
  /** 重请求时保留上一次成功数据，避免闪 Empty；默认 true */
  keepPreviousData?: boolean
}

export interface UseRequestResult<T> {
  data: T | undefined
  loading: boolean
  error: string | null
  errorCode: number | null
  reload: () => Promise<void>
  mutate: (updater: T | ((prev: T | undefined) => T)) => void
}

export function useRequest<T>(
  fetcher: () => Promise<T>,
  options: UseRequestOptions<T> = {},
): UseRequestResult<T> {
  const { immediate = true, initialData, deps = [], keepPreviousData = true } = options
  const [data, setData] = useState<T | undefined>(initialData)
  const [loading, setLoading] = useState(immediate)
  const [error, setError] = useState<string | null>(null)
  const [errorCode, setErrorCode] = useState<number | null>(null)
  const fetcherRef = useRef(fetcher)
  const depsKey = JSON.stringify(deps)

  useEffect(() => {
    fetcherRef.current = fetcher
  }, [fetcher])

  const runFetch = useCallback(async (isMounted: () => boolean) => {
    setLoading(true)
    setError(null)
    setErrorCode(null)
    try {
      const result = await fetcherRef.current()
      if (isMounted()) {
        setData(result)
      }
    } catch (err) {
      if (!isMounted()) return
      if (isApiError(err)) {
        setError(err.message)
        setErrorCode(err.code)
      } else if (err instanceof Error) {
        setError(err.message)
      } else {
        setError('未知错误')
      }
    } finally {
      if (isMounted()) {
        setLoading(false)
      }
    }
  }, [])

  const reload = useCallback(async () => {
    await runFetch(() => true)
  }, [runFetch])

  useEffect(() => {
    if (!immediate) {
      return
    }

    let mounted = true
    const isMounted = () => mounted

    queueMicrotask(() => {
      if (mounted) {
        if (!keepPreviousData) {
          setData(undefined)
        }
        setLoading(true)
        void runFetch(isMounted)
      }
    })

    return () => {
      mounted = false
    }
  }, [immediate, runFetch, depsKey, keepPreviousData])

  const mutate = useCallback((updater: T | ((prev: T | undefined) => T)) => {
    setData((prev) => (typeof updater === 'function' ? (updater as (p: T | undefined) => T)(prev) : updater))
  }, [])

  return { data, loading, error, errorCode, reload, mutate }
}
