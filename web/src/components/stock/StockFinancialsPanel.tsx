import { Empty } from 'antd'
import { useTranslation } from 'react-i18next'

import type { FinancialReportSummary, StockFinancialsResponse } from '@/api/stock'
import { StockPanelState } from '@/components/stock/StockPanelState'

interface StockFinancialsPanelProps {
  data?: StockFinancialsResponse
  loading?: boolean
  error?: string | null
  onRetry?: () => void
}

const HIGHLIGHT_LABELS: Record<string, string> = {
  total_revenue: 'stock.financials.totalRevenue',
  revenue: 'stock.financials.revenue',
  n_income: 'stock.financials.netIncome',
  basic_eps: 'stock.financials.basicEps',
  operate_profit: 'stock.financials.operateProfit',
  total_assets: 'stock.financials.totalAssets',
  total_liab: 'stock.financials.totalLiab',
  total_hldr_eqy_exc_min_int: 'stock.financials.equity',
  money_cap: 'stock.financials.moneyCap',
  n_cashflow_act: 'stock.financials.cashflowOp',
  n_cashflow_inv_act: 'stock.financials.cashflowInv',
  n_cash_flows_fnc_act: 'stock.financials.cashflowFin',
  free_cashflow: 'stock.financials.freeCashflow',
  eps: 'stock.financials.eps',
  roe: 'stock.financials.roe',
  roa: 'stock.financials.roa',
  grossprofit_margin: 'stock.financials.grossMargin',
  netprofit_margin: 'stock.financials.netMargin',
  debt_to_assets: 'stock.financials.debtRatio',
  current_ratio: 'stock.financials.currentRatio',
}

function ReportBlock({
  title,
  report,
}: {
  title: string
  report: FinancialReportSummary | null | undefined
}) {
  const { t } = useTranslation()

  if (!report) {
    return (
      <div className="stock-financials__block">
        <h4>{title}</h4>
        <p className="stock-financials__empty">{t('stock.financials.noData')}</p>
      </div>
    )
  }

  return (
    <div className="stock-financials__block">
      <h4>{title}</h4>
      <div className="stock-financials__period">
        {t('stock.financials.reportPeriod')}: {report.end_date ?? '--'}
      </div>
      <div className="stock-financials__grid">
        {Object.entries(report.highlights).map(([key, value]) => (
          <div key={key} className="stock-financials__item">
            <span>{t(HIGHLIGHT_LABELS[key] ?? key)}</span>
            <strong>{value == null ? '--' : typeof value === 'number' ? value.toLocaleString() : value}</strong>
          </div>
        ))}
      </div>
    </div>
  )
}

export function StockFinancialsPanel({ data, loading, error, onRetry }: StockFinancialsPanelProps) {
  const { t } = useTranslation()

  if (loading && !data) {
    return <StockPanelState loading />
  }

  if (error && !data) {
    return <StockPanelState error={error} onRetry={onRetry} />
  }

  if (!data) {
    return (
      <div className="stock-panel card">
        <Empty description={t('stock.financials.noData')} />
      </div>
    )
  }

  return (
    <div className="stock-panel card">
      <ReportBlock title={t('stock.financials.income')} report={data.income_statement} />
      <ReportBlock title={t('stock.financials.balance')} report={data.balance_sheet} />
      <ReportBlock title={t('stock.financials.cashflow')} report={data.cash_flow} />
      <ReportBlock title={t('stock.financials.indicator')} report={data.financial_indicator} />
    </div>
  )
}
