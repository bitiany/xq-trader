import { Tabs, Button } from 'antd'
import { useMemo, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { ArrowLeft, FlaskConical, Sparkles } from 'lucide-react'

import {
  fetchStockDiagnosis,
  fetchStockFinancials,
  fetchStockFundFlow,
  fetchStockOverview,
  type MainIndicator,
  type SubIndicator,
  type StockOverviewResponse,
} from '@/api/stock'
import { AsyncSection } from '@/components/common/AsyncSection'
import { StockAnnouncementsPanel } from '@/components/stock/StockAnnouncementsPanel'
import { StockDiagnosisPanel } from '@/components/stock/StockDiagnosisPanel'
import { StockFinancialsPanel } from '@/components/stock/StockFinancialsPanel'
import { StockFundFlowPanel } from '@/components/stock/StockFundFlowPanel'
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
  const [mainIndicator, setMainIndicator] = useState<MainIndicator>('ma')
  const [subIndicator, setSubIndicator] = useState<SubIndicator>('macd')
  const sendMessage = useAgentStore((s) => s.sendMessage)
  const setPageContext = useAgentStore((s) => s.setPageContext)
  const setAgentPanelOpen = useLayoutStore((s) => s.setAgentPanelOpen)

  const requestDeps = useMemo(() => [decodedSymbol] as const, [decodedSymbol])

  const { data: overview, loading, error, reload } = useRequest(
    () => fetchStockOverview(decodedSymbol),
    { deps: requestDeps },
  )

  const [activeTab, setActiveTab] = useState('fundFlow')
  const fundFlowDeps = useMemo(() => (activeTab === 'fundFlow' || subIndicator === 'fundflow' ? requestDeps : ([] as const)), [activeTab, subIndicator, requestDeps])
  const financialsDeps = useMemo(() => (activeTab === 'financials' ? requestDeps : ([] as const)), [activeTab, requestDeps])
  const diagnosisDeps = useMemo(() => (activeTab === 'diagnosis' ? requestDeps : ([] as const)), [activeTab, requestDeps])

  const { data: fundFlow } = useRequest(() => fetchStockFundFlow(decodedSymbol, 1200), { deps: fundFlowDeps, immediate: activeTab === 'fundFlow' || subIndicator === 'fundflow' })
  const { data: financials } = useRequest(() => fetchStockFinancials(decodedSymbol), { deps: financialsDeps, immediate: activeTab === 'financials' })
  const { data: diagnosis } = useRequest(() => fetchStockDiagnosis(decodedSymbol), { deps: diagnosisDeps, immediate: activeTab === 'diagnosis' })

  const stockOverview = overview as StockOverviewResponse | undefined
  const overviewReady = stockOverview?.symbol === decodedSymbol

  const {
    bars,
    maOverlays,
    allOverlays,
    chanlun,
    chanlunLoading,
    loading: klineLoading,
  } = useStockKline(decodedSymbol, mainIndicator, subIndicator)

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

  const mainIndicatorOptions = useMemo(
    () =>
      (['ma', 'boll', 'chanlun'] as MainIndicator[]).map((value) => ({
        label: t(`stock.indicators.${value}`),
        value,
      })),
    [t],
  )
  const subIndicatorOptions = useMemo(
    () =>
      (['macd', 'kdj', 'rsi', 'bias', 'adx', 'fundflow'] as SubIndicator[]).map((value) => ({
        label: t(`stock.indicators.${value}`),
        value,
      })),
    [t],
  )

  const pageLoading = loading || klineLoading || chanlunLoading || !overviewReady

  return (
    <div key={decodedSymbol} className="page stock-page">
      <div className="stock-page__topbar">
        <div className="stock-page__actions">
          <Button
            size="small"
            icon={<ArrowLeft size={14} />}
            onClick={() => navigate(-1)}
          >
            {t('common.back')}
          </Button>
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
            {t('common.aiAnalysis')}
          </Button>
          <Button
            size="small"
            icon={<FlaskConical size={14} />}
            onClick={() => navigate(`/backtest/${encodeURIComponent(decodedSymbol)}`)}
          >
            {t('common.backtest')}
          </Button>
        </div>
      </div>

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
                <StockKlineChart
                  bars={displayBars}
                  mainIndicator={mainIndicator}
                  subIndicator={subIndicator}
                  mainIndicatorOptions={mainIndicatorOptions}
                  subIndicatorOptions={subIndicatorOptions}
                  onMainIndicatorChange={setMainIndicator}
                  onSubIndicatorChange={setSubIndicator}
                  allOverlays={allOverlays}
                  maOverlays={maOverlays}
                  chanlun={chanlun ?? undefined}
                  fundFlowItems={fundFlow?.items}
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
              activeKey={activeTab}
              onChange={setActiveTab}
              items={[
                {
                  key: 'news',
                  label: t('stock.tabs.news'),
                  children: <StockNewsPanel data={null} />,
                },
                {
                  key: 'fundFlow',
                  label: t('stock.tabs.fundFlow'),
                  children: <StockFundFlowPanel data={fundFlow} />,
                },
                {
                  key: 'announcements',
                  label: t('stock.tabs.announcements'),
                  children: <StockAnnouncementsPanel data={null} />,
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
