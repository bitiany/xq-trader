import type { LucideIcon } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import '@/styles/pages.css'

interface RoutePlaceholderProps {
  pageKey?: string
  icon: LucideIcon
  titleKey?: string
  descriptionKey?: string
}

export function RoutePlaceholder({ pageKey, icon: Icon, titleKey, descriptionKey }: RoutePlaceholderProps) {
  const { t } = useTranslation()

  return (
    <div className="page-placeholder">
      <div className="page-placeholder__icon">
        <Icon size={24} />
      </div>
      <h2>{t(titleKey ?? `pages.${pageKey}.title`)}</h2>
      <p>{t(descriptionKey ?? `pages.${pageKey}.description`)}</p>
    </div>
  )
}
