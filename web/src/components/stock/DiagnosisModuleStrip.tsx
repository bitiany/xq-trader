import type { DiagnosisModuleScore } from '@/api/stock'

const MODULE_ORDER = [
  'technical',
  'capital_flow',
  'fundamental',
  'sentiment',
  'industry',
  'institutional',
] as const

interface DiagnosisModuleStripProps {
  modules: DiagnosisModuleScore[]
  activeKey?: string | null
  onModuleClick?: (key: string) => void
}

function formatScore(score: number | null | undefined): string {
  if (score == null || Number.isNaN(score)) return '—'
  return score.toFixed(1)
}

export function DiagnosisModuleStrip({
  modules,
  activeKey,
  onModuleClick,
}: DiagnosisModuleStripProps) {
  const moduleMap = Object.fromEntries(modules.map((module) => [module.key, module]))

  return (
    <div className="diagnosis-module-strip">
      {MODULE_ORDER.map((key) => {
        const module = moduleMap[key]
        if (!module) return null
        const isActive = activeKey === key
        return (
          <button
            key={key}
            type="button"
            className={`diagnosis-module-strip__item${isActive ? ' diagnosis-module-strip__item--active' : ''}`}
            onClick={() => onModuleClick?.(key)}
          >
            <span className="diagnosis-module-strip__label">{module.label}</span>
            <strong className="diagnosis-module-strip__score">{formatScore(module.score)}</strong>
          </button>
        )
      })}
    </div>
  )
}
