import { useNavigate } from 'react-router-dom'
import { Button, Result } from 'antd'
import { useTranslation } from 'react-i18next'
import '@/styles/pages.css'

export function NotFoundPage() {
  const { t } = useTranslation()
  const navigate = useNavigate()

  return (
    <div className="error-page">
      <Result
        status="404"
        title="404"
        subTitle={t('errors.notFoundDesc')}
        extra={
          <Button type="primary" onClick={() => navigate('/')}>
            {t('errors.backHome')}
          </Button>
        }
      />
    </div>
  )
}
