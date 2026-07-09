import type { StockAnnouncementsResponse } from '@/api/stock'
import { StockNewsList } from '@/components/stock/StockNewsList'

interface StockAnnouncementsPanelProps {
  data?: StockAnnouncementsResponse
  collecting?: boolean
  loading?: boolean
  error?: string | null
  onCollect?: () => void
  onReload?: () => void
}

export function StockAnnouncementsPanel({
  data,
  collecting,
  loading,
  error,
  onCollect,
  onReload,
}: StockAnnouncementsPanelProps) {
  return (
    <StockNewsList
      data={data}
      emptyKey="stock.announcements.empty"
      keywordLabelKey="stock.announcements.type"
      collectLabelKey="stock.announcements.collect"
      collecting={collecting}
      loading={loading}
      error={error}
      onCollect={onCollect}
      onReload={onReload}
    />
  )
}
