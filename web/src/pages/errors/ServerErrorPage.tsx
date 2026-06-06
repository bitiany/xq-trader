import { useNavigate, useRouteError } from 'react-router-dom'
import { Button, Result } from 'antd'
import { useTranslation } from 'react-i18next'
import '@/styles/pages.css'

interface ServerErrorPageProps {
  embedded?: boolean
}

export function ServerErrorPage({ embedded = false }: ServerErrorPageProps) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const routeError = useRouteError() as Error | undefined

  return (
    <div className={`error-page ${embedded ? 'error-page--embedded' : ''}`}>
      <Result
        status="500"
        title="500"
        subTitle={routeError?.message || t('errors.serverErrorDesc')}
        extra={[
          <Button key="home" type="primary" onClick={() => navigate('/')}>
            {t('errors.backHome')}
          </Button>,
          <Button key="reload" onClick={() => window.location.reload()}>
            {t('common.retry')}
          </Button>,
        ]}
      />
    </div>
  )
}
