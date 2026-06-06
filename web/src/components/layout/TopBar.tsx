import {
  Bell,
  ChevronDown,
  Notebook,
  PanelLeftClose,
  PanelLeftOpen,
  PanelRightClose,
  PanelRightOpen,
} from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Badge, Popover, List, Tag, Empty, Button } from 'antd'
import { CheckCircleOutlined, CloseCircleOutlined } from '@ant-design/icons'
import { LocaleSwitch } from '@/components/common/LocaleSwitch'
import { ThemeSwitch } from '@/components/common/ThemeSwitch'
import { GlobalStockSearch } from '@/components/stock/GlobalStockSearch'
import { useLayoutStore } from '@/stores/layoutStore'
import { useSignalNotificationStore } from '@/stores/signalNotificationStore'
import { usePageWebSocket } from '@/ws/usePageWebSocket'
import { TOPIC_TRADING_SIGNALS } from '@/ws/protocol'
import { pnlClass } from '@/utils/format'
import { SIGNAL_SIDE_COLOR, SIGNAL_SIDE_KEYS } from '@/utils/trading'
import './TopBar.css'

const JUPYTER_URL = import.meta.env.VITE_JUPYTER_URL ?? 'http://localhost:8888/tree'

export function TopBar() {
  const { t } = useTranslation()
  const sideNavCollapsed = useLayoutStore((s) => s.sideNavCollapsed)
  const agentPanelOpen = useLayoutStore((s) => s.agentPanelOpen)
  const toggleSideNav = useLayoutStore((s) => s.toggleSideNav)
  const toggleAgentPanel = useLayoutStore((s) => s.toggleAgentPanel)

  const handleOpenNotebook = useCallback(() => {
    window.open(JUPYTER_URL, '_blank')
  }, [])

  return (
    <header className="topbar">
      <div className="topbar__left">
        <button
          type="button"
          className="topbar__icon-btn"
          onClick={toggleSideNav}
          title={sideNavCollapsed ? t('topbar.expandNav') : t('topbar.collapseNav')}
          aria-label={sideNavCollapsed ? t('topbar.expandNav') : t('topbar.collapseNav')}
        >
          {sideNavCollapsed ? <PanelLeftOpen size={15} /> : <PanelLeftClose size={15} />}
        </button>

        <div className="topbar__brand">
          <span className="topbar__logo">XQ</span>
          <span className="topbar__brand-text">{t('common.brand')}</span>
        </div>

        <GlobalStockSearch />
      </div>

      <div className="topbar__right">
        <button
          type="button"
          className="topbar__icon-btn"
          onClick={handleOpenNotebook}
          title={t('topbar.openNotebook')}
          aria-label={t('topbar.openNotebook')}
        >
          <Notebook size={15} />
        </button>

        <ThemeSwitch />
        <LocaleSwitch />

        <SignalNotificationBell />

        <button
          type="button"
          className={`topbar__icon-btn topbar__agent-toggle ${agentPanelOpen ? 'is-active' : ''}`}
          onClick={toggleAgentPanel}
          title={agentPanelOpen ? t('topbar.closeAgent') : t('topbar.openAgent')}
          aria-label={agentPanelOpen ? t('topbar.closeAgent') : t('topbar.openAgent')}
        >
          {agentPanelOpen ? <PanelRightClose size={15} /> : <PanelRightOpen size={15} />}
        </button>

        <button type="button" className="topbar__user" aria-label={t('topbar.userMenu')}>
          <span className="topbar__avatar">QT</span>
          <span className="topbar__username">Quant Desk</span>
          <ChevronDown size={13} />
        </button>
      </div>
    </header>
  )
}

/** 信号通知铃铛 — 订阅 WS trading.signals topic，实时接收信号通知 */
function SignalNotificationBell() {
  const { t } = useTranslation()
  const notifications = useSignalNotificationStore((s) => s.notifications)
  const unreadCount = useSignalNotificationStore((s) => s.unreadCount)
  const addNotification = useSignalNotificationStore((s) => s.addNotification)
  const markAllRead = useSignalNotificationStore((s) => s.markAllRead)
  const clearAll = useSignalNotificationStore((s) => s.clearAll)
  const [open, setOpen] = useState(false)

  // 订阅 WS 信号推送
  usePageWebSocket({
    topics: [TOPIC_TRADING_SIGNALS],
    onUpdate: (_channel, data) => {
      if (data && typeof data === 'object') {
        addNotification(data as Parameters<typeof addNotification>[0])
      }
    },
    onSnapshot: (_channel, data) => {
      // 快照返回 unconsumed_count，不处理
      void data
    },
  })

  const handleOpenChange = useCallback((nextOpen: boolean) => {
    setOpen(nextOpen)
    if (nextOpen && unreadCount > 0) {
      markAllRead()
    }
  }, [unreadCount, markAllRead])

  const sideLabel = useCallback((side: string) => {
    return t(SIGNAL_SIDE_KEYS[side] ?? side)
  }, [t])

  const content = (
    <div style={{ width: 320, maxHeight: 400, overflow: 'auto' }}>
      {notifications.length === 0 ? (
        <Empty description={t('trading.signals.noSignals')} image={Empty.PRESENTED_IMAGE_SIMPLE} />
      ) : (
        <>
          <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 8 }}>
            <Button type="link" size="small" onClick={clearAll}>{t('common.clear')}</Button>
          </div>
          <List
            size="small"
            dataSource={notifications.slice(0, 20)}
            renderItem={(item) => (
              <List.Item style={{ padding: '6px 0' }}>
                <div style={{ width: '100%' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <span style={{ fontWeight: 600, fontFamily: 'var(--font-mono)', fontSize: 13 }}>
                      {item.symbol_name ? `${item.symbol_name} ` : ''}{item.symbol}
                    </span>
                    <Tag
                      color={SIGNAL_SIDE_COLOR[item.side] ?? 'default'}
                      style={{ fontSize: 11, padding: '0 4px' }}
                    >
                      {sideLabel(item.side)}
                    </Tag>
                  </div>
                  {item.price != null && (
                    <div style={{ fontSize: 14, fontWeight: 700, marginTop: 2 }}>
                      ¥{item.price.toFixed(2)}
                    </div>
                  )}
                  {item.strategy_code && (
                    <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 2 }}>
                      {item.strategy_code}
                    </div>
                  )}
                </div>
              </List.Item>
            )}
          />
        </>
      )}
    </div>
  )

  return (
    <Popover
      open={open}
      onOpenChange={handleOpenChange}
      title={t('topbar.notifications')}
      content={content}
      trigger="click"
      placement="bottomRight"
    >
      <button type="button" className="topbar__icon-btn" title={t('topbar.notifications')} aria-label={t('topbar.notifications')}>
        <Badge count={unreadCount} size="small" offset={[-2, -2]}>
          <Bell size={15} />
        </Badge>
      </button>
    </Popover>
  )
}
