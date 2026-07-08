interface PositionPriceCostCellProps {
  marketPrice: string | number | null
  costPrice: string | number | null
}

function num(value: string | number | null | undefined): number {
  return Number(value ?? 0)
}

export function PositionPriceCostCell({ marketPrice, costPrice }: PositionPriceCostCellProps) {
  const price = num(marketPrice)
  const cost = num(costPrice)
  const hasPrice = marketPrice !== null && marketPrice !== undefined && price > 0
  const hasCost = costPrice !== null && costPrice !== undefined && cost > 0

  if (!hasPrice && !hasCost) {
    return <span style={{ color: 'var(--text-muted)' }}>—</span>
  }

  let toneColor = 'var(--text-secondary)'
  if (hasPrice && hasCost) {
    if (price > cost) toneColor = 'var(--color-rise)'
    else if (price < cost) toneColor = 'var(--color-fall)'
  }

  return (
    <span
      className="position-price-cost-cell"
      title="最新收盘价 / 成本价"
      style={{ fontFamily: 'var(--font-mono)', fontWeight: 600, color: toneColor }}
    >
      {hasPrice ? price.toFixed(2) : '—'}
      <span style={{ color: 'var(--text-muted)', fontWeight: 400, margin: '0 2px' }}>/</span>
      {hasCost ? cost.toFixed(2) : '—'}
    </span>
  )
}
