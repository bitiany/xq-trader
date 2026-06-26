import { useTranslation } from 'react-i18next'
import { Empty } from 'antd'

export function EvalRunsTab() {
  const { t } = useTranslation()
  return (
    <div className="factor-placeholder">
      <Empty description={t('factor.evalRuns.placeholder')} />
    </div>
  )
}
