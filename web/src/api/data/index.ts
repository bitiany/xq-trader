import { request } from '@/api/client'

export interface WatermarkSummaryItem {
  pipeline_name: string
  display_name: string
  display_name_en: string
  code_count: number
  missing_count: number
  min_date: string | null
  max_date: string | null
  total_records: number
  coverage_pct: number | null
  lag_days: number | null
}

export interface StockTableStatItem {
  schema_name: string
  table_name: string
  label: string
  label_en: string
  approx_rows: number
  total_size: string
  total_bytes: number
}

export interface CollectTaskItem {
  task_id: string
  task_name: string
  task_name_en: string
  description: string
  description_en: string
  category: string
  task_type: string
  is_scheduled: boolean
  schedule: string | null
  schedule_display: string
  schedule_display_en: string
  queue: string
  timeout: number
  params_schema: Record<string, unknown> | null
  enabled: boolean
  status: string
  last_run_at: string | null
  worker_available: boolean
  source: string
  version: number
}

export interface DataSummaryResponse {
  pipeline_count: number
  total_codes: number
  total_records: number
  stock_table_count: number
  stock_total_bytes: number
  worker_available: boolean
}

export interface DataOverviewResponse {
  pipeline_count: number
  total_codes: number
  total_records: number
  stock_table_count: number
  stock_total_bytes: number
  worker_available: boolean
  reference_trade_date: string | null
  watermarks: WatermarkSummaryItem[]
  tables: StockTableStatItem[]
}

export interface TriggerTaskResponse {
  task_id: string
  queued: boolean
  message: string
}

export interface TaskLogItem {
  id: number
  task_id: string
  celery_task_id: string | null
  cycle_id: string | null
  node_id: string | null
  level: string
  message: string
  traceback: string | null
  extra: Record<string, unknown> | null
  created_at: string | null
}

export interface NodeItem {
  node_id: string
  status: string
  queues: string[]
  last_heartbeat: string | null
}

export async function fetchDataOverview(): Promise<DataOverviewResponse> {
  return request.get<DataOverviewResponse>('/data/overview')
}

export async function fetchDataSummary(): Promise<DataSummaryResponse> {
  return request.get<DataSummaryResponse>('/data/summary')
}

export interface WatermarksResponse {
  reference_trade_date: string
  items: WatermarkSummaryItem[]
}

export async function fetchWatermarks(): Promise<WatermarksResponse> {
  return request.get<WatermarksResponse>('/data/watermarks')
}

export async function fetchStockTables(): Promise<StockTableStatItem[]> {
  return request.get<StockTableStatItem[]>('/data/tables')
}

export async function fetchCollectTasks(): Promise<CollectTaskItem[]> {
  return request.get<CollectTaskItem[]>('/data/tasks')
}

export async function fetchCollectTask(taskId: string): Promise<CollectTaskItem> {
  return request.get<CollectTaskItem>(`/data/tasks/${taskId}`)
}

export async function createCollectTask(data: Record<string, unknown>): Promise<CollectTaskItem> {
  return request.post<CollectTaskItem>('/data/tasks', data)
}

export async function updateCollectTask(taskId: string, data: Record<string, unknown>): Promise<CollectTaskItem> {
  return request.put<CollectTaskItem>(`/data/tasks/${taskId}`, data)
}

export async function deleteCollectTask(taskId: string): Promise<void> {
  await request.delete(`/data/tasks/${taskId}`)
}

export async function enableCollectTask(taskId: string): Promise<CollectTaskItem> {
  return request.patch<CollectTaskItem>(`/data/tasks/${taskId}/enable`)
}

export async function disableCollectTask(taskId: string): Promise<CollectTaskItem> {
  return request.patch<CollectTaskItem>(`/data/tasks/${taskId}/disable`)
}

export async function updateTaskSchedule(
  taskId: string,
  schedule: string,
  scheduleDisplay?: string,
  scheduleDisplayEn?: string,
  reason?: string,
): Promise<CollectTaskItem> {
  return request.patch<CollectTaskItem>(`/data/tasks/${taskId}/schedule`, {
    schedule,
    schedule_display: scheduleDisplay,
    schedule_display_en: scheduleDisplayEn,
    reason,
  })
}

export async function triggerCollectTask(taskId: string, params?: Record<string, unknown>): Promise<TriggerTaskResponse> {
  return request.post<TriggerTaskResponse>(`/data/tasks/${taskId}/trigger`, { params })
}

export async function fetchTaskLogs(
  taskId: string,
  level?: string,
  limit = 50,
  offset = 0,
): Promise<{ items: TaskLogItem[]; total: number }> {
  const params: Record<string, unknown> = { limit, offset }
  if (level) params.level = level
  return request.get<{ items: TaskLogItem[]; total: number }>(`/data/tasks/${taskId}/logs`, { params })
}

export async function fetchLogs(
  taskId?: string,
  level?: string,
  limit = 50,
  offset = 0,
): Promise<{ items: TaskLogItem[]; total: number }> {
  const params: Record<string, unknown> = { limit, offset }
  if (taskId) params.task_id = taskId
  if (level) params.level = level
  return request.get<{ items: TaskLogItem[]; total: number }>('/data/logs', { params })
}

export async function fetchNodes(): Promise<NodeItem[]> {
  return request.get<NodeItem[]>('/data/nodes')
}
