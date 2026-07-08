import type { DiagnosisSummary } from '@/api/stock'

interface DiagnosisSummaryBoxProps {
  summary: DiagnosisSummary
}

function renderNarrative(narrative: string) {
  const parts = narrative.split(/(【[^】]+】)/g)
  return parts.map((part, index) => {
    if (part.startsWith('【') && part.endsWith('】')) {
      return (
        <strong key={`${part}-${index}`} className="stock-diagnosis__summary-highlight">
          {part}
        </strong>
      )
    }
    return <span key={`${part}-${index}`}>{part}</span>
  })
}

export function DiagnosisSummaryBox({ summary }: DiagnosisSummaryBoxProps) {
  if (summary.narrative) {
    return (
      <div className="stock-diagnosis__summary-box">
        <p>{renderNarrative(summary.narrative)}</p>
      </div>
    )
  }

  if ((summary.bullets?.length ?? 0) > 0) {
    return (
      <div className="stock-diagnosis__summary-box">
        <ul>
          {summary.bullets.map((bullet) => (
            <li key={bullet}>{bullet}</li>
          ))}
        </ul>
      </div>
    )
  }

  return null
}
