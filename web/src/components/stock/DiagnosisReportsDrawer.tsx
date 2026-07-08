import { Drawer, Empty, Spin, Table } from 'antd'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { fetchStockDiagnosisHistory, type StockDiagnosisHistoryItem } from '@/api/stock'

const MODULE_ORDER = [
  'technical',
  'capital_flow',
  'fundamental',
  'sentiment',
  'industry',
  'institutional',
] as const

interface DiagnosisReportsDrawerProps {
  open: boolean
  symbol: string
  reportsCount: number
  moduleLabels: Record<string, string>
  onClose: () => void
}

export function DiagnosisReportsDrawer({
  open,
  symbol,
  reportsCount,
  moduleLabels,
  onClose,
}: DiagnosisReportsDrawerProps) {
  const { t } = useTranslation()
  const [loading, setLoading] = useState(false)
  const [items, setItems] = useState<StockDiagnosisHistoryItem[]>([])

  useEffect(() => {
    if (!open || !symbol) return
    let cancelled = false
    setLoading(true)
    void fetchStockDiagnosisHistory(symbol, 365)
      .then((response) => {
        if (!cancelled) {
          setItems([...response.items].reverse())
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [open, symbol])

  const columns = [
    {
      title: t('stock.diagnosis.reportDate'),
      dataIndex: 'as_of',
      key: 'as_of',
      width: 120,
    },
    {
      title: t('stock.diagnosis.overallScore'),
      dataIndex: 'overall_score',
      key: 'overall_score',
      width: 100,
      render: (value: number | null) => (value != null ? `${value}分` : '—'),
    },
    ...MODULE_ORDER.map((key) => ({
      title: moduleLabels[key] ?? key,
      key,
      width: 72,
      render: (_: unknown, record: StockDiagnosisHistoryItem) => {
        const score = record.modules[key]
        return score != null ? score.toFixed(1) : '—'
      },
    })),
  ]

  return (
    <Drawer
      title={t('stock.diagnosis.allReports', { count: reportsCount })}
      open={open}
      onClose={onClose}
      size={720}
      destroyOnClose
    >
      {loading ? (
        <Spin tip={t('common.loading')} />
      ) : items.length > 0 ? (
        <Table
          size="small"
          rowKey="as_of"
          pagination={{ pageSize: 15, showSizeChanger: false }}
          dataSource={items}
          columns={columns}
          scroll={{ x: 640 }}
        />
      ) : (
        <Empty description={t('stock.diagnosis.reportsEmpty')} />
      )}
    </Drawer>
  )
}
