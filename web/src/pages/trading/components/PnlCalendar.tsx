import { generateCalendarData } from '../data/mock-trading';

const CALENDAR_DATA = generateCalendarData();

export function PnlCalendar() {
  const dayHeaders = ['一', '二', '三', '四', '五', '六', '日'];
  const daysInMonth = 30;
  const getCellClass = (pnl: number | null): string => {
    if (pnl == null) return 'pnl-calendar__cell--empty';
    if (pnl === 0) return 'pnl-calendar__cell--neutral';
    const abs = Math.abs(pnl);
    const level = abs <= 0.3 ? 1 : abs <= 0.7 ? 2 : abs <= 1.0 ? 3 : 4;
    return pnl > 0 ? `pnl-calendar__cell--positive-${level}` : `pnl-calendar__cell--negative-${level}`;
  };
  const cells = [];
  for (let d = 1; d <= daysInMonth; d++) cells.push({ day: d, pnl: CALENDAR_DATA[d] ?? null });

  return (
    <div className="pnl-calendar" data-component="PnL Calendar">
      <div className="pnl-calendar__month-label">2026年6月 收益日历</div>
      <div className="pnl-calendar__grid">
        {dayHeaders.map(h => <div key={h} className="pnl-calendar__day-header">{h}</div>)}
        {cells.map((cell, idx) => (
          <div key={idx} className={`pnl-calendar__cell ${getCellClass(cell.pnl)}`}
            title={cell.day && cell.pnl != null ? `${(cell.pnl > 0 ? '+' : '') + (cell.pnl * 100).toFixed(1) + '%'}` : ''}>
            {cell.day || ''}
          </div>
        ))}
      </div>
      <div className="pnl-calendar__legend">
        <span>亏</span>
        {[30, 60].map(a => <div key={`f${a}`} className="pnl-calendar__legend-block" style={{ background: `color-mix(in srgb, var(--color-fall) ${a}%, var(--bg-card))` }} />)}
        <div className="pnl-calendar__legend-block" style={{ background: 'var(--text-muted)' }} />
        {[30, 60].map(a => <div key={`r${a}`} className="pnl-calendar__legend-block" style={{ background: `color-mix(in srgb, var(--color-rise) ${a}%, var(--bg-card))` }} />)}
        <span>盈</span>
      </div>
    </div>
  );
}
