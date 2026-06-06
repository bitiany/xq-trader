/**
 * 通用格式化工具函数
 */

export function formatMoney(value: number | null | undefined, decimals = 2): string {
  if (value == null || Number.isNaN(value)) {
    return '--'
  }
  const prefix = value >= 0 ? '' : '-'
  return `${prefix}¥${Math.abs(value).toLocaleString(undefined, {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  })}`
}

export function formatSignedMoney(value: number | null | undefined, decimals = 2): string {
  if (value == null || Number.isNaN(value)) {
    return '--'
  }
  const prefix = value >= 0 ? '+' : '-'
  return `${prefix}¥${Math.abs(value).toLocaleString(undefined, {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  })}`
}

export function formatPercent(value: number | null | undefined, decimals = 2): string {
  if (value == null || Number.isNaN(value)) {
    return '--'
  }
  return `${value >= 0 ? '+' : ''}${value.toFixed(decimals)}%`
}

export function formatPrice(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) {
    return '--'
  }
  return value.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })
}

export function formatPricePair(
  lastPrice: number | null | undefined,
  costPrice: number | null | undefined,
): string {
  return `${formatPrice(lastPrice)}/${formatPrice(costPrice)}`
}

export function pnlClass(value: number | null | undefined): string {
  if (value == null) return ''
  return value > 0 ? 'card__value--profit' : value < 0 ? 'card__value--loss' : ''
}

export function textPnlClass(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return ''
  return value > 0 ? 'text-profit' : value < 0 ? 'text-loss' : ''
}

export function priceTrendClass(changePct: number | null | undefined): string {
  if (changePct == null || Number.isNaN(changePct)) {
    return ''
  }
  if (changePct > 0) {
    return 'text-profit'
  }
  if (changePct < 0) {
    return 'text-loss'
  }
  return ''
}
