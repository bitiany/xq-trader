import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'

import type { WatermarkSummaryItem } from '@/api/data'
import '@/styles/data.css'

const DAY_MS = 24 * 60 * 60 * 1000
const AXIS_PADDING_DAYS = 5
const MIN_BAR_PCT = 0.8

function parseDate(value: string | null): number | null {
  if (!value) {
    return null
  }
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value)
  if (match) {
    const year = Number(match[1])
    const month = Number(match[2]) - 1
    const day = Number(match[3])
    return new Date(year, month, day).getTime()
  }
  const time = Date.parse(value)
  return Number.isNaN(time) ? null : time
}

function formatAxisDate(value: number): string {
  const date = new Date(value)
  return `${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`
}

function buildAxisTicks(axisStart: number, axisEnd: number): number[] {
  const spanDays = Math.max(Math.round((axisEnd - axisStart) / DAY_MS), 1)
  const step = Math.max(Math.ceil(spanDays / 6), 1)
  const ticks: number[] = []
  const cursor = new Date(axisStart)
  cursor.setHours(0, 0, 0, 0)
  while (cursor.getTime() <= axisEnd) {
    ticks.push(cursor.getTime())
    cursor.setDate(cursor.getDate() + step)
  }
  if (ticks[ticks.length - 1] !== axisEnd) {
    ticks.push(axisEnd)
  }
  return ticks
}

interface WatermarkRangeChartProps {
  items: WatermarkSummaryItem[]
  referenceTradeDate: string | null
}

export function WatermarkRangeChart({ items, referenceTradeDate }: WatermarkRangeChartProps) {
  const { t, i18n } = useTranslation()
  const isZh = i18n.language.startsWith('zh')

  const chartModel = useMemo(() => {
    const datedItems = items
      .filter((item) => item.min_date && item.max_date)
      .sort((a, b) => a.data_type.localeCompare(b.data_type))

    if (datedItems.length === 0) {
      return null
    }

    const referenceTime = parseDate(referenceTradeDate)
    const allTimes = datedItems
      .flatMap((item) => [parseDate(item.min_date), parseDate(item.max_date)])
      .filter((value): value is number => value != null)

    const globalMin = Math.min(...allTimes)
    const globalMax = Math.max(...allTimes)
    const axisStart = globalMin - AXIS_PADDING_DAYS * DAY_MS
    const axisEnd = referenceTime != null ? Math.max(globalMax, referenceTime) : globalMax
    const span = Math.max(axisEnd - axisStart, DAY_MS)

    const toPct = (time: number) => ((time - axisStart) / span) * 100
    const referencePct =
      referenceTime != null ? Math.min(Math.max(toPct(referenceTime), 0), 100) : null

    const rows = datedItems.map((item) => {
      const minTime = parseDate(item.min_date)!
      const maxTime = parseDate(item.max_date)!
      const lagged = item.lag_days != null && item.lag_days > 0
      const left = toPct(minTime)
      const width = Math.max(toPct(maxTime) - left, MIN_BAR_PCT)
      const lagLeft = toPct(maxTime)
      const lagWidth =
        lagged && referenceTime != null && maxTime < referenceTime
          ? Math.max(toPct(referenceTime) - lagLeft, 0)
          : 0

      return {
        key: item.data_type,
        label: isZh ? item.display_name : item.display_name_en,
        rangeText: `${item.min_date} ~ ${item.max_date}`,
        codeCount: item.code_count,
        lagDays: item.lag_days,
        lagged,
        bar: { left, width },
        lag: lagWidth > 0 ? { left: lagLeft, width: lagWidth } : null,
      }
    })

    return {
      axisStart,
      axisEnd,
      referencePct,
      referenceTradeDate,
      ticks: buildAxisTicks(axisStart, axisEnd),
      rows,
    }
  }, [items, isZh, referenceTradeDate])

  if (!chartModel) {
    return <div className="data-empty">{t('data.watermark.empty')}</div>
  }

  const { referencePct, ticks, rows } = chartModel

  return (
    <div className="watermark-chart">
      <div className="watermark-chart__legend">
        <span className="watermark-chart__legend-item">
          <i className="watermark-chart__swatch watermark-chart__swatch--range" />
          {t('data.watermark.rangeLegend')}
        </span>
        <span className="watermark-chart__legend-item">
          <i className="watermark-chart__swatch watermark-chart__swatch--lag-gap" />
          {t('data.watermark.lagGapLegend')}
        </span>
        <span className="watermark-chart__legend-item">
          <i className="watermark-chart__swatch watermark-chart__swatch--today" />
          {t('data.watermark.todayLegend')}
          {chartModel.referenceTradeDate ? ` (${chartModel.referenceTradeDate})` : ''}
        </span>
      </div>

      <div className="watermark-chart__body">
        <div className="watermark-chart__rows">
          {referencePct != null ? (
            <div className="watermark-chart__today-line" style={{ left: `${referencePct}%` }} />
          ) : null}
          {rows.map((row) => (
            <div key={row.key} className="watermark-chart__row">
              <div className="watermark-chart__label-col">
                <div className="watermark-chart__label" title={row.key}>
                  {row.label}
                </div>
                <div className="watermark-chart__sublabel">
                  {row.rangeText}
                  {row.lagDays != null && row.lagDays > 0
                    ? ` · ${t('data.watermark.lagDays', { count: row.lagDays })}`
                    : ''}
                </div>
              </div>
              <div className="watermark-chart__track" title={row.rangeText}>
                <div
                  className={`watermark-chart__bar ${row.lagged ? 'watermark-chart__bar--lagged' : 'watermark-chart__bar--fresh'}`}
                  style={{ left: `${row.bar.left}%`, width: `${row.bar.width}%` }}
                />
                {row.lag ? (
                  <div
                    className="watermark-chart__lag-gap"
                    style={{ left: `${row.lag.left}%`, width: `${row.lag.width}%` }}
                  />
                ) : null}
              </div>
              <div className="watermark-chart__stat">{row.codeCount.toLocaleString()}</div>
            </div>
          ))}
        </div>

        <div className="watermark-chart__axis">
          {ticks.map((tick) => (
            <span
              key={tick}
              className="watermark-chart__axis-tick"
              style={{ left: `${((tick - chartModel.axisStart) / (chartModel.axisEnd - chartModel.axisStart)) * 100}%` }}
            >
              {formatAxisDate(tick)}
            </span>
          ))}
        </div>
      </div>
    </div>
  )
}
