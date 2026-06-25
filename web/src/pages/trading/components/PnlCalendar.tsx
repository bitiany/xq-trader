import type { AccountSnapshot } from '@/api/trading';

interface PnlCalendarProps {
  snapshots: AccountSnapshot[];
}

function getCellClass(pnl: number | null): string {
  if (pnl == null) return 'pnl-calendar__cell--empty';
  if (pnl === 0) return 'pnl-calendar__cell--neutral';
  const abs = Math.abs(pnl);
  const level = abs <= 0.003 ? 1 : abs <= 0.007 ? 2 : abs <= 0.01 ? 3 : 4;
  return pnl > 0 ? `pnl-calendar__cell--positive-${level}` : `pnl-calendar__cell--negative-${level}`;
}

export function PnlCalendar({ snapshots }: PnlCalendarProps) {
  const dayHeaders = ['一', '二', '三', '四', '五', '六', '日'];
  const byDay = new Map<number, number>();
  const dates = snapshots
    .map(item => item.snapshot_date)
    .filter((value): value is string => typeof value === 'string');
  const latestDate = dates[0] ? new Date(dates[0]) : new Date();
  const year = latestDate.getFullYear();
  const month = latestDate.getMonth();
  const daysInMonth = new Date(year, month + 1, 0).getDate();

  snapshots.forEach((snapshot) => {
    if (!snapshot.snapshot_date) return;
    const date = new Date(snapshot.snapshot_date);
    if (date.getFullYear() !== year || date.getMonth() !== month) return;
    byDay.set(date.getDate(), Number(snapshot.daily_return));
  });

  const cells = [];
  for (let d = 1; d <= daysInMonth; d++) cells.push({ day: d, pnl: byDay.get(d) ?? null });

  return (
    <div className="pnl-calendar" data-component="PnL Calendar">
      <div className="pnl-calendar__month-label">{year}年{month + 1}月 收益日历</div>
      <div className="pnl-calendar__grid">
        {dayHeaders.map(h => <div key={h} className="pnl-calendar__day-header">{h}</div>)}
        {cells.map((cell) => (
          <div
            key={cell.day}
            className={`pnl-calendar__cell ${getCellClass(cell.pnl)}`}
            title={cell.pnl != null ? `${cell.pnl > 0 ? '+' : ''}${(cell.pnl * 100).toFixed(2)}%` : ''}
          >
            {cell.day}
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
