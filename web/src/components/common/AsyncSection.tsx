import type { ReactNode } from 'react'
import { Alert, Button, Spin } from 'antd'
import { useTranslation } from 'react-i18next'
import './AsyncSection.css'

interface AsyncSectionProps {
  loading?: boolean
  error?: string | null
  onRetry?: () => void
  minHeight?: number
  children?: ReactNode
}

export function AsyncSection({
  loading = false,
  error = null,
  onRetry,
  minHeight = 120,
  children,
}: AsyncSectionProps) {
  const { t } = useTranslation()
  const hasContent = children != null

  if (loading && !hasContent) {
    return (
      <div className="async-section async-section--loading" style={{ minHeight }}>
        <Spin description={t('common.loading')} />
      </div>
    )
  }

  return (
    <div className="async-section">
      {error && (
        <Alert
          type="error"
          showIcon
          message={t('common.loadFailed')}
          description={error}
          action={
            onRetry ? (
              <Button size="small" onClick={onRetry}>
                {t('common.retry')}
              </Button>
            ) : undefined
          }
          className="async-section__alert"
        />
      )}
      {hasContent && (
        <div className="async-section__body" style={{ minHeight: loading ? minHeight : undefined }}>
          {loading && (
            <div className="async-section__overlay">
              <Spin size="small" />
            </div>
          )}
          {children}
        </div>
      )}
    </div>
  )
}
