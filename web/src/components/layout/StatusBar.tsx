import { useEffect, useState } from 'react'
import { Clock, Server, Wifi, WifiOff } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useLocaleStore } from '@/stores/localeStore'
import { usePageWebSocket } from '@/ws/usePageWebSocket'
import { TOPIC_BROKER_STATUS, TOPIC_TRADING_PNL, type BrokerStatusData, type TradingPnlData } from '@/ws/protocol'
import { formatMoney } from '@/utils/format'
import './StatusBar.css'

export function StatusBar() {
  const { t } = useTranslation()
  const locale = useLocaleStore((s) => s.locale)
  const now = new Date()
  const timeStr = now.toLocaleTimeString(locale, { hour12: false })

  /* --- Broker status via WebSocket --- */
  const [brokerStatus, setBrokerStatus] = useState<BrokerStatusData | null>(null)
  const [pnlData, setPnlData] = useState<TradingPnlData | null>(null)
  const { status: wsStatus } = usePageWebSocket<BrokerStatusData>({
    topics: [TOPIC_BROKER_STATUS],
    onSnapshot: (_channel, data) => {
      if (data && typeof data === 'object') {
        setBrokerStatus(data as BrokerStatusData)
      }
    },
    onUpdate: (_channel, data) => {
      if (data && typeof data === 'object') {
        setBrokerStatus(data as BrokerStatusData)
      }
    },
  })

  // WS断开时重置状态数据
  useEffect(() => {
    if (wsStatus !== 'open') {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setBrokerStatus(null)
      setPnlData(null)
    }
  }, [wsStatus])

  /* --- Account asset via WebSocket --- */
  usePageWebSocket<TradingPnlData>({
    topics: [TOPIC_TRADING_PNL],
    onSnapshot: (_channel, data) => {
      if (data && typeof data === 'object') {
        setPnlData(data as TradingPnlData)
      }
    },
    onUpdate: (_channel, data) => {
      if (data && typeof data === 'object') {
        setPnlData(data as TradingPnlData)
      }
    },
  })

  const marketConnected = brokerStatus?.market_status === 'connected'
  const tradingConnected = brokerStatus?.trading_status === 'connected'

  return (
    <footer className="statusbar">
      <div className="statusbar__section">
        <span className="statusbar__item">
          {marketConnected ? (
            <Wifi size={10} style={{ color: 'var(--color-live)' }} />
          ) : (
            <WifiOff size={10} style={{ color: 'var(--color-loss)' }} />
          )}
          {marketConnected ? t('statusbar.marketConnected') : t('statusbar.marketDisconnected')}
        </span>
        <span className="statusbar__item">
          {tradingConnected ? (
            <Wifi size={10} style={{ color: 'var(--color-live)' }} />
          ) : (
            <WifiOff size={10} style={{ color: 'var(--color-loss)' }} />
          )}
          {tradingConnected ? t('statusbar.tradingConnected') : t('statusbar.tradingDisconnected')}
        </span>
        <span className="statusbar__item">
          <Server size={10} />
          {t('statusbar.latency', { ms: 12 })}
        </span>
      </div>

      <div className="statusbar__section statusbar__section--center">
        <span className="statusbar__pnl">
          {t('statusbar.totalAsset')}
          <strong className="statusbar__pnl-value">
            {formatMoney(pnlData?.total_asset ?? 0)}
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
