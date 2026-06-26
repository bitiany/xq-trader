import { useTranslation } from 'react-i18next'
import { Empty } from 'antd'

export function CorrelationTab() {
  const { t } = useTranslation()
  return (
    <div className="factor-placeholder">
      <Empty description={t('factor.correlation.placeholder')} />
    </div>
  )
}
