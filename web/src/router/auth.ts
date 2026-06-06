/**
 * 路由鉴权守卫（预留）
 *
 * TODO: 接入登录态校验、角色权限、Token 过期跳转等
 */
export interface AuthGuardContext {
  isAuthenticated: boolean
  /** 预留：用户角色列表 */
  roles: string[]
}

export function checkAuth(): AuthGuardContext {
  // TODO: 从 auth store / token 解析真实鉴权状态
  return {
    isAuthenticated: true,
    roles: ['admin'],
  }
}

export function canActivate(requiredRoles?: string[]): boolean {
  const auth = checkAuth()
  if (!auth.isAuthenticated) {
    return false
  }
  if (requiredRoles?.length) {
    // TODO: 基于 requiredRoles 做 RBAC 校验
    void requiredRoles
  }
  return true
}
