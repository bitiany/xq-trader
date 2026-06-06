import { Tooltip } from 'antd'
import type { StockTagItem } from '@/api/stock'

const TAG_COLOR_MAP: Record<string, { bg: string; text: string; border: string }> = {
  large_cap: { bg: '#1E3A5F', text: '#FFFFFF', border: '#1E3A5F' },
  mid_cap: { bg: '#2563EB', text: '#FFFFFF', border: '#2563EB' },
  small_cap: { bg: '#60A5FA', text: '#0F172A', border: '#60A5FA' },
  value: { bg: '#065F46', text: '#FFFFFF', border: '#065F46' },
  growth: { bg: '#B91C1C', text: '#FFFFFF', border: '#B91C1C' },
  core: { bg: '#5B21B6', text: '#FFFFFF', border: '#5B21B6' },
  momentum: { bg: '#C2410C', text: '#FFFFFF', border: '#C2410C' },
  blue_chip: { bg: '#1E293B', text: '#F8FAFC', border: '#475569' },
  white_horse: { bg: '#F5F5F4', text: '#44403C', border: '#A8A29E' },
  dividend: { bg: '#991B1B', text: '#FFFFFF', border: '#991B1B' },
  cyclical: { bg: '#92400E', text: '#FFFFFF', border: '#92400E' },
  tech: { bg: '#1D4ED8', text: '#FFFFFF', border: '#1D4ED8' },
  consumption: { bg: '#9D174D', text: '#FFFFFF', border: '#9D174D' },
  high_vol: { bg: '#7F1D1D', text: '#FCA5A5', border: '#7F1D1D' },
  low_vol: { bg: '#14532D', text: '#86EFAC', border: '#14532D' },
}

const DEFAULT_COLOR = { bg: '#374151', text: '#F9FAFB', border: '#374151' }

interface StockTagBadgeProps {
  tag: StockTagItem
  size?: 'small' | 'default'
}

export function StockTagBadge({ tag, size = 'default' }: StockTagBadgeProps) {
  const colors = TAG_COLOR_MAP[tag.tag_key] ?? DEFAULT_COLOR
  const isSmall = size === 'small'

  return (
    <Tooltip title={tag.dimension === 'size' ? '规模' : tag.dimension === 'style' ? '风格' : tag.dimension === 'quality' ? '质量' : tag.dimension}>
      <span
        className="stock-tag-badge"
        style={{
          backgroundColor: colors.bg,
          color: colors.text,
          borderColor: colors.border,
          fontSize: isSmall ? '11px' : '12px',
          padding: isSmall ? '0 5px' : '1px 7px',
          lineHeight: isSmall ? '18px' : '20px',
        }}
      >
        {tag.tag_name}
      </span>
    </Tooltip>
  )
}

interface StockTagListProps {
  tags: StockTagItem[]
  size?: 'small' | 'default'
  max?: number
}

export function StockTagList({ tags, size = 'default', max }: StockTagListProps) {
  if (!tags || tags.length === 0) return null

  const displayTags = max ? tags.slice(0, max) : tags
  const remaining = max ? tags.length - max : 0

  return (
    <span className="stock-tag-list">
      {displayTags.map((tag) => (
        <StockTagBadge key={tag.tag_key} tag={tag} size={size} />
      ))}
      {remaining > 0 ? (
        <Tooltip
          title={tags.slice(max).map((t) => t.tag_name).join('、')}
        >
          <span className="stock-tag-badge stock-tag-badge--more">+{remaining}</span>
        </Tooltip>
      ) : null}
    </span>
  )
}
