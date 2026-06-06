import { create } from 'zustand'
import { persist } from 'zustand/middleware'

interface LayoutState {
  sideNavCollapsed: boolean
  sideNavHovered: boolean
  agentPanelOpen: boolean
  agentPanelWidth: number
  toggleSideNav: () => void
  setSideNavCollapsed: (collapsed: boolean) => void
  setSideNavHovered: (hovered: boolean) => void
  toggleAgentPanel: () => void
  setAgentPanelOpen: (open: boolean) => void
  setAgentPanelWidth: (width: number) => void
}

export const useLayoutStore = create<LayoutState>()(
  persist(
    (set) => ({
      sideNavCollapsed: true,
      sideNavHovered: false,
      agentPanelOpen: false,
      agentPanelWidth: 380,
      toggleSideNav: () => set((s) => ({ sideNavCollapsed: !s.sideNavCollapsed })),
      setSideNavCollapsed: (collapsed) => set({ sideNavCollapsed: collapsed }),
      setSideNavHovered: (hovered) => set({ sideNavHovered: hovered }),
      toggleAgentPanel: () => set((s) => ({ agentPanelOpen: !s.agentPanelOpen })),
      setAgentPanelOpen: (open) => set({ agentPanelOpen: open }),
      setAgentPanelWidth: (width) => set({ agentPanelWidth: Math.max(300, Math.min(560, width)) }),
    }),
    {
      name: 'xqtrader-layout',
      partialize: (state) => ({
        sideNavCollapsed: state.sideNavCollapsed,
        agentPanelOpen: state.agentPanelOpen,
        agentPanelWidth: state.agentPanelWidth,
      }),
    },
  ),
)
