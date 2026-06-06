import { Outlet, useLocation } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { NAV_ITEMS } from '@/config/navigation'
import './Workspace.css'

export function Workspace() {
  const { t } = useTranslation()
  const location = useLocation()
  const currentNav = NAV_ITEMS.find(
    (item) => item.path === location.pathname || (item.path !== '/' && location.pathname.startsWith(item.path)),
  )

  return (
    <main className="workspace">
      <div className="workspace__header">
        <h1 className="workspace__title">
          {currentNav ? t(currentNav.labelKey) : t('workspace.defaultTitle')}
        </h1>
        <div className="workspace__tabs">
          <button type="button" className="workspace__tab workspace__tab--active">
            {t('workspace.tabMain')}
          </button>
          <button type="button" className="workspace__tab">
            {t('workspace.tabDetail')}
          </button>
          <button type="button" className="workspace__tab">
            {t('workspace.tabLog')}
          </button>
        </div>
      </div>
      <div className="workspace__content">
        <Outlet />
      </div>
    </main>
  )
}
