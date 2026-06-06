import type { CSSProperties } from 'react'
import { useLayoutStore } from '@/stores/layoutStore'
import { AgentPanel } from '@/components/layout/AgentPanel'
import { SideNav } from '@/components/layout/SideNav'
import { StatusBar } from '@/components/layout/StatusBar'
import { TopBar } from '@/components/layout/TopBar'
import { Workspace } from '@/components/layout/Workspace'
import '@/styles/layout.css'

export function AppLayout() {
  const agentPanelOpen = useLayoutStore((s) => s.agentPanelOpen)
  const agentPanelWidth = useLayoutStore((s) => s.agentPanelWidth)
  const sideNavCollapsed = useLayoutStore((s) => s.sideNavCollapsed)
  const sideNavHovered = useLayoutStore((s) => s.sideNavHovered)

  const sideNavExpanded = !sideNavCollapsed || sideNavHovered

  return (
    <div
      className="app-shell"
      data-agent-open={agentPanelOpen}
      data-sidenav-expanded={sideNavExpanded}
      style={{ '--agent-width': `${agentPanelWidth}px` } as CSSProperties}
    >
      <TopBar />
      <div className="app-body">
        <SideNav />
        <Workspace />
        {agentPanelOpen && <AgentPanel />}
      </div>
      <StatusBar />
    </div>
  )
}
