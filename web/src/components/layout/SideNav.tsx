import { NavLink } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { NAV_ITEMS } from '@/config/navigation'
import { useLayoutStore } from '@/stores/layoutStore'
import './SideNav.css'

export function SideNav() {
  const { t } = useTranslation()
  const sideNavCollapsed = useLayoutStore((s) => s.sideNavCollapsed)
  const sideNavHovered = useLayoutStore((s) => s.sideNavHovered)
  const setSideNavHovered = useLayoutStore((s) => s.setSideNavHovered)
  const isExpanded = !sideNavCollapsed || sideNavHovered

  return (
    <aside
      className="sidenav"
      data-collapsed={sideNavCollapsed}
      data-expanded={isExpanded}
      onMouseEnter={() => sideNavCollapsed && setSideNavHovered(true)}
      onMouseLeave={() => setSideNavHovered(false)}
    >
      <nav className="sidenav__nav" aria-label="Main navigation">
        {NAV_ITEMS.map((item) => {
          const Icon = item.icon
          return (
            <NavLink
              key={item.id}
              to={item.path}
              end={item.path === '/'}
              className={({ isActive }) =>
                `sidenav__item ${isActive ? 'sidenav__item--active' : ''}`
              }
              title={t(item.labelKey)}
            >
              <span className="sidenav__icon-wrap">
                <Icon size={16} strokeWidth={1.75} />
              </span>
              <span className="sidenav__label">{t(item.labelKey)}</span>
              {item.badge && (
                <span
                  className={`sidenav__badge ${isExpanded ? 'sidenav__badge--pill' : 'sidenav__badge--dot'}`}
                  aria-label={item.badge}
                >
                  {isExpanded ? item.badge : null}
                </span>
              )}
            </NavLink>
          )
        })}
      </nav>

      <div className="sidenav__footer">
        <div className="sidenav__env">
          <span className="sidenav__env-dot" />
          <span className="sidenav__env-text">{t('settings.productionEnv')}</span>
        </div>
      </div>
    </aside>
  )
}
