import { Empty } from 'antd'
import { useTranslation } from 'react-i18next'

import type { StockAnnouncementsResponse } from '@/api/stock'

interface StockAnnouncementsPanelProps {
  data?: StockAnnouncementsResponse
}

export function StockAnnouncementsPanel({ data }: StockAnnouncementsPanelProps) {
  const { t } = useTranslation()

  if (!data || data.items.length === 0) {
    return (
      <div className="stock-panel card">
        <Empty description={data?.placeholder ? t('stock.announcements.placeholder') : t('stock.announcements.empty')} />
      </div>
    )
  }

  return (
    <div className="stock-panel card">
      <ul className="stock-news">
        {data.items.map((item) => (
          <li key={item.id} className="stock-news__item">
            <div className="stock-news__title">{item.title}</div>
            <div className="stock-news__meta">
              {item.source} · {item.published_at}
            </div>
          </li>
        ))}
      </ul>
    </div>
  )
}
