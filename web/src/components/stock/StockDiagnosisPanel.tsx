import { Empty } from 'antd'
import { Sparkles } from 'lucide-react'
import { useTranslation } from 'react-i18next'

import type { StockDiagnosisResponse } from '@/api/stock'

interface StockDiagnosisPanelProps {
  data?: StockDiagnosisResponse
}

export function StockDiagnosisPanel({ data }: StockDiagnosisPanelProps) {
  const { t } = useTranslation()

  return (
    <div className="stock-panel card stock-diagnosis">
      <div className="stock-diagnosis__icon">
        <Sparkles size={28} />
      </div>
      <h3>{t('stock.diagnosis.title')}</h3>
      <p>{data?.message ?? t('stock.diagnosis.placeholder')}</p>
      <Empty description={t('stock.diagnosis.comingSoon')} image={Empty.PRESENTED_IMAGE_SIMPLE} />
    </div>
  )
}
