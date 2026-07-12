import { createContext, useContext, useState, type ReactNode } from 'react'
import { Outlet, useLocation } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { NAV_ITEMS } from '@/config/navigation'
import './Workspace.css'

interface WorkspaceActionsContextValue {
  setActions: (actions: ReactNode | null) => void
}

const WorkspaceActionsContext = createContext<WorkspaceActionsContextValue>({
  setActions: () => {},
})

export function useWorkspaceActions() {
  return useContext(WorkspaceActionsContext)
}

export function Workspace() {
  const { t } = useTranslation()
  const location = useLocation()
  const [actions, setActions] = useState<ReactNode | null>(null)
  const currentNav = NAV_ITEMS.find(
    (item) => item.path === location.pathname || (item.path !== '/' && location.pathname.startsWith(item.path)),
  )

  return (
    <main className="workspace">
      <div className="workspace__header">
        <h1 className="workspace__title">
          {currentNav ? t(currentNav.labelKey) : t('workspace.defaultTitle')}
        </h1>
        <div className="workspace__actions">
          {actions}
        </div>
      </div>
      <div className="workspace__content">
        <WorkspaceActionsContext.Provider value={{ setActions }}>
          <Outlet />
        </WorkspaceActionsContext.Provider>
      </div>
    </main>
  )
}
