import { Empty } from 'antd'
import { useTranslation } from 'react-i18next'

import type { DiagnosisModuleScore } from '@/api/stock'
import { DiagnosisModuleCard } from '@/components/stock/DiagnosisModuleCard'
import { translateDiagnosisTerm } from '@/utils/diagnosisTechnical'

interface TechnicalModuleCardProps {
  module: DiagnosisModuleScore
  onDetail?: () => void
}

export function TechnicalModuleCard({ module, onDetail }: TechnicalModuleCardProps) {
  const { t } = useTranslation()
  const detail = module.detail ?? {}
  const signals = (detail.signals as Array<{ name: string; value: string }> | undefined) ?? []

  const horizons = [
    { key: 'short', label: t('stock.diagnosis.technical.horizon.short'), value: detail.short_label },
    { key: 'mid', label: t('stock.diagnosis.technical.horizon.mid'), value: detail.mid_label },
    { key: 'long', label: t('stock.diagnosis.technical.horizon.long'), value: detail.long_label },
  ]

  return (
    <DiagnosisModuleCard module={module} onDetail={onDetail}>
      <div className="diagnosis-module-card__badges">
        {horizons.map((item) => (
          <span key={item.key} className="diagnosis-badge">
            {item.label} {translateDiagnosisTerm(item.value as string, t)}
          </span>
        ))}
      </div>
      {signals.length > 0 ? (
        <table className="diagnosis-signal-table">
          <thead>
            <tr>
              <th>{t('stock.diagnosis.technical.indicator')}</th>
              <th>{t('stock.diagnosis.technical.signalLabel')}</th>
            </tr>
          </thead>
          <tbody>
            {signals.map((signal) => (
              <tr key={signal.name}>
                <td>{signal.name}</td>
                <td>{translateDiagnosisTerm(signal.value, t)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t('stock.diagnosis.technical.noSignals')} />
      )}
      <div className="diagnosis-module-card__meta">
        <span>
          {t('stock.diagnosis.technical.support')}{' '}
          {detail.support != null ? Number(detail.support).toFixed(2) : '—'}
        </span>
        <span>
          {t('stock.diagnosis.technical.resistance')}{' '}
          {detail.resistance != null ? Number(detail.resistance).toFixed(2) : '—'}
        </span>
      </div>
    </DiagnosisModuleCard>
  )
}
