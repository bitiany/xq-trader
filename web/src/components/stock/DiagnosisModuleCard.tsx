import { Tag } from 'antd'

import type { ReactNode } from 'react'

import type { DiagnosisModuleScore } from '@/api/stock'

interface DiagnosisModuleCardProps {
  module: DiagnosisModuleScore
  onDetail?: () => void
  children?: ReactNode
}

export function DiagnosisModuleCard({ module, onDetail, children }: DiagnosisModuleCardProps) {
  return (
    <article className="diagnosis-module-card" id={`diagnosis-module-${module.key}`}>
      <header className="diagnosis-module-card__header">
        <div>
          <h3 className="diagnosis-module-card__title">{module.label}</h3>
          <div className="diagnosis-module-card__score">
            {module.score != null ? `${module.score.toFixed(1)}分` : '—'}
            {module.prev_score != null && module.score != null ? (
              <Tag
                className={
                  module.score > module.prev_score
                    ? 'diagnosis-module-card__delta--up'
                    : module.score < module.prev_score
                      ? 'diagnosis-module-card__delta--down'
                      : undefined
                }
              >
                {module.score > module.prev_score ? '↑' : module.score < module.prev_score ? '↓' : '—'}
                {Math.abs(module.score - module.prev_score).toFixed(1)}
              </Tag>
            ) : null}
          </div>
        </div>
        {onDetail ? (
          <button type="button" className="diagnosis-module-card__detail-btn" onClick={onDetail}>
            详情
          </button>
        ) : null}
      </header>
      <div className="diagnosis-module-card__body">{children}</div>
    </article>
  )
}
