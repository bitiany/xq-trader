import { request } from '@/api/client'
import type { ApiPageParams, ApiPageResult } from '@/api/types'
import { extractPageItems } from '@/api/types'

export interface AiModelItem {
  id?: number
  name?: string
  type?: string
  status?: boolean
  description?: string
  provider_count?: number
  [key: string]: unknown
}

export interface AiModelListParams extends ApiPageParams {
  name?: string
  type?: string
  status?: boolean
}

export interface AiModelProvider {
  id: number
  model_id: number
  provider_code: string
  provider_model_name?: string | null
  status?: boolean
  remark?: string | null
  /** @deprecated 兼容旧字段，读取时映射自 provider_code */
  provider_type?: string
  [key: string]: unknown
}

export interface CreateModelPayload {
  name: string
  type: string
  status?: boolean
  description?: string
}

export interface UpdateModelPayload {
  name?: string
  type?: string
  status?: boolean
  description?: string
}

export interface AddProviderPayload {
  provider_code: string
  provider_model_name?: string
  status?: boolean
  remark?: string
}

export interface UpdateProviderPayload {
  provider_model_name?: string
  status?: boolean
  remark?: string
}

export interface ModelConfigPayload {
  [key: string]: unknown
}

export const aiModelApi = {
  list(params: AiModelListParams) {
    return request.get<ApiPageResult<AiModelItem>>('/ai/models', { params })
  },

  listProviders(modelId: number) {
    return request.get<AiModelProvider[] | ApiPageResult<AiModelProvider>>(`/ai/models/${modelId}/providers`)
  },

  getConfig(modelId: number) {
    return request.get<Record<string, unknown>>(`/ai/models/${modelId}/config`)
  },

  create(values: CreateModelPayload) {
    return request.post<AiModelItem>('/ai/models', values)
  },

  update(modelId: number, values: UpdateModelPayload) {
    return request.put<AiModelItem>(`/ai/models/${modelId}`, values)
  },

  delete(modelId: number) {
    return request.delete<void>(`/ai/models/${modelId}`)
  },

  addProvider(modelId: number, values: AddProviderPayload) {
    return request.post<AiModelProvider>(`/ai/models/${modelId}/providers`, values)
  },

  removeProvider(modelProviderId: number) {
    return request.delete<void>(`/ai/models/providers/${modelProviderId}`)
  },

  updateProvider(modelProviderId: number, values: UpdateProviderPayload) {
    return request.put<AiModelProvider>(`/ai/models/providers/${modelProviderId}`, values)
  },

  saveConfig(modelId: number, values: ModelConfigPayload) {
    return request.put<Record<string, unknown>>(`/ai/models/${modelId}/config`, values)
  },
}

export function normalizeProviderList(
  data: AiModelProvider[] | ApiPageResult<AiModelProvider> | undefined,
): AiModelProvider[] {
  return extractPageItems<AiModelProvider>(data).map((item) => ({
    ...item,
    provider_type: item.provider_code ?? item.provider_type,
  }))
}

export function normalizeModelList(
  data: ApiPageResult<AiModelItem> | AiModelItem[] | undefined,
): AiModelItem[] {
  return extractPageItems<AiModelItem>(data)
}
