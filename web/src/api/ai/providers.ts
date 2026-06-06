import { request } from '@/api/client'
import type { ApiPageParams, ApiPageResult } from '@/api/types'
import { extractPageItems } from '@/api/types'

export interface AiProviderDefinition {
  id: number
  name: string
  code: string
  icon?: string
  api_url?: string
  remark?: string
}

export interface AiProviderKey {
  id: number
  provider_code: string
  api_key?: string
  status?: boolean
  params?: Record<string, unknown> | null
  remark?: string | null
}

export interface CreateProviderKeyPayload {
  api_key: string
  status?: boolean
  remark?: string
  params?: Record<string, unknown>
}

export interface UpdateProviderKeyPayload {
  api_key?: string
  status?: boolean
  remark?: string
  params?: Record<string, unknown>
}

export interface AiProviderListParams extends ApiPageParams {
  name?: string
}

export const aiProviderApi = {
  list(params?: AiProviderListParams) {
    return request.get<ApiPageResult<AiProviderDefinition>>('/ai/providers', { params })
  },

  listKeys(providerCode: string, params?: ApiPageParams) {
    return request.get<ApiPageResult<AiProviderKey>>(`/ai/providers/${providerCode}/keys`, { params })
  },

  createKey(providerCode: string, values: CreateProviderKeyPayload) {
    return request.post<AiProviderKey>(`/ai/providers/${providerCode}/keys`, values)
  },

  updateKey(keyId: number, values: UpdateProviderKeyPayload) {
    return request.put<AiProviderKey>(`/ai/providers/keys/${keyId}`, values)
  },

  deleteKey(keyId: number) {
    return request.delete<void>(`/ai/providers/keys/${keyId}`)
  },
}

export function normalizeProviderKeyList(
  data: ApiPageResult<AiProviderKey> | AiProviderKey[] | undefined,
): AiProviderKey[] {
  return extractPageItems<AiProviderKey>(data)
}

export function normalizeProviderDefinitionList(
  data: ApiPageResult<AiProviderDefinition> | AiProviderDefinition[] | undefined,
): AiProviderDefinition[] {
  return extractPageItems<AiProviderDefinition>(data)
}
