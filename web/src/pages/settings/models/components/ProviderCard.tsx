import { KeyRound } from 'lucide-react'
import { Button, Tooltip } from 'antd'
import { useTranslation } from 'react-i18next'
import type { AiProviderDefinition } from '@/api/ai/providers'
import { getProviderBrandColor } from '@/config/modelVendors'
import './ProviderCard.css'

interface ProviderCardProps {
  provider: AiProviderDefinition
  onManageKeys: (provider: AiProviderDefinition) => void
}

export function ProviderCard({ provider, onManageKeys }: ProviderCardProps) {
  const { t } = useTranslation()
  const brandColor = getProviderBrandColor(provider.code)
  const desc = provider.remark || provider.api_url || provider.code

  return (
    <article className="provider-card card">
      <div className="provider-card__header">
        <div
          className="provider-card__logo"
          style={{ background: `${brandColor}22`, color: brandColor }}
        >
          {provider.icon ?? provider.code.slice(0, 2).toUpperCase()}
        </div>
        <div className="provider-card__meta">
          <h4 className="provider-card__name">{provider.name}</h4>
          <p className="provider-card__desc" title={desc}>
            {desc}
          </p>
        </div>
        <Tooltip title={t('settings.models.manageKeys')}>
          <Button
            type="text"
            size="small"
            className="provider-card__key-btn"
            icon={<KeyRound size={14} />}
            onClick={() => onManageKeys(provider)}
          />
        </Tooltip>
      </div>
    </article>
  )
}
