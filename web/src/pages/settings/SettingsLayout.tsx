import { NavLink, Outlet } from 'react-router-dom'
import { Bot, FlaskConical, Settings } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import '@/styles/pages.css'
import './SettingsLayout.css'

const SETTINGS_NAV = [
  { key: 'overview', path: '/settings', labelKey: 'settings.nav.overview', icon: Settings, end: true },
  { key: 'models', path: '/settings/models', labelKey: 'settings.nav.models', icon: Bot, end: false },
  { key: 'apiTest', path: '/settings/api-test', labelKey: 'settings.nav.apiTest', icon: FlaskConical, end: false },
] as const

export function SettingsLayout() {
  const { t } = useTranslation()

  return (
    <div className="settings-layout">
      <aside className="settings-layout__aside card">
        <h3 className="settings-layout__aside-title">{t('pages.settings.title')}</h3>
        <nav className="settings-layout__nav">
          {SETTINGS_NAV.map((item) => {
            const Icon = item.icon
            return (
              <NavLink
                key={item.key}
                to={item.path}
                end={item.end}
                className={({ isActive }) =>
                  `settings-layout__link ${isActive ? 'settings-layout__link--active' : ''}`
                }
              >
                <Icon size={14} />
                <span>{t(item.labelKey)}</span>
              </NavLink>
            )
          })}
        </nav>
      </aside>
      <div className="settings-layout__content">
        <Outlet />
      </div>
    </div>
  )
}
