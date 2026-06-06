import { request } from '@/api/client'

export interface ModelCallStat {
  provider_code: string
  key_id: number
  success_count: number
  avg_duration_ms: number
}

export interface CallLogsStats {
  total_models: number
  models: Record<string, ModelCallStat[]>
}

export interface CallLogsStatsParams {
  date?: string
}

export const callLogsApi = {
  stats(params?: CallLogsStatsParams) {
    return request.get<CallLogsStats>('/ai/call-logs/stats', { params })
  },
}
