import { useMemo, useState } from 'react';
import { Segmented } from 'antd';
import type { AccountSnapshot } from '@/api/trading';
import { formatCompactPnl, formatPct } from '../utils/trading';

interface PnlCalendarProps {
  snapshots: AccountSnapshot[];
}

type PnlDisplayMode = 'return' | 'amount';

type CalendarCell = {
  day: number;
  weekend: boolean;
  value: number | null;
  column: number;
  row: number;
};

const DAY_HEADERS = ['一', '二', '三', '四', '五', '六', '日'] as const;

function parseLocalDate(value: string): Date {
  const iso = value.slice(0, 10);
  const [year, month, day] = iso.split('-').map(Number);
  return new Date(year, month - 1, day);
}

function toIsoDate(year: number, month: number, day: number): string {
  return `${year}-${String(month + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
}

/** 周一=0 … 周日=6 */
function mondayFirstIndex(date: Date): number {
  return (date.getDay() + 6) % 7;
}

function isWeekend(date: Date): boolean {
  const weekday = date.getDay();
  return weekday === 0 || weekday === 6;
}

function getCellClass(cell: CalendarCell): string {
  if (cell.weekend) return 'pnl-calendar__cell--weekend';
  if (cell.value == null) return 'pnl-calendar__cell--empty';
  if (cell.value === 0) return 'pnl-calendar__cell--neutral';
  return cell.value > 0 ? 'pnl-calendar__cell--positive' : 'pnl-calendar__cell--negative';
}

function formatCellValue(mode: PnlDisplayMode, value: number): string {
  if (mode === 'return') {
    const sign = value > 0 ? '+' : '';
    return `${sign}${(value * 100).toFixed(1)}%`;
  }
  return formatCompactPnl(value);
}

function formatTooltip(mode: PnlDisplayMode, value: number): string {
  if (mode === 'return') return formatPct(value);
  const sign = value > 0 ? '+' : '';
  return `${sign}¥${Math.abs(value).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

export function PnlCalendar({ snapshots }: PnlCalendarProps) {
  const [mode, setMode] = useState<PnlDisplayMode>('return');

  const { year, month, cells } = useMemo(() => {
    const dates = snapshots
      .map(item => item.snapshot_date)
      .filter((value): value is string => typeof value === 'string');
    const latestDate = dates[0] ? parseLocalDate(dates[0]) : new Date();
    const calendarYear = latestDate.getFullYear();
    const calendarMonth = latestDate.getMonth();
    const daysInMonth = new Date(calendarYear, calendarMonth + 1, 0).getDate();

    const returnByIso = new Map<string, number>();
    const amountByIso = new Map<string, number>();

    snapshots.forEach((snapshot) => {
      if (!snapshot.snapshot_date) return;
      const date = parseLocalDate(snapshot.snapshot_date);
      if (date.getFullYear() !== calendarYear || date.getMonth() !== calendarMonth) return;
      if (isWeekend(date)) return;
      returnByIso.set(snapshot.snapshot_date, Number(snapshot.daily_return));
      amountByIso.set(snapshot.snapshot_date, Number(snapshot.daily_pnl));
    });

    const leadingPads = mondayFirstIndex(new Date(calendarYear, calendarMonth, 1));
    const grid: CalendarCell[] = [];
    for (let day = 1; day <= daysInMonth; day += 1) {
      const date = new Date(calendarYear, calendarMonth, day);
      const weekend = isWeekend(date);
      const iso = toIsoDate(calendarYear, calendarMonth, day);
      const value = weekend
        ? null
        : mode === 'return'
          ? (returnByIso.get(iso) ?? null)
          : (amountByIso.get(iso) ?? null);
      grid.push({
        day,
        weekend,
        value,
        column: mondayFirstIndex(date) + 1,
        row: Math.floor((day - 1 + leadingPads) / 7) + 2,
      });
    }

    return { year: calendarYear, month: calendarMonth, cells: grid };
  }, [snapshots, mode]);

  return (
    <div className="pnl-calendar" data-component="PnL Calendar">
      <div className="pnl-calendar__header">
        <div className="pnl-calendar__month-label">{year}年{month + 1}月 收益日历</div>
        <Segmented
          size="small"
          value={mode}
          onChange={(value) => setMode(value as PnlDisplayMode)}
          options={[
            { label: '收益率', value: 'return' },
            { label: '收益额', value: 'amount' },
          ]}
        />
      </div>
      <div className="pnl-calendar__grid">
        {DAY_HEADERS.map(h => <div key={h} className="pnl-calendar__day-header">{h}</div>)}
        {cells.map((cell) => (
            <div
              key={`day-${cell.day}`}
              className={`pnl-calendar__cell ${getCellClass(cell)}`}
              style={{ gridColumn: cell.column, gridRow: cell.row }}
              title={cell.value != null ? formatTooltip(mode, cell.value) : undefined}
            >
              <span className={`pnl-calendar__cell-day ${cell.weekend ? 'pnl-calendar__cell-day--weekend' : ''}`}>
                {cell.day}
              </span>
              {!cell.weekend && cell.value != null && (
                <span
                  className={`pnl-calendar__cell-value ${
                    cell.value > 0
                      ? 'pnl-calendar__cell-value--rise'
                      : cell.value < 0
                        ? 'pnl-calendar__cell-value--fall'
                        : 'pnl-calendar__cell-value--neutral'
                  }`}
                >
                  {formatCellValue(mode, cell.value)}
                </span>
              )}
            </div>
        ))}
      </div>
      <div className="pnl-calendar__legend">
        <span>亏</span>
        <div className="pnl-calendar__legend-block pnl-calendar__legend-block--fall" />
        <div className="pnl-calendar__legend-block pnl-calendar__legend-block--neutral" />
        <div className="pnl-calendar__legend-block pnl-calendar__legend-block--rise" />
        <span>盈</span>
      </div>
    </div>
  );
}
