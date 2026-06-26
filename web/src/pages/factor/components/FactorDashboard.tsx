import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { Tag, Tooltip } from 'antd'
import type { Factor, FactorCategoryStat } from '@/api'
import { GRADE_BAR_COLOR, GRADE_ORDER, type FactorGrade } from '../utils/factor'

interface FactorDashboardProps {
  factors: Factor[]
  categories: FactorCategoryStat[]
}

export function FactorDashboard({ factors, categories }: FactorDashboardProps) {
  const { t } = useTranslation()

  const stats = useMemo(() => {
    const gradeCount: Record<string, number> = { A: 0, B: 0, C: 0, D: 0 }
    let ungraded = 0
    for (const f of factors) {
      const g = f.factor_grade
      if (g && g in gradeCount) gradeCount[g] += 1
      else ungraded += 1
    }
    const total = factors.length
    const usable = gradeCount.A + gradeCount.B
    const usableRate = total > 0 ? usable / total : 0
    return { total, gradeCount, ungraded, usableRate }
  }, [factors])

  const kpis = [
    { label: t('factor.dashboard.total'), value: String(stats.total) },
    { label: t('factor.dashboard.gradeA'), value: String(stats.gradeCount.A) },
    { label: t('factor.dashboard.gradeB'), value: String(stats.gradeCount.B) },
    { label: t('factor.dashboard.usable'), value: `${(stats.usableRate * 100).toFixed(0)}%` },
    { label: t('factor.dashboard.ungraded'), value: String(stats.ungraded) },
  ]

  const gradeSegments = useMemo(() => {
    const denom = stats.total || 1
    const segs = GRADE_ORDER.map((g) => ({
      grade: g,
      count: stats.gradeCount[g],
      pct: (stats.gradeCount[g] / denom) * 100,
      color: GRADE_BAR_COLOR[g as FactorGrade],
    }))
    segs.push({
      grade: '—' as FactorGrade,
      count: stats.ungraded,
      pct: (stats.ungraded / denom) * 100,
      color: 'var(--border-strong, #d9d9d9)',
    })
    return segs
  }, [stats])

  return (
    <div className="factor-dashboard">
      <div className="factor-kpi-grid">
        {kpis.map((k) => (
          <div className="factor-kpi-card" key={k.label}>
            <span className="factor-kpi-card__label">{k.label}</span>
            <span className="factor-kpi-card__value">{k.value}</span>
          </div>
        ))}
      </div>

      <div className="factor-dist">
        <div className="factor-dist__block">
          <div className="factor-dist__title">{t('factor.dashboard.gradeDist')}</div>
          <div className="factor-grade-bar">
            {gradeSegments.map((s) =>
              s.count > 0 ? (
                <Tooltip key={s.grade} title={`${s.grade}: ${s.count}`}>
                  <div
                    className="factor-grade-bar__seg"
                    style={{ width: `${s.pct}%`, background: s.color }}
                  />
                </Tooltip>
              ) : null,
            )}
          </div>
        </div>

        <div className="factor-dist__block">
          <div className="factor-dist__title">{t('factor.dashboard.categoryDist')}</div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
            {categories.map((c) => (
              <Tag key={c.category} style={{ margin: 0 }}>
                {c.category} · {c.count}
              </Tag>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
