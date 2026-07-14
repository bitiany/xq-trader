import { createContext, useContext, type ReactNode } from 'react'

interface WorkspaceActionsContextValue {
  setActions: (actions: ReactNode | null) => void
}

export const WorkspaceActionsContext = createContext<WorkspaceActionsContextValue>({
  setActions: () => {},
})

export function useWorkspaceActions() {
  return useContext(WorkspaceActionsContext)
}
