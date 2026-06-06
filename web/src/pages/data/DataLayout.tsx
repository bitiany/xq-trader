import { NavLink, Outlet } from 'react-router-dom'
import { Database, LayoutGrid } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import '@/styles/pages.css'
import './DataLayout.css'

const DATA_NAV = [
  { key: 'overview', path: '/data', labelKey: 'data.nav.overview', icon: LayoutGrid, end: true },
  { key: 'tasks', path: '/data/tasks', labelKey: 'data.nav.tasks', icon: Database, end: false },
] as const

export function DataLayout() {
  const { t } = useTranslation()

  return (
    <div className="data-layout">
      <aside className="data-layout__aside card">
        <h3 className="data-layout__aside-title">{t('pages.data.title')}</h3>
        <nav className="data-layout__nav">
          {DATA_NAV.map((item) => {
            const Icon = item.icon
            return (
              <NavLink
                key={item.key}
                to={item.path}
                end={item.end}
                className={({ isActive }) =>
                  `data-layout__link ${isActive ? 'data-layout__link--active' : ''}`
                }
              >
                <Icon size={14} />
                <span>{t(item.labelKey)}</span>
              </NavLink>
            )
          })}
        </nav>
      </aside>
      <div className="data-layout__content">
        <Outlet />
      </div>
    </div>
  )
}
