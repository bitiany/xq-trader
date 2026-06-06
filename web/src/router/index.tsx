import { createBrowserRouter } from 'react-router-dom'
import { AppLayout } from '@/layouts/AppLayout'
import { DataLayout } from '@/pages/data/DataLayout'
import { DataOverviewPage } from '@/pages/data/DataOverviewPage'
import { DataTasksPage } from '@/pages/data/DataTasksPage'
import { NotFoundPage } from '@/pages/errors/NotFoundPage'
import { ServerErrorPage } from '@/pages/errors/ServerErrorPage'
import { BacktestPage } from '@/pages/backtest/BacktestPage'
import { RoutePlaceholder } from '@/pages/RoutePlaceholder'
import { StockDetailPage } from '@/pages/stock/StockDetailPage'
import { ApiTestPage } from '@/pages/settings/ApiTestPage'
import { ModelMarketplacePage } from '@/pages/settings/models/ModelMarketplacePage'
import { SettingsLayout } from '@/pages/settings/SettingsLayout'
import { SettingsOverviewPage } from '@/pages/settings/SettingsOverviewPage'
import { AuthGuard } from '@/router/AuthGuard'
import { RouteErrorBoundary } from '@/router/RouteErrorBoundary'
import { Activity } from 'lucide-react'

export const router = createBrowserRouter([
  {
    path: '/',
    element: (
      <AuthGuard>
        <RouteErrorBoundary>
          <AppLayout />
        </RouteErrorBoundary>
      </AuthGuard>
    ),
    errorElement: <ServerErrorPage />,
    children: [
      { path: 'stock/:symbol', element: <StockDetailPage /> },
      { path: 'backtest', element: <BacktestPage /> },
      { path: 'backtest/:symbol', element: <BacktestPage /> },
      { path: 'data', element: <DataLayout />, children: [
        { index: true, element: <DataOverviewPage /> },
        { path: 'tasks', element: <DataTasksPage /> },
      ] },
      { path: 'monitor', element: <RoutePlaceholder pageKey="monitor" icon={Activity} /> },
      {
        path: 'settings',
        element: <SettingsLayout />,
        children: [
          { index: true, element: <SettingsOverviewPage /> },
          { path: 'models', element: <ModelMarketplacePage /> },
          { path: 'api-test', element: <ApiTestPage /> },
        ],
      },
    ],
  },
  { path: '/500', element: <ServerErrorPage /> },
  { path: '/404', element: <NotFoundPage /> },
  { path: '*', element: <NotFoundPage /> },
])

/** 预留：鉴权失败时跳转登录（暂未启用） */
export const LOGIN_ROUTE = '/login'
