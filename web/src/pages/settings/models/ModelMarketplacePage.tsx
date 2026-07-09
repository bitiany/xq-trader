import { useEffect, useState } from 'react'
import { App, Button, Modal } from 'antd'
import { useTranslation } from 'react-i18next'
import { aiModelApi, type AiModelItem } from '@/api/ai/models'
import type { AiProviderDefinition } from '@/api/ai/providers'
import { AsyncSection } from '@/components/common/AsyncSection'
import { MarketplacePanel } from './components/MarketplacePanel'
import { ModelFormModal, type ModelFormValues } from './components/ModelFormModal'
import { ModelListSection } from './components/ModelListSection'
import { ProviderCard } from './components/ProviderCard'
import { ModelCallStatsChart } from './components/ModelCallStatsChart'
import { ProviderKeysDrawer } from './components/ProviderKeysDrawer'
import { useModelMarketplace } from './useModelMarketplace'
import './ModelMarketplacePage.css'

export function ModelMarketplacePage() {
  const { t } = useTranslation()
  const { message } = App.useApp()
  const {
    models,
    providers,
    modelsLoading,
    providersLoading,
    modelsError,
    providersError,
    reloadAll,
    reloadModels,
  } = useModelMarketplace()

  const [activeProvider, setActiveProvider] = useState<AiProviderDefinition | null>(null)
  const [modelModalOpen, setModelModalOpen] = useState(false)
  const [editingModel, setEditingModel] = useState<AiModelItem | null>(null)

  useEffect(() => {
    void reloadAll()
  }, [reloadAll])

  const openCreateModal = () => {
    setEditingModel(null)
    setModelModalOpen(true)
  }

  const handleCreateOrUpdate = async (values: ModelFormValues) => {
    try {
      if (editingModel?.id) {
        await aiModelApi.update(editingModel.id, {
          name: values.name,
          type: values.type,
          description: values.description,
          status: values.status,
        })
        message.success(t('settings.models.modelUpdated'))
      } else {
        const { provider_code, ...createPayload } = values
        const created = await aiModelApi.create(createPayload)
        if (provider_code && created.id != null) {
          await aiModelApi.addProvider(created.id, {
            provider_code,
            provider_model_name: createPayload.name,
            status: createPayload.status ?? true,
          })
        }
        message.success(t('settings.models.modelCreated'))
      }
      setModelModalOpen(false)
      setEditingModel(null)
      await reloadModels()
    } catch (err) {
      message.error(err instanceof Error ? err.message : t('common.loadFailed'))
    }
  }

  const handleDelete = (model: AiModelItem) => {
    if (!model.id) return
    Modal.confirm({
      title: t('settings.models.confirmDeleteModel'),
      content: model.name,
      okType: 'danger',
      onOk: async () => {
        try {
          await aiModelApi.delete(model.id!)
          message.success(t('settings.models.modelDeleted'))
          await reloadModels()
        } catch (err) {
          message.error(err instanceof Error ? err.message : t('common.loadFailed'))
        }
      },
    })
  }

  const handleToggleStatus = async (model: AiModelItem, enabled: boolean) => {
    if (!model.id) return
    try {
      await aiModelApi.update(model.id, { status: enabled })
      message.success(t('settings.models.modelUpdated'))
      await reloadModels()
    } catch (err) {
      message.error(err instanceof Error ? err.message : t('common.loadFailed'))
    }
  }

  return (
    <div className="model-marketplace">
      <header className="model-marketplace__head">
        <h2 className="model-marketplace__title">{t('settings.models.title')}</h2>
        <p className="model-marketplace__desc">{t('settings.models.subtitle')}</p>
      </header>

      <MarketplacePanel
        extra={
          <Button type="primary" size="small" onClick={openCreateModal}>
            {t('settings.models.createModel')}
          </Button>
        }
      >
        <ModelListSection
          models={models}
          loading={modelsLoading}
          error={modelsError}
          onRetry={() => void reloadModels()}
          onCreate={openCreateModal}
          onEdit={(model) => {
            setEditingModel(model)
            setModelModalOpen(true)
          }}
          onDelete={handleDelete}
          onToggleStatus={(model, enabled) => void handleToggleStatus(model, enabled)}
        />
      </MarketplacePanel>

      <MarketplacePanel
        title={t('settings.models.vendorsTitle')}
        subtitle={t('settings.models.vendorsSubtitle')}
      >
        <AsyncSection
          loading={providersLoading && providers.length === 0}
          error={providersError}
          onRetry={() => void reloadAll()}
          minHeight={120}
        >
          <div className="model-marketplace__vendor-grid">
            {providers.map((provider) => (
              <ProviderCard
                key={provider.code}
                provider={provider}
                onManageKeys={setActiveProvider}
              />
            ))}
          </div>
        </AsyncSection>
      </MarketplacePanel>

      <MarketplacePanel
        title={t('settings.models.callStats.title')}
        subtitle={t('settings.models.callStats.subtitle')}
      >
        <ModelCallStatsChart />
      </MarketplacePanel>

      <ProviderKeysDrawer
        open={!!activeProvider}
        provider={activeProvider}
        onClose={() => setActiveProvider(null)}
      />

      <ModelFormModal
        open={modelModalOpen}
        editing={editingModel}
        providers={providers}
        onCancel={() => {
          setModelModalOpen(false)
          setEditingModel(null)
        }}
        onSubmit={handleCreateOrUpdate}
      />
    </div>
  )
}
