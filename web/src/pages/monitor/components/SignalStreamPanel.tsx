import { useMemo } from 'react'
import { ChevronDown, ChevronUp, Zap } from 'lucide-react'
import { useMonitorStore } from '../stores/monitorStore'
import '@/pages/monitor/styles/monitor.css'

const DIRECTION_LABELS: Record<string, string> = {
  long: '▲ long',
  short: '▼ short',
  neutral: '—',
}

export function SignalStreamPanel() {
  const signals = useMonitorStore((s) => s.signals)
  const collapsed = useMonitorStore((s) => s.signalPanelCollapsed)
  const setCollapsed = useMonitorStore((s) => s.setSignalPanelCollapsed)
  const setSelectedCellId = useMonitorStore((s) => s.setSelectedCellId)
  const cells = useMonitorStore((s) => s.cells)

  const sortedSignals = useMemo(() => {
    return [...signals].sort((a, b) =>
      b.created_at.localeCompare(a.created_at),
    )
  }, [signals])

  const handleRowClick = (symbol: string) => {
    const cell = cells.find((c) => c.symbol === symbol)
    if (cell) {
      setSelectedCellId(cell.id)
    }
  }

  return (
    <div className={`monitor-signals ${collapsed ? 'monitor-signals--collapsed' : 'monitor-signals--expanded'}`}>
      <div
        className="monitor-signals__header"
        onClick={() => setCollapsed(!collapsed)}
      >
        <Zap size={14} style={{ color: 'var(--color-warning)' }} />
        <span className="monitor-signals__title">信号流</span>
        <span className="monitor-signals__count">{signals.length}</span>
        <div style={{ flex: 1 }} />
        {collapsed ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
      </div>
      {!collapsed && (
        <div className="monitor-signals__list">
          {sortedSignals.length === 0 ? (
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                height: '100%',
                color: 'var(--text-muted)',
                fontSize: 12,
              }}
            >
              暂无信号
            </div>
          ) : (
            sortedSignals.map((signal) => (
              <div
                key={signal.id}
                className="monitor-signals__row"
                onClick={() => handleRowClick(signal.symbol)}
              >
                <span className="monitor-signals__time">
                  {signal.created_at.substring(11, 19)}
                </span>
                <span className="monitor-signals__symbol">{signal.symbol}</span>
                <span className="monitor-signals__type">
                  {signal.signal_type ?? signal.signal_source}
                </span>
                <span
                  className={`monitor-signals__direction monitor-signals__direction--${signal.direction}`}
                >
                  {DIRECTION_LABELS[signal.direction] ?? signal.direction}
                </span>
                <span className="monitor-signals__strength">
                  {signal.strength !== null ? signal.strength.toFixed(2) : '—'}
                </span>
              </div>
            ))
          )}
        </div>
      )}
    </div>
  )
}
