import { useMemo } from 'react'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Crosshair, ListChecks, History } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import '@/styles/pages.css'

interface StrategyTab {
  key: string
  path: string
  labelKey: string
  icon: LucideIcon
}

const TABS: StrategyTab[] = [
  { key: 'workbench', path: '/strategy/workbench', labelKey: 'strategy.workbench', icon: Crosshair },
  { key: 'list', path: '/strategy/list', labelKey: 'strategy.management', icon: ListChecks },
  { key: 'history', path: '/strategy/history', labelKey: 'strategy.history', icon: History },
]

export function StrategyLayout() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const location = useLocation()

  const activeKey = useMemo(() => {
    const match = TABS.find((tab) => location.pathname.startsWith(tab.path))
    return match?.key ?? 'workbench'
  }, [location.pathname])

  return (
    <div className="strategy-layout">
      <div className="strategy-layout__tabs" role="tablist">
        {TABS.map((tab) => {
          const Icon = tab.icon
          const isActive = activeKey === tab.key
          return (
            <button
              key={tab.key}
              type="button"
              role="tab"
              aria-selected={isActive}
              className={`strategy-layout__tab${isActive ? ' strategy-layout__tab--active' : ''}`}
              onClick={() => navigate(tab.path)}
            >
              <Icon size={14} />
              <span>{t(tab.labelKey)}</span>
            </button>
          )
        })}
      </div>
      <div className="strategy-layout__content">
        <Outlet />
      </div>
    </div>
  )
}
