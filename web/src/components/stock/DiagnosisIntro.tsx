import { useState } from 'react'
import { useTranslation } from 'react-i18next'

interface DiagnosisIntroProps {
  name: string
  intro: string | null | undefined
}

export function DiagnosisIntro({ name, intro }: DiagnosisIntroProps) {
  const { t } = useTranslation()
  const [expanded, setExpanded] = useState(false)

  if (!intro) return null

  const preview = intro.length > 120 && !expanded ? `${intro.slice(0, 120)}…` : intro

  return (
    <div className="stock-diagnosis__intro">
      <div className="stock-diagnosis__intro-title">{name}</div>
      <p className="stock-diagnosis__intro-text">{preview}</p>
      {intro.length > 120 ? (
        <button
          type="button"
          className="stock-diagnosis__intro-toggle"
          onClick={() => setExpanded((value) => !value)}
        >
          {expanded ? t('stock.news.collapse') : t('stock.news.expand')}
        </button>
      ) : null}
    </div>
  )
}
