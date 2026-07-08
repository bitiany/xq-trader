import type { StockNewsResponse } from '@/api/stock'
import { StockNewsList } from '@/components/stock/StockNewsList'

interface StockNewsPanelProps {
  data?: StockNewsResponse
  collecting?: boolean
  onCollect?: () => void
  onReload?: () => void
}

export function StockNewsPanel({ data, collecting, onCollect, onReload }: StockNewsPanelProps) {
  return (
    <StockNewsList
      data={data}
      emptyKey="stock.news.empty"
      keywordLabelKey="stock.news.keywords"
      collecting={collecting}
      onCollect={onCollect}
      onReload={onReload}
    />
  )
}
