import { useState } from 'react'
import { Circle, Clock, Server, Wifi, WifiOff } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useLocaleStore } from '@/stores/localeStore'
import { useWebSocketStore } from '@/stores/webSocketStore'
import { usePageWebSocket } from '@/ws/usePageWebSocket'
import { TOPIC_TRADING_CONNECTION, type ConnectionStatusData } from '@/ws/protocol'
import { formatSignedMoney } from '@/utils/format'
import type { PageWebSocketStatus } from '@/ws/usePageWebSocket'
import './StatusBar.css'

function wsDotClass(status: PageWebSocketStatus): string {
  switch (status) {
    case 'open':
      return 'statusbar__dot--ok'
    case 'connecting':
    case 'idle':
      return 'statusbar__dot--warn'
    case 'error':
    case 'closed':
      return 'statusbar__dot--error'
    default:
      return 'statusbar__dot--warn'
  }
}

export function StatusBar() {
  const { t } = useTranslation()
  const locale = useLocaleStore((s) => s.locale)
  const wsStatus = useWebSocketStore((s) => s.status)
  const now = new Date()
  const timeStr = now.toLocaleTimeString(locale, { hour12: false })

  /* --- QMT connection status via WebSocket --- */
  const [qmtStatus, setQmtStatus] = useState<ConnectionStatusData | null>(null)
  usePageWebSocket<ConnectionStatusData>({
    topics: [TOPIC_TRADING_CONNECTION],
    onSnapshot: (channel, data) => {
      if (channel === TOPIC_TRADING_CONNECTION && data && typeof data === 'object') {
        setQmtStatus(data as ConnectionStatusData)
      }
    },
    onUpdate: (channel, data) => {
      if (channel === TOPIC_TRADING_CONNECTION && data && typeof data === 'object') {
        setQmtStatus(data as ConnectionStatusData)
      }
    },
  })

  /* --- Unified QMT status --- */
  const qmtConnected = qmtStatus?.status === 'connected'
  const qmtPartial = qmtStatus?.status === 'partial'

  return (
    <footer className="statusbar">
      <div className="statusbar__section">
        <span className="statusbar__item">
          <Circle size={8} className={`statusbar__dot ${wsDotClass(wsStatus)}`} />
          {t(`statusbar.wsStatus.${wsStatus}`)}
        </span>
        <span className="statusbar__item">
          {qmtConnected || qmtPartial ? (
            <Wifi size={10} style={{ color: qmtConnected ? 'var(--color-live)' : 'var(--color-loss)' }} />
          ) : (
            <WifiOff size={10} style={{ color: 'var(--color-loss)' }} />
          )}
          QMT {qmtConnected ? t('trading.connection.connected') : qmtPartial ? t('trading.connection.partial') : t('trading.connection.disconnected')}
        </span>
        <span className="statusbar__item">
          <Server size={10} />
          {t('statusbar.latency', { ms: 12 })}
        </span>
      </div>

      <div className="statusbar__section statusbar__section--center">
        <span className="statusbar__pnl">
          {t('statusbar.todayPnl')}
          <strong className="statusbar__pnl-value">
            {formatSignedMoney(0)}
          </strong>
        </span>
      </div>

      <div className="statusbar__section statusbar__section--right">
        <span className="statusbar__item">{t('statusbar.benchmark')}</span>
        <span className="statusbar__item">
          <Clock size={10} />
          {timeStr}
        </span>
      </div>
    </footer>
  )
}
