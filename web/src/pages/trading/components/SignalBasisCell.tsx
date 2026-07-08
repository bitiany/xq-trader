import { Tag } from 'antd'
import type { SignalDetail } from '@/api/trading'
import { DIRECTION_COLOR, DIRECTION_LABEL, formatSignalPct } from '../utils/trading'

interface SignalBasisCellProps {
  detail: SignalDetail | null | undefined
}

export function SignalBasisCell({ detail }: SignalBasisCellProps) {
  if (!detail) {
    return <span style={{ color: 'var(--text-muted)' }}>—</span>
  }

  return (
    <div className="signal-basis-cell" data-component="Signal Basis Cell">
      <div className="signal-basis-cell__row">
        <Tag
          color={DIRECTION_COLOR[detail.direction] ?? 'default'}
          style={{ margin: 0, fontSize: 10, padding: '0 5px', lineHeight: '18px' }}
        >
          {DIRECTION_LABEL[detail.direction] ?? detail.direction ?? '—'}
        </Tag>
        <span className="signal-basis-cell__metric">置信 {formatSignalPct(detail.confidence)}</span>
        {detail.fused_score != null && (
          <span className="signal-basis-cell__metric">融合 {detail.fused_score}</span>
        )}
      </div>
      {detail.strategy_id && (
        <div className="signal-basis-cell__strategy" title={detail.strategy_id}>
          {detail.strategy_id}
        </div>
      )}
      {detail.reason && (
        <div className="signal-basis-cell__reason" title={detail.reason}>
          {detail.reason}
        </div>
      )}
    </div>
  )
}
