import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Button, Select, Space, Tabs, Tooltip } from 'antd'
import { FlaskConical, GitMerge, Grid3x3, Library, RefreshCw } from 'lucide-react'
import {
  fetchAllFactors,
  fetchFactorCategories,
  fetchPools,
} from '@/api'
import { AsyncSection } from '@/components/common/AsyncSection'
import { useRequest } from '@/hooks/useRequest'
import { FactorDashboard } from './components/FactorDashboard'
import { FactorLibraryTab } from './components/FactorLibraryTab'
import { CompositeTab } from './components/CompositeTab'
import { CorrelationTab } from './components/CorrelationTab'
import { EvalRunsTab } from './components/EvalRunsTab'
import { FactorDetailDrawer } from './components/FactorDetailDrawer'
import '@/styles/factor.css'

const DEFAULT_POOL = 'all'

export function FactorWorkbenchPage() {
  const { t } = useTranslation()
  const [poolId, setPoolId] = useState<string>(DEFAULT_POOL)
  const [selectedFactorId, setSelectedFactorId] = useState<string | null>(null)
  const [drawerOpen, setDrawerOpen] = useState(false)

  const poolsReq = useRequest(() => fetchPools(true))
  const categoriesReq = useRequest(() => fetchFactorCategories())
  const factorsReq = useRequest(() => fetchAllFactors())

  const pools = useMemo(() => poolsReq.data ?? [], [poolsReq.data])
  const categories = useMemo(() => categoriesReq.data ?? [], [categoriesReq.data])
  const factors = useMemo(() => factorsReq.data ?? [], [factorsReq.data])

  const poolOptions = useMemo(() => {
    if (pools.length === 0) return [{ value: DEFAULT_POOL, label: '全A股 (all)' }]
    return pools.map((p) => ({ value: p.pool_id, label: `${p.pool_name} (${p.pool_id})` }))
  }, [pools])

  const openDetail = (factorId: string) => {
    setSelectedFactorId(factorId)
    setDrawerOpen(true)
  }

  const handleRefresh = () => {
    void categoriesReq.reload()
    void factorsReq.reload()
  }

  const tabItems = [
    {
      key: 'library',
      label: <Space size={4}><Library size={13} />{t('factor.tabs.library')}</Space>,
      children: <FactorLibraryTab categories={categories} onSelectFactor={openDetail} />,
    },
    {
      key: 'composite',
      label: <Space size={4}><GitMerge size={13} />{t('factor.tabs.composite')}</Space>,
      children: <CompositeTab factors={factors} onSelectFactor={openDetail} />,
    },
    {
      key: 'correlation',
      label: <Space size={4}><Grid3x3 size={13} />{t('factor.tabs.correlation')}</Space>,
      children: <CorrelationTab />,
    },
    {
      key: 'evalRuns',
      label: <Space size={4}><FlaskConical size={13} />{t('factor.tabs.evalRuns')}</Space>,
      children: <EvalRunsTab />,
    },
  ]

  return (
    <div className="factor-page" data-component="Factor Workbench">
      <div className="factor-page__header">
        <div className="factor-page__title-area">
          <span className="factor-page__title">{t('factor.title')}</span>
          <Space size={4}>
            <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>{t('factor.pool')}</span>
            <Select
              size="small"
              style={{ width: 200 }}
              value={poolId}
              onChange={setPoolId}
              options={poolOptions}
              loading={poolsReq.loading}
            />
          </Space>
        </div>
        <Space>
          <Tooltip title={t('factor.evalRuns.placeholder')}>
            <Button size="small" disabled>{t('factor.runEvaluate')}</Button>
          </Tooltip>
          <Tooltip title={t('factor.evalRuns.placeholder')}>
            <Button size="small" disabled>{t('factor.runSynthesize')}</Button>
          </Tooltip>
          <Button size="small" icon={<RefreshCw size={13} />} onClick={handleRefresh}>
            {t('factor.refresh')}
          </Button>
        </Space>
      </div>

      <div className="factor-page__content">
        <AsyncSection loading={factorsReq.loading} error={factorsReq.error} onRetry={factorsReq.reload}>
          <FactorDashboard factors={factors} categories={categories} />
        </AsyncSection>

        <Tabs className="factor-tabs" items={tabItems} size="small" defaultActiveKey="library" />
      </div>

      <FactorDetailDrawer
        factorId={selectedFactorId}
        poolId={poolId}
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
      />
    </div>
  )
}
