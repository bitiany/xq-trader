import { request } from '@/api/client'

export interface IndexQuote {
  code: string
  name: string
  name_en: string
  last: number | null
  prev_close: number | null
  change: number | null
  change_pct: number | null
  open: number | null
  high: number | null
  low: number | null
  volume: number | null
  amount: number | null
  timestamp: string | null
  status: string
}

export async function fetchMajorIndices(): Promise<IndexQuote[]> {
  return request.get<IndexQuote[]>('/market/indices/major')
}
