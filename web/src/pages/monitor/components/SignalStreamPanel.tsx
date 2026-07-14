import { useMemo } from 'react'
import { ChevronDown, ChevronUp, Zap } from 'lucide-react'
import { useMonitorStore } from '../stores/monitorStore'
import { buildSignalDesc, SIGNAL_TYPE_LABELS, DIRECTION_LABELS, toShanghaiTime } from '../utils/signalDesc'
import '@/pages/monitor/styles/monitor.css'

export function SignalStreamPanel() {
  const signals = useMonitorStore((s) => s.signals)
  const collapsed = useMonitorStore((s) => s.signalPanelCollapsed)
  const setCollapsed = useMonitorStore((s) => s.setSignalPanelCollapsed)
  const setSelectedCellId = useMonitorStore((s) => s.setSelectedCellId)
  const cells = useMonitorStore((s) => s.cells)

  // 仅显示监控区域标的的信号
  const monitorSymbols = useMemo(() => new Set(cells.map((c) => c.symbol)), [cells])

  const sortedSignals = useMemo(() => {
    return signals
      .filter((s) => monitorSymbols.has(s.symbol))
      .sort((a, b) => b.created_at.localeCompare(a.created_at))
  }, [signals, monitorSymbols])

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
        <span className="monitor-signals__count">{sortedSignals.length}</span>
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
              {cells.length === 0 ? '请拖拽标的到监控区域' : '暂无信号'}
            </div>
          ) : (
            sortedSignals.map((signal) => (
              <div
                key={signal.id}
                className="monitor-signals__row"
                onClick={() => handleRowClick(signal.symbol)}
                title={buildSignalDesc(signal)}
              >
                <span className="monitor-signals__time">
                  {toShanghaiTime(signal.created_at)}
                </span>
                <span className="monitor-signals__symbol" title={signal.name ?? signal.symbol}>
                  {signal.name ?? signal.symbol}
                </span>
                <span className="monitor-signals__code">{signal.symbol}</span>
                <span className="monitor-signals__type">
                  {SIGNAL_TYPE_LABELS[signal.signal_type ?? ''] ?? signal.signal_type}
                </span>
                <span className="monitor-signals__desc">
                  {buildSignalDesc(signal)}
                </span>
                <span
                  className={`monitor-signals__direction monitor-signals__direction--${signal.direction}`}
                >
                  {DIRECTION_LABELS[signal.direction] ?? signal.direction}
                </span>
                <span className="monitor-signals__strength">
                  {signal.strength !== null ? signal.strength.toFixed(2) : '-'}
                </span>
              </div>
            ))
          )}
        </div>
      )}
    </div>
  )
}
