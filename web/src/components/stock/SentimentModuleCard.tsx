import type { DiagnosisModuleScore } from '@/api/stock'
import { DiagnosisModuleCard } from '@/components/stock/DiagnosisModuleCard'
import { formatDate } from '@/utils/format'

interface SentimentModuleCardProps {
  module: DiagnosisModuleScore
  onDetail?: () => void
}

export function SentimentModuleCard({ module, onDetail }: SentimentModuleCardProps) {
  const detail = module.detail ?? {}
  const recentNews = (detail.recent_news as Array<{ title?: string; published_at?: string }> | undefined) ?? []

  return (
    <DiagnosisModuleCard module={module} onDetail={onDetail}>
      <div className="diagnosis-module-card__meta">
        <span>新闻 {detail.news_count ?? 0}</span>
        <span>公告 {detail.announcement_count ?? 0}</span>
        <span>
          舆情 {detail.sentiment_score != null ? Number(detail.sentiment_score).toFixed(2) : '—'}
        </span>
      </div>
      {recentNews.length > 0 ? (
        <ul className="diagnosis-news-list">
          {recentNews.map((item, index) => (
            <li key={`${item.published_at ?? index}-${item.title ?? index}`}>
              <span className="diagnosis-news-list__date">{formatDate(item.published_at)}</span>
              <span className="diagnosis-news-list__title">{item.title ?? '—'}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="diagnosis-module-card__hint">近 30 日暂无新闻摘要</p>
      )}
    </DiagnosisModuleCard>
  )
}
