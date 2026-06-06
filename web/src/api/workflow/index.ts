import { request } from '@/api/client'

export interface WorkflowRunRequest {
  flow_id: string
  workspace_id: string
  inputs?: Record<string, unknown>
}

export interface WorkflowRunResponse {
  execute_id: string
  flow_id: string
  workspace_id: string
  status: 'completed' | 'interrupted'
  thread_id?: string
  interrupt?: {
    step: string
    message: string
    data: unknown
  } | null
  result: Record<string, unknown>
}

export interface WorkflowResumeRequest {
  flow_id: string
  execute_id: string
  thread_id: string
  resume_value: unknown
}

export interface WorkflowStatusResponse {
  execute_id: string
  type: string
  status: string
  [key: string]: unknown
}

export interface WorkflowInfo {
  flow_id: string
  name: string
  description: string
}

export interface RotationCategoryResult {
  execute_id: string
  category: string
  trade_date: string
  status: string
  rotation_result: {
    universe_id: string
    as_of_date: string
    sector_count: number
    phase_distribution: Record<string, number>
  }
  top_sectors: Array<{
    rank: number
    sector_code: string
    sector_name: string
    composite_score: number | null
    phase: string | null
    [key: string]: unknown
  }>
  sector_scores_summary: {
    total: number
    phase_distribution: Record<string, number>
  }
}

export interface ResonanceResult {
  execute_id: string
  workspace_id: string
  status: string
  resonance_summary: {
    total_sectors_analyzed: number
    num_categories: number
    strong_resonance_count: number
    categories_processed: string[]
  }
  strong_resonance_sectors: Array<{
    sector_code: string
    sector_name: string
    primary_category: string
    momentum_exposure: number
    resonance_ratio: number
    categories_present: number
    composite_scores: Record<string, number>
    phases: Record<string, string>
    matched_sectors: Array<{
      category: string
      sector_code: string
      sector_name: string
    }>
  }>
  momentum_exposure_top: Record<string, number>
}

export interface SectorRotationWorkflowResult {
  execute_id: string
  workspace_id: string
  categories: Record<string, RotationCategoryResult>
  category_count: number
}

export async function runWorkflow(
  payload: WorkflowRunRequest,
): Promise<WorkflowRunResponse> {
  return request.post<WorkflowRunResponse>('/workflow/run', payload)
}

export async function resumeWorkflow(
  payload: WorkflowResumeRequest,
): Promise<WorkflowRunResponse> {
  return request.post<WorkflowRunResponse>('/workflow/resume', payload)
}

export async function fetchWorkflowStatus(
  executeId: string,
): Promise<WorkflowStatusResponse> {
  return request.get<WorkflowStatusResponse>(
    `/workflow/status/${encodeURIComponent(executeId)}`,
  )
}

export async function fetchWorkflowList(): Promise<WorkflowInfo[]> {
  return request.get<WorkflowInfo[]>('/workflow/list')
}
