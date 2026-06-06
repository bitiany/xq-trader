import { useCallback, useMemo, useState } from 'react'
import {
  aiModelApi,
  normalizeModelList,
  normalizeProviderList,
  type AiModelItem,
  type AiModelProvider,
} from '@/api/ai/models'
import {
  aiProviderApi,
  normalizeProviderDefinitionList,
  type AiProviderDefinition,
} from '@/api/ai/providers'

export function useModelMarketplace() {
  const [models, setModels] = useState<AiModelItem[]>([])
  const [providers, setProviders] = useState<AiProviderDefinition[]>([])
  const [modelProviders, setModelProviders] = useState<AiModelProvider[]>([])
  const [modelsLoading, setModelsLoading] = useState(true)
  const [providersLoading, setProvidersLoading] = useState(true)
  const [modelsError, setModelsError] = useState<string | null>(null)
  const [providersError, setProvidersError] = useState<string | null>(null)

  const loadModelProviders = useCallback(async (modelList: AiModelItem[]) => {
    const ids = modelList.map((m) => m.id).filter((id): id is number => id != null)
    if (ids.length === 0) {
      setModelProviders([])
      return
    }

    const results = await Promise.allSettled(
      ids.map(async (id) => {
        const data = await aiModelApi.listProviders(id)
        return normalizeProviderList(data).map((item) => ({ ...item, model_id: item.model_id ?? id }))
      }),
    )

    const merged = results.flatMap((result) => (result.status === 'fulfilled' ? result.value : []))
    setModelProviders(merged)
  }, [])

  const loadProviders = useCallback(async () => {
    setProvidersLoading(true)
    setProvidersError(null)
    try {
      const data = await aiProviderApi.list({ page: 1, page_size: 100 })
      setProviders(normalizeProviderDefinitionList(data))
    } catch (err) {
      setProvidersError(err instanceof Error ? err.message : '加载供应商列表失败')
    } finally {
      setProvidersLoading(false)
    }
  }, [])

  const reloadModels = useCallback(async () => {
    setModelsLoading(true)
    setModelsError(null)
    try {
      const data = await aiModelApi.list({ page: 1, page_size: 100 })
      const list = normalizeModelList(data)
      setModels(list)
      void loadModelProviders(list)
    } catch (err) {
      setModelsError(err instanceof Error ? err.message : '加载模型列表失败')
    } finally {
      setModelsLoading(false)
    }
  }, [loadModelProviders])

  const reloadAll = useCallback(async () => {
    await Promise.all([reloadModels(), loadProviders()])
  }, [reloadModels, loadProviders])

  const modelsWithStats = useMemo(() => {
    return models.map((model) => {
      if (model.id == null) return model
      const count = modelProviders.filter((p) => p.model_id === model.id).length
      return { ...model, provider_count: count }
    })
  }, [models, modelProviders])

  return {
    models: modelsWithStats,
    providers,
    modelsLoading,
    providersLoading,
    modelsError,
    providersError,
    reloadAll,
    reloadModels,
    loadProviders,
  }
}
