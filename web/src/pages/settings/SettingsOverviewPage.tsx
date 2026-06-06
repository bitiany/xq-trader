import { useTranslation } from 'react-i18next'
import '@/styles/pages.css'

export function SettingsOverviewPage() {
  const { t } = useTranslation()

  return (
    <div className="card">
      <div className="card__header">
        <h3 className="card__title">{t('settings.nav.overview')}</h3>
      </div>
      <p className="settings-desc">{t('pages.settings.description')}</p>
    </div>
  )
}
