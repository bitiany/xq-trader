import { useTranslation } from 'react-i18next'
import { Monitor, ExternalLink } from 'lucide-react'
import '@/pages/monitor/styles/monitor.css'

export function MonitorOverviewPage() {
  const { t } = useTranslation()

  const handleOpenScreen = () => {
    window.open('/monitor/screen', '_blank', 'popup,width=1920,height=1080')
  }

  return (
    <div className="monitor-overview">
      <div style={{ color: 'var(--accent-primary)' }}>
        <Monitor size={48} />
      </div>
      <h2 className="monitor-overview__title">{t('pages.monitor.title', '行情监控大屏')}</h2>
      <p className="monitor-overview__desc">
        {t('pages.monitor.description', '多标的同屏行情监控面板，支持拖拽布局、分钟/日K切换、指标叠加、信号流展示。适合投屏或副屏使用。')}
      </p>
      <button className="monitor-overview__btn" onClick={handleOpenScreen}>
        <ExternalLink size={18} />
        <span>打开大屏</span>
      </button>
    </div>
  )
}
