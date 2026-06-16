import { request } from '@/api/client'

export interface WatermarkSummaryItem {
  data_type: string
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
  data_type_count: number
  total_codes: number
  total_records: number
  table_count: number
  total_bytes: number
  worker_available: boolean
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

export async function fetchNodes(): Promise<NodeItem[]> {
  return request.get<NodeItem[]>('/data/nodes')
}

export interface PipelineStep {
  name: string
  task: string
  depends_on?: string[]
  args?: Record<string, unknown>
}

export interface PipelineItem {
  pipeline_name: string
  description: string
  mode: string
  cron: string | null
  queue: string
  enabled: boolean
  steps: PipelineStep[]
  step_count: number
  status: string
  last_run_at: string | null
}

export async function fetchPipelines(): Promise<PipelineItem[]> {
  return request.get<PipelineItem[]>('/data/pipelines')
}

export async function triggerPipeline(pipelineName: string): Promise<TriggerTaskResponse> {
  return request.post<TriggerTaskResponse>(`/data/pipelines/${pipelineName}/trigger`)
}
