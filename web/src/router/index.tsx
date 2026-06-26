import { createBrowserRouter } from 'react-router-dom'
import { Navigate } from 'react-router-dom'
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
import { StrategyLayout } from '@/pages/strategy/StrategyLayout'
import { SelectionWorkbenchPage } from '@/pages/strategy/SelectionWorkbenchPage'
import { StrategyListPage } from '@/pages/strategy/StrategyListPage'
import { StrategyDetailPage } from '@/pages/strategy/StrategyDetailPage'
import { SelectionHistoryPage } from '@/pages/strategy/SelectionHistoryPage'
import { AuthGuard } from '@/router/AuthGuard'
import { RouteErrorBoundary } from '@/router/RouteErrorBoundary'
import { Activity } from 'lucide-react'
import { LiveCockpitPage } from '@/pages/trading/LiveCockpitPage'
import { FactorWorkbenchPage } from '@/pages/factor/FactorWorkbenchPage'

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
      {
        path: 'strategy',
        element: <StrategyLayout />,
        children: [
          { index: true, element: <Navigate to="/strategy/workbench" replace /> },
          { path: 'workbench', element: <SelectionWorkbenchPage /> },
          { path: 'list', element: <StrategyListPage /> },
          { path: 'list/:strategyId', element: <StrategyDetailPage /> },
          { path: 'history', element: <SelectionHistoryPage /> },
        ],
      },
      { path: 'data', element: <DataLayout />, children: [
        { index: true, element: <DataOverviewPage /> },
        { path: 'tasks', element: <DataTasksPage /> },
      ] },
      { path: 'factors', element: <FactorWorkbenchPage /> },
      { path: 'trading', element: <LiveCockpitPage /> },
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
