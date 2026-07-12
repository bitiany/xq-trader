import { useMemo } from 'react'
import { Maximize2 } from 'lucide-react'
import { useMonitorStore } from '../stores/monitorStore'
import '@/pages/monitor/styles/monitor.css'

interface ScreenHeaderProps {
  monitoring: boolean
  poolCount: number
}

export function ScreenHeader({ monitoring, poolCount }: ScreenHeaderProps) {
  const cellCount = useMonitorStore((s) => s.cells.length)
  const cols = useMonitorStore((s) => s.cols)

  const timeRange = useMemo(() => '09:30-15:00', [])

  const handleFullscreen = () => {
    if (!document.fullscreenElement) {
      document.documentElement.requestFullscreen().catch(() => {})
    } else {
      document.exitFullscreen().catch(() => {})
    }
  }

  return (
    <div className="monitor-header">
      <div className="monitor-header__status">
        <span className={`monitor-header__dot ${monitoring ? 'monitor-header__dot--active' : ''}`} />
        <span>{monitoring ? '监控中' : '未启动'}</span>
      </div>
      <span className="monitor-header__info">{timeRange}</span>
      <span className="monitor-header__info">| 池: {poolCount}只</span>
      <span className="monitor-header__info">| 格: {cellCount}</span>
      <span className="monitor-header__info">| 列: {cols}</span>
      <div className="monitor-header__spacer" />
      <span className="monitor-header__info">深色主题</span>
      <button className="monitor-header__btn" onClick={handleFullscreen}>
        <Maximize2 size={12} />
        <span>全屏</span>
      </button>
    </div>
  )
}
