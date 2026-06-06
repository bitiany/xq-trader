import type { ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { canActivate } from '@/router/auth'

interface AuthGuardProps {
  children: ReactNode
  /** 预留：路由所需角色 */
  roles?: string[]
}

export function AuthGuard({ children, roles }: AuthGuardProps) {
  const location = useLocation()

  if (!canActivate(roles)) {
    // TODO: 替换为真实登录页路径
    return <Navigate to="/login" state={{ from: location.pathname }} replace />
  }

  return children
}
