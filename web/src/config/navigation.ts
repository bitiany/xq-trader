import type { LucideIcon } from 'lucide-react'
import {
  Activity,
  Database,
  LayoutDashboard,
  LineChart,
  Radio,
  Settings,
  Target,
} from 'lucide-react'

export interface NavItem {
  id: string
  labelKey: string
  path: string
  icon: LucideIcon
  badge?: string
}

export const NAV_ITEMS: NavItem[] = [
  { id: 'dashboard', labelKey: 'nav.dashboard', path: '/', icon: LayoutDashboard },
  { id: 'strategy', labelKey: 'nav.strategy', path: '/strategy', icon: Target },
  { id: 'backtest', labelKey: 'nav.backtest', path: '/backtest', icon: LineChart },
  { id: 'trading', labelKey: 'nav.trading', path: '/trading', icon: Radio },
  { id: 'data', labelKey: 'nav.data', path: '/data', icon: Database },
  { id: 'monitor', labelKey: 'nav.monitor', path: '/monitor', icon: Activity },
  { id: 'settings', labelKey: 'nav.settings', path: '/settings', icon: Settings },
]
