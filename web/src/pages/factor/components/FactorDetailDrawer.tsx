import { useEffect, useMemo, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { Descriptions, Drawer, Empty, Tag } from 'antd'
import * as echarts from 'echarts'
import {
  fetchFactorDetail,
  fetchFactorStats,
  fetchFactorStatsLatest,
  type FactorStats,
} from '@/api'
import { AsyncSection } from '@/components/common/AsyncSection'
import { useRequest } from '@/hooks/useRequest'
import { GRADE_COLOR, formatNum, formatPct, type FactorGrade } from '../utils/factor'

interface FactorDetailDrawerProps {
  factorId: string | null
  poolId: string
  open: boolean
  onClose: () => void
}

function IcTrendChart({ series }: { series: FactorStats[] }) {
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!ref.current) return
    const chart = echarts.init(ref.current)
    const sorted = [...series].sort((a, b) => a.calc_date.localeCompare(b.calc_date))
    chart.setOption({
      grid: { top: 24, right: 16, bottom: 28, left: 48 },
      tooltip: { trigger: 'axis' },
      xAxis: { type: 'category', data: sorted.map((s) => s.calc_date) },
      yAxis: { type: 'value', scale: true },
      series: [
        {
          name: 'IC',
          type: 'line',
          smooth: true,
          showSymbol: false,
          data: sorted.map((s) => s.ic_mean),
          areaStyle: { opacity: 0.08 },
          lineStyle: { width: 2 },
        },
      ],
    })
    const onResize = () => chart.resize()
    window.addEventListener('resize', onResize)
    return () => {
      window.removeEventListener('resize', onResize)
      chart.dispose()
    }
  }, [series])

  return <div ref={ref} style={{ width: '100%', height: 220 }} />
}

function FactorDetailContent({ factorId, poolId }: { factorId: string; poolId: string }) {
  const { t } = useTranslation()

  const detailReq = useRequest(() => fetchFactorDetail(factorId), { deps: [factorId] })
  const latestReq = useRequest(() => fetchFactorStatsLatest(factorId, poolId), { deps: [factorId, poolId] })
  const seriesReq = useRequest(() => fetchFactorStats(factorId, { pool_id: poolId, limit: 104 }), {
    deps: [factorId, poolId],
  })

  const detail = detailReq.data
  const latest = latestReq.data
  const series = useMemo(() => seriesReq.data ?? [], [seriesReq.data])

  return (
    <div>
      <div className="factor-detail-section">
        <div className="factor-detail-section__title">{t('factor.detail.metadata')}</div>
        <AsyncSection loading={detailReq.loading} error={detailReq.error} onRetry={detailReq.reload}>
          {detail && (
            <Descriptions size="small" column={1} bordered>
              <Descriptions.Item label="ID">
                <span style={{ fontFamily: 'var(--font-mono)' }}>{detail.factor_id}</span>
              </Descriptions.Item>
              <Descriptions.Item label={t('factor.library.category')}>{detail.category}</Descriptions.Item>
              <Descriptions.Item label={t('factor.library.direction')}>{detail.direction}</Descriptions.Item>
              <Descriptions.Item label={t('factor.library.grade')}>
                {detail.factor_grade ? (
                  <Tag color={GRADE_COLOR[detail.factor_grade as FactorGrade]}>{detail.factor_grade}</Tag>
                ) : '—'}
              </Descriptions.Item>
              <Descriptions.Item label={t('factor.library.status')}>{detail.status}</Descriptions.Item>
              {detail.composite_factor_ids && (
                <Descriptions.Item label={t('factor.detail.lineage')}>
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12 }}>
                    {detail.composite_factor_ids}
                  </span>
                </Descriptions.Item>
              )}
              {detail.description && (
                <Descriptions.Item label="">{detail.description}</Descriptions.Item>
              )}
            </Descriptions>
          )}
        </AsyncSection>
      </div>

      <div className="factor-detail-section">
        <div className="factor-detail-section__title">
          {t('factor.detail.snapshot')} · {poolId}
        </div>
        <AsyncSection loading={latestReq.loading} error={latestReq.error} onRetry={latestReq.reload}>
          {latest ? (
            <Descriptions size="small" column={2} bordered>
              <Descriptions.Item label={t('factor.detail.icMean')}>{formatNum(latest.ic_mean)}</Descriptions.Item>
              <Descriptions.Item label={t('factor.detail.icir')}>{formatNum(latest.icir)}</Descriptions.Item>
              <Descriptions.Item label={t('factor.detail.icWinRate')}>{formatPct(latest.ic_win_rate)}</Descriptions.Item>
              <Descriptions.Item label={t('factor.detail.icStd')}>{formatNum(latest.ic_std)}</Descriptions.Item>
              <Descriptions.Item label={t('factor.detail.longShortAnnual')}>{formatPct(latest.long_short_annual_ret)}</Descriptions.Item>
              <Descriptions.Item label={t('factor.detail.longShortSharpe')}>{formatNum(latest.long_short_sharpe)}</Descriptions.Item>
              <Descriptions.Item label={t('factor.detail.turnover')}>{formatPct(latest.turnover)}</Descriptions.Item>
              <Descriptions.Item label={t('factor.detail.decayHalfLife')}>{formatNum(latest.decay_half_life, 1)}</Descriptions.Item>
              <Descriptions.Item label={t('factor.detail.coverage')}>{formatPct(latest.coverage)}</Descriptions.Item>
            </Descriptions>
          ) : (
            !latestReq.loading && <Empty description={t('factor.detail.noSnapshot')} />
          )}
        </AsyncSection>
      </div>

      <div className="factor-detail-section">
        <div className="factor-detail-section__title">{t('factor.detail.icTrend')} · {poolId}</div>
        <AsyncSection loading={seriesReq.loading} error={seriesReq.error} onRetry={seriesReq.reload}>
          {series.length > 0 ? (
            <IcTrendChart series={series} />
          ) : (
            !seriesReq.loading && <Empty description={t('factor.detail.noTrend')} />
          )}
        </AsyncSection>
      </div>
    </div>
  )
}

export function FactorDetailDrawer({ factorId, poolId, open, onClose }: FactorDetailDrawerProps) {
  return (
    <Drawer
      title={factorId ?? ''}
      placement="right"
      width={720}
      open={open}
      onClose={onClose}
      destroyOnHidden
    >
      {factorId && <FactorDetailContent factorId={factorId} poolId={poolId} />}
    </Drawer>
  )
}
