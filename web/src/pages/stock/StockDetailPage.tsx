import { Segmented, Tabs, Button, Tooltip, Space } from 'antd'
import { useMemo, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { ArrowLeft, FlaskConical, Sparkles } from 'lucide-react'

import {
  fetchStockDiagnosis,
  fetchStockFinancials,
  fetchStockNews,
  fetchStockOverview,
  fetchStockChanlun,
  type IndicatorKind,
  type StockOverviewResponse,
  type ChanlunResponse,
} from '@/api/stock'
import { AsyncSection } from '@/components/common/AsyncSection'
import { StockDiagnosisPanel } from '@/components/stock/StockDiagnosisPanel'
import { StockFinancialsPanel } from '@/components/stock/StockFinancialsPanel'
import { StockKlineChart } from '@/components/stock/StockKlineChart'
import { StockNewsPanel } from '@/components/stock/StockNewsPanel'
import { StockQuoteHeader } from '@/components/stock/StockQuoteHeader'
import { useRequest } from '@/hooks/useRequest'
import { useStockKline } from '@/hooks/useStockKline'
import { useStockQuote } from '@/hooks/useStockQuote'
import { useAgentStore } from '@/stores/agentStore'
import { useLayoutStore } from '@/stores/layoutStore'
import { mergeLiveQuoteIntoBars } from '@/utils/klineLive'
import '@/styles/stock.css'

export function StockDetailPage() {
  const { symbol = '' } = useParams()
  const decodedSymbol = decodeURIComponent(symbol)
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [indicator, setIndicator] = useState<IndicatorKind>('ma')
  const sendMessage = useAgentStore((s) => s.sendMessage)
  const setPageContext = useAgentStore((s) => s.setPageContext)
  const setAgentPanelOpen = useLayoutStore((s) => s.setAgentPanelOpen)

  const requestDeps = useMemo(() => [decodedSymbol] as const, [decodedSymbol])

  const { data: overview, loading, error, reload } = useRequest(
    () => fetchStockOverview(decodedSymbol),
    { deps: requestDeps },
  )
  const { data: news } = useRequest(() => fetchStockNews(decodedSymbol), { deps: requestDeps })
  const { data: financials } = useRequest(() => fetchStockFinancials(decodedSymbol), { deps: requestDeps })
  const { data: diagnosis } = useRequest(() => fetchStockDiagnosis(decodedSymbol), { deps: requestDeps })
  const { data: chanlunData } = useRequest(() => fetchStockChanlun(decodedSymbol), { deps: requestDeps })

  const stockOverview = overview as StockOverviewResponse | undefined
  const overviewReady = stockOverview?.symbol === decodedSymbol

  const {
    bars,
    overlays,
    maOverlays,
    loading: klineLoading,
  } = useStockKline(decodedSymbol, indicator)

  const { quote: liveQuote, inSession } = useStockQuote(decodedSymbol)

  const liveTradeDate = useMemo(() => {
    if (!inSession) {
      return null
    }
    return (
      liveQuote?.timestamp?.slice(0, 10) ??
      stockOverview?.quote?.timestamp?.slice(0, 10) ??
      bars[bars.length - 1]?.trade_date ??
      null
    )
  }, [bars, inSession, liveQuote?.timestamp, stockOverview?.quote])

  const displayQuote = useMemo(() => {
    if (!stockOverview || !overviewReady) {
      return null
    }
    if (inSession && liveQuote && liveQuote.last != null) {
      return liveQuote
    }
    return stockOverview.quote
  }, [inSession, liveQuote, overviewReady, stockOverview])

  const displayBars = useMemo(
    () => mergeLiveQuoteIntoBars(bars, inSession ? liveQuote : null, liveTradeDate),
    [bars, inSession, liveQuote, liveTradeDate],
  )

  const indicatorOptions = useMemo(
    () =>
      (['ma', 'macd', 'kdj', 'rsi', 'bias'] as IndicatorKind[]).map((value) => ({
        label: t(`stock.indicators.${value}`),
        value,
      })),
    [t],
  )

  const pageLoading = loading || klineLoading || !overviewReady

  return (
    <div key={decodedSymbol} className="page stock-page">
      <button
        type="button"
        className="stock-page__back"
        onClick={() => navigate(-1)}
        aria-label={t('common.back')}
      >
        <ArrowLeft size={18} />
      </button>
      <AsyncSection loading={pageLoading} error={error} onRetry={() => void reload()}>
        {overviewReady && stockOverview && displayQuote ? (
          <>
            <StockQuoteHeader
              overview={stockOverview}
              quote={displayQuote}
              valuation={stockOverview.valuation}
            />

            <div className="stock-page__main">
              <div className="stock-page__chart card">
                <div className="stock-page__chart-toolbar">
                  <h3 className="card__title">{t('stock.chart.title')}</h3>
                  <Space>
                    <Tooltip title="AI 全方位分析">
                      <Button
                        size="small"
                        type="primary"
                        icon={<Sparkles size={14} />}
                        onClick={() => {
                          const ctx = { stock_symbol: decodedSymbol, page_source: 'stock_detail' }
                          setPageContext(ctx)
                          setAgentPanelOpen(true)
                          const name = stockOverview?.name ?? decodedSymbol
                          void sendMessage(`请对 ${decodedSymbol}（${name}）进行全方位分析，包括基本面、技术面和持仓情况`, ctx)
                        }}
                      >
                        AI 分析
                      </Button>
                    </Tooltip>
                    <Tooltip title="回测验证">
                      <Button
                        size="small"
                        icon={<FlaskConical size={14} />}
                        onClick={() => navigate(`/backtest/${encodeURIComponent(decodedSymbol)}`)}
                      >
                        回测
                      </Button>
                    </Tooltip>
                    <Segmented
                      size="small"
                      value={indicator}
                      options={indicatorOptions}
                      onChange={(value) => setIndicator(value as IndicatorKind)}
                    />
                  </Space>
                </div>
                <StockKlineChart
                  bars={displayBars}
                  indicator={indicator}
                  overlays={overlays}
                  maOverlays={maOverlays}
                  chanlun={chanlunData as ChanlunResponse | undefined}
                  loading={klineLoading}
                />
              </div>

              {stockOverview.introduction ? (
                <div className="card stock-intro">
                  <div className="card__header">
                    <h3 className="card__title">{t('stock.intro.title')}</h3>
                  </div>
                  <p>{stockOverview.introduction}</p>
                </div>
              ) : null}
            </div>

            <Tabs
              className="stock-page__tabs"
              items={[
                {
                  key: 'news',
                  label: t('stock.tabs.news'),
                  children: <StockNewsPanel data={news} />,
                },
                {
                  key: 'financials',
                  label: t('stock.tabs.financials'),
                  children: <StockFinancialsPanel data={financials} />,
                },
                {
                  key: 'diagnosis',
                  label: t('stock.tabs.diagnosis'),
                  children: <StockDiagnosisPanel data={diagnosis} />,
                },
              ]}
            />
          </>
        ) : null}
      </AsyncSection>
    </div>
  )
}
