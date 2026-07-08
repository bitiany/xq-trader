import { Tabs, Button, Dropdown, message } from 'antd'
import type { MenuProps } from 'antd'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { ArrowLeft, FlaskConical, Sparkles, Layers, LineChart, TrendingUp, Wallet } from 'lucide-react'

import {
  fetchStockAnnouncements,
  fetchStockDiagnosis,
  fetchStockDiagnosisHistory,
  fetchStockFinancials,
  fetchStockFundFlow,
  fetchStockNews,
  fetchStockOverview,
  type MainIndicator,
  type SubIndicator,
  type StockOverviewResponse,
} from '@/api/stock'
import { triggerCollectTask } from '@/api/data'
import { AsyncSection } from '@/components/common/AsyncSection'
import { StockAnnouncementsPanel } from '@/components/stock/StockAnnouncementsPanel'
import { StockDiagnosisPanel } from '@/components/stock/StockDiagnosisPanel'
import { StockFinancialsPanel } from '@/components/stock/StockFinancialsPanel'
import { StockFactorDrawer } from '@/components/stock/StockFactorDrawer'
import { StockFundFlowPanel } from '@/components/stock/StockFundFlowPanel'
import { StockKlineChart } from '@/components/stock/StockKlineChart'
import { StockNewsPanel } from '@/components/stock/StockNewsPanel'
import { StockQuoteHeader } from '@/components/stock/StockQuoteHeader'
import { useRequest } from '@/hooks/useRequest'
import { useRequestErrorToast } from '@/hooks/useRequestErrorToast'
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
  const [factorDrawerOpen, setFactorDrawerOpen] = useState(false)
  const sendMessage = useAgentStore((s) => s.sendMessage)
  const setSessionScope = useAgentStore((s) => s.setSessionScope)
  const setAgentPanelOpen = useLayoutStore((s) => s.setAgentPanelOpen)

  const triggerAnalysis = (promptKey: string) => {
    const ctx = { stock_symbol: decodedSymbol, page_source: 'stock_detail' }
    setAgentPanelOpen(true)
    const name = stockOverview?.name ?? decodedSymbol
    const sym = decodedSymbol
    const prompts: Record<string, string> = {
      full: `请对 ${sym}（${name}）进行全方位投研分析：按国泰君安五步法推演基本面（信息差→逻辑差→超预期差→催化剂→结论），结合技术面走势、资金面动向与市场情绪综合研判，交叉验证后给出交易策略建议（含入场价、止损价、目标位、仓位建议）。`,
      technical: `请对 ${sym}（${name}）进行技术面深度分析：研判当前趋势方向与强度，识别关键支撑/压力位，分析 MACD/KDJ/RSI 指标信号，结合缠论笔/线段/中枢判断走势结构，给出 ATR 波动率与短期操作建议。`,
      fund: `请对 ${sym}（${name}）进行资金面分析：研判近期主力资金净流入/流出趋势，分析超大单/大单/中单/小单资金博弈格局，识别资金流向与股价走势的背离信号，评估主力控盘程度。`,
      basic: `请快速扫描 ${sym}（${name}）的基本面：最新估值水平（PE/PB/PS/股息率）、核心财务指标（营收/净利润/ROE/毛利率）、近期公告与新闻要闻，给出基本面评级与关键风险点。`,
      position: `请评估 ${sym}（${name}）的持仓情况：查询当前持仓与账户资产，分析持仓成本与浮盈浮亏，结合技术面与资金面给出操作建议（加仓/持有/减仓/清仓）。`,
    }
    void sendMessage(prompts[promptKey] ?? prompts.full, ctx)
  }

  const analysisMenuItems: MenuProps['items'] = [
    { key: 'full', label: t('stock.ai.full'), icon: <Sparkles size={14} /> },
    { key: 'technical', label: t('stock.ai.technical'), icon: <LineChart size={14} /> },
    { key: 'fund', label: t('stock.ai.fund'), icon: <TrendingUp size={14} /> },
    { key: 'basic', label: t('stock.ai.basic'), icon: <Layers size={14} /> },
    { type: 'divider' },
    { key: 'position', label: t('stock.ai.position'), icon: <Wallet size={14} /> },
  ]

  // 个股页注册标的私有会话：进入切到 stock:{symbol}，离开回退全局会话
  useEffect(() => {
    setSessionScope(`stock:${decodedSymbol}`)
    return () => setSessionScope(null)
  }, [decodedSymbol, setSessionScope])

  const requestDeps = useMemo(() => [decodedSymbol] as const, [decodedSymbol])

  const { data: overview, loading, error, reload } = useRequest(
    () => fetchStockOverview(decodedSymbol),
    { deps: requestDeps },
  )

  const [activeTab, setActiveTab] = useState('diagnosis')
  const fundFlowDeps = useMemo(
    () =>
      activeTab === 'fundFlow' || subIndicator === 'fundflow'
        ? requestDeps
        : ([] as const),
    [activeTab, subIndicator, requestDeps],
  )
  const financialsDeps = useMemo(() => (activeTab === 'financials' ? requestDeps : ([] as const)), [activeTab, requestDeps])
  const diagnosisDeps = useMemo(() => (activeTab === 'diagnosis' ? requestDeps : ([] as const)), [activeTab, requestDeps])
  const newsDeps = useMemo(() => (activeTab === 'news' ? requestDeps : ([] as const)), [activeTab, requestDeps])
  const announcementsDeps = useMemo(() => (activeTab === 'announcements' ? requestDeps : ([] as const)), [activeTab, requestDeps])

  const diagnosisRefreshRef = useRef(false)
  const [newsCollecting, setNewsCollecting] = useState(false)

  const { data: fundFlow, error: fundFlowError } = useRequest(() => fetchStockFundFlow(decodedSymbol, 1200), {
    deps: fundFlowDeps,
    immediate: activeTab === 'fundFlow' || subIndicator === 'fundflow',
  })
  const { data: financials, error: financialsError } = useRequest(
    () => fetchStockFinancials(decodedSymbol),
    { deps: financialsDeps, immediate: activeTab === 'financials' },
  )
  const {
    data: diagnosis,
    loading: diagnosisLoading,
    error: diagnosisError,
    reload: reloadDiagnosis,
  } = useRequest(
    () => fetchStockDiagnosis(decodedSymbol, diagnosisRefreshRef.current),
    { deps: diagnosisDeps, immediate: activeTab === 'diagnosis' },
  )
  const {
    data: diagnosisHistory,
    loading: diagnosisHistoryLoading,
    error: diagnosisHistoryError,
    reload: reloadDiagnosisHistory,
  } = useRequest(
    () => fetchStockDiagnosisHistory(decodedSymbol, 90),
    { deps: diagnosisDeps,
      immediate: activeTab === 'diagnosis' },
  )
  const { data: news, reload: reloadNews, error: newsError } = useRequest(
    () => fetchStockNews(decodedSymbol),
    { deps: newsDeps, immediate: activeTab === 'news' },
  )
  const { data: announcements, reload: reloadAnnouncements, error: announcementsError } = useRequest(
    () => fetchStockAnnouncements(decodedSymbol),
    { deps: announcementsDeps,
      immediate: activeTab === 'announcements' },
  )

  const handleDiagnosisRefresh = () => {
    diagnosisRefreshRef.current = true
    void reloadDiagnosis()
      .then(() => reloadDiagnosisHistory())
      .finally(() => {
        diagnosisRefreshRef.current = false
      })
  }

  const handleCollectNews = async () => {
    setNewsCollecting(true)
    try {
      const result = await triggerCollectTask('market.stock_news_collect', {
        stock_codes: [decodedSymbol],
        fetch_news: true,
        fetch_announcements: true,
      })
      message.success(result.message || t('stock.news.collectSuccess'))
      if (activeTab === 'news') {
        await reloadNews()
      }
      if (activeTab === 'announcements') {
        await reloadAnnouncements()
      }
    } catch (err) {
      message.error(err instanceof Error ? err.message : t('common.loadFailed'))
    } finally {
      setNewsCollecting(false)
    }
  }

  const stockOverview = overview as StockOverviewResponse | undefined
  const overviewReady = stockOverview?.symbol === decodedSymbol

  const {
    bars,
    maOverlays,
    allOverlays,
    chanlun,
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

  const hasOverview = overviewReady && stockOverview != null && displayQuote != null
  const pageLoading = loading && !overview && !error
  const showPageBody = !loading

  useRequestErrorToast(error, t('stock.loadErrors.overview'))
  useRequestErrorToast(diagnosisError, t('stock.loadErrors.diagnosis'))
  useRequestErrorToast(diagnosisHistoryError, t('stock.loadErrors.diagnosisHistory'))
  useRequestErrorToast(fundFlowError, t('stock.tabs.fundFlow'))
  useRequestErrorToast(financialsError, t('stock.tabs.financials'))
  useRequestErrorToast(newsError, t('stock.tabs.news'))
  useRequestErrorToast(announcementsError, t('stock.tabs.announcements'))

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
          <Dropdown
            menu={{ items: analysisMenuItems, onClick: ({ key }) => triggerAnalysis(key) }}
            trigger={['click']}
          >
            <Button
              size="small"
              type="primary"
              icon={<Sparkles size={14} />}
            >
              {t('common.aiAnalysis')}
            </Button>
          </Dropdown>
          <Button
            size="small"
            icon={<FlaskConical size={14} />}
            onClick={() => navigate(`/backtest/${encodeURIComponent(decodedSymbol)}`)}
          >
            {t('common.backtest')}
          </Button>
          <Button
            size="small"
            icon={<Layers size={14} />}
            onClick={() => setFactorDrawerOpen(true)}
          >
            截面因子
          </Button>
        </div>
      </div>

      <AsyncSection loading={pageLoading} onRetry={() => void reload()}>
        {showPageBody ? (
          <>
            {hasOverview ? (
              <StockQuoteHeader
                overview={stockOverview}
                quote={displayQuote}
                valuation={stockOverview.valuation}
              />
            ) : (
              <div className="card stock-page__fallback-header">
                <h2 className="stock-page__symbol">{decodedSymbol}</h2>
              </div>
            )}

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

              {hasOverview && stockOverview.introduction ? (
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
                  children: (
                    <StockNewsPanel
                      data={news}
                      collecting={newsCollecting}
                      onCollect={handleCollectNews}
                      onReload={() => void reloadNews()}
                    />
                  ),
                },
                {
                  key: 'fundFlow',
                  label: t('stock.tabs.fundFlow'),
                  children: <StockFundFlowPanel data={fundFlow} />,
                },
                {
                  key: 'announcements',
                  label: t('stock.tabs.announcements'),
                  children: (
                    <StockAnnouncementsPanel
                      data={announcements}
                      collecting={newsCollecting}
                      onCollect={handleCollectNews}
                      onReload={() => void reloadAnnouncements()}
                    />
                  ),
                },
                {
                  key: 'financials',
                  label: t('stock.tabs.financials'),
                  children: <StockFinancialsPanel data={financials} />,
                },
                {
                  key: 'diagnosis',
                  label: t('stock.tabs.diagnosis'),
                  children: (
                    <StockDiagnosisPanel
                      symbol={decodedSymbol}
                      data={diagnosis}
                      history={diagnosisHistory}
                      loading={diagnosisLoading}
                      historyLoading={diagnosisHistoryLoading}
                      error={diagnosisError}
                      onDeepAnalysis={() => triggerAnalysis('full')}
                      onRefresh={handleDiagnosisRefresh}
                      onSummaryRefresh={() => void reloadDiagnosis()}
                      onRetry={() => void reloadDiagnosis()}
                    />
                  ),
                },
              ]}
            />
          </>
        ) : null}
      </AsyncSection>
      <StockFactorDrawer
        open={factorDrawerOpen}
        symbol={decodedSymbol}
        stockName={stockOverview?.name}
        onClose={() => setFactorDrawerOpen(false)}
      />
    </div>
  )
}
