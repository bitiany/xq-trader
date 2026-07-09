import type { ReactNode } from 'react'
import { Alert, Button, Spin } from 'antd'
import { useTranslation } from 'react-i18next'

interface StockPanelStateProps {
  loading?: boolean
  error?: string | null
  onRetry?: () => void
  children?: ReactNode
}

/** 个股 Tab 面板统一 loading / error 态，避免失败被伪装成 Empty */
export function StockPanelState({ loading = false, error = null, onRetry, children }: StockPanelStateProps) {
  const { t } = useTranslation()

  if (loading && children == null) {
    return (
      <div className="stock-panel card stock-panel--loading">
        <Spin description={t('common.loading')} />
      </div>
    )
  }

  if (error && children == null) {
    return (
      <div className="stock-panel card">
        <Alert
          type="error"
          showIcon
          title={t('common.loadFailed')}
          description={error}
          action={
            onRetry ? (
              <Button size="small" onClick={onRetry}>
                {t('common.retry')}
              </Button>
            ) : undefined
          }
        />
      </div>
    )
  }

  return <>{children}</>
}
