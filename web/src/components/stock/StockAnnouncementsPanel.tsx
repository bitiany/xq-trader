import type { StockAnnouncementsResponse } from '@/api/stock'
import { StockNewsList } from '@/components/stock/StockNewsList'

interface StockAnnouncementsPanelProps {
  data?: StockAnnouncementsResponse
  collecting?: boolean
  onCollect?: () => void
  onReload?: () => void
}

export function StockAnnouncementsPanel({
  data,
  collecting,
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
      onCollect={onCollect}
      onReload={onReload}
    />
  )
}
