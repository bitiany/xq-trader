import type { ReactNode } from 'react'
import './MarketplacePanel.css'

interface MarketplacePanelProps {
  title?: string
  subtitle?: string
  extra?: ReactNode
  children: ReactNode
}

export function MarketplacePanel({ title, subtitle, extra, children }: MarketplacePanelProps) {
  const showHead = Boolean(title || subtitle || extra)

  return (
    <section className="marketplace-panel card">
      {showHead && (
        <div
          className={
            !title && !subtitle && extra
              ? 'marketplace-panel__head marketplace-panel__head--tools'
              : 'marketplace-panel__head'
          }
        >
          <div className="marketplace-panel__titles">
            {title && <h3 className="marketplace-panel__title">{title}</h3>}
            {subtitle && <p className="marketplace-panel__subtitle">{subtitle}</p>}
          </div>
          {extra && <div className="marketplace-panel__extra">{extra}</div>}
        </div>
      )}
      <div className="marketplace-panel__body">{children}</div>
    </section>
  )
}
