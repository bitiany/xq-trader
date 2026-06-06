/** 后台统一业务响应（AI 流式对话等接口除外） */
export interface ApiResponse<T = unknown> {
  code: number
  message: string
  data: T
}

export interface ApiPageParams {
  page: number
  page_size: number
}

export interface ApiPageResult<T> {
  items?: T[]
  list?: T[]
  total?: number
  page?: number
  page_size?: number
  [key: string]: unknown
}

export class ApiError extends Error {
  readonly code: number
  readonly status?: number

  constructor(message: string, code = -1, status?: number) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.status = status
  }
}

export function isApiError(error: unknown): error is ApiError {
  return error instanceof ApiError
}

/** 从分页响应、数组或误传的 AxiosResponse 中提取列表 */
export function extractPageItems<T>(payload: unknown): T[] {
  if (payload == null) return []

  if (Array.isArray(payload)) {
    return payload as T[]
  }

  if (typeof payload !== 'object') return []

  const record = payload as Record<string, unknown>

  // 兼容 axios 响应体 { data: { items: [] } }
  if (
    'data' in record &&
    record.data != null &&
    typeof record.data === 'object' &&
    !('items' in record) &&
    !('list' in record) &&
    !Array.isArray(record.data)
  ) {
    return extractPageItems<T>(record.data)
  }

  const list = record.items ?? record.list
  return Array.isArray(list) ? (list as T[]) : []
}
