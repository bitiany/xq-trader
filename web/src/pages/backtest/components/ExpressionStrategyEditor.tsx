import { Card } from 'antd'
import { AlertCircle } from 'lucide-react'

export function ExpressionStrategyEditor() {
  return (
    <Card size="small" style={{ background: 'var(--bg-card)' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: 'var(--text-muted)', padding: '16px 0' }}>
        <AlertCircle size={16} />
        <span>表达式策略编辑器（开发中）</span>
      </div>
    </Card>
  )
}
