import { request } from '@/api/client'
import type { ApiPageResult } from '@/api/types'

export type PoolType = 'all' | 'index' | 'style' | 'industry'

export interface Pool {
  pool_id: string
  pool_name: string
  pool_type: PoolType
  definition?: Record<string, unknown> | null
  description?: string | null
  is_builtin?: boolean
}

export interface PoolSecurity {
  symbol: string
  code?: string
  name: string
  industry?: string | null
  market?: string | null
}

export interface PoolSymbolsParams {
  page?: number
  page_size?: number
  keyword?: string
}

export async function fetchPools(includeDb = true): Promise<Pool[]> {
  return request.get<Pool[]>('/universe/pools', {
    params: { include_db: includeDb },
  })
}

export async function fetchPoolSymbols(
  poolId: string,
  params: PoolSymbolsParams = {},
): Promise<ApiPageResult<PoolSecurity>> {
  return request.get<ApiPageResult<PoolSecurity>>(
    `/universe/pools/${encodeURIComponent(poolId)}/symbols`,
    { params },
  )
}
