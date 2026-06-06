import { useTranslation } from 'react-i18next'

import type { StockTableStatItem } from '@/api/data'

interface StockTablesPanelProps {
  tables: StockTableStatItem[]
}

function formatBytes(bytes: number): string {
  if (bytes >= 1024 ** 3) {
    return `${(bytes / 1024 ** 3).toFixed(2)} GB`
  }
  if (bytes >= 1024 ** 2) {
    return `${(bytes / 1024 ** 2).toFixed(1)} MB`
  }
  if (bytes >= 1024) {
    return `${(bytes / 1024).toFixed(1)} KB`
  }
  return `${bytes} B`
}

export function StockTablesPanel({ tables }: StockTablesPanelProps) {
  const { t, i18n } = useTranslation()
  const isZh = i18n.language.startsWith('zh')

  return (
    <div className="table-wrap">
      <table className="data-table">
        <thead>
          <tr>
            <th>{t('data.tables.colName')}</th>
            <th>{t('data.tables.colTable')}</th>
            <th>{t('data.tables.colRows')}</th>
            <th>{t('data.tables.colSize')}</th>
          </tr>
        </thead>
        <tbody>
          {tables.map((item) => (
            <tr key={item.table_name}>
              <td>{isZh ? item.label : item.label_en}</td>
              <td style={{ fontFamily: 'var(--font-mono)' }}>{item.table_name}</td>
              <td>{item.approx_rows.toLocaleString()}</td>
              <td>{item.total_size || formatBytes(item.total_bytes)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
